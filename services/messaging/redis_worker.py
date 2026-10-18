import json
import logging
import os
import socket
import time
import uuid

import redis

from config import Config
from app import create_app
from models.models import db
from schemas.incoming_message import IncomingMessage
from platforms.registry import get_handler
from services.domain.page_service import PageService
from services.messaging.message_processor import run_agent
from services.messaging.webhook_service import _send_reply
from services.messaging.redis_queue import DUE_ZSET_KEY, get_redis_client
from notification_center import send_production_alert

PRESCRIPTION_SEPARATOR = "\n\n---\n\n"

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

POLL_INTERVAL_SECONDS = 0.5
PROCESSING_STALE_SECONDS = 120
RECOVERY_INTERVAL_SECONDS = 30

# ============================================================================
# Worker Identity
# ============================================================================

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def _new_owner_token() -> str:
    """Generate a globally unique owner token for a conversation claim."""
    return f"{WORKER_ID}:{uuid.uuid4().hex}"


# ============================================================================
# Redis Key Helpers
# ============================================================================

def _queue_key(conversation_key: str) -> str:
    return f"queue:{conversation_key}"


def _processing_key(conversation_key: str) -> str:
    return f"processing:{conversation_key}"


def _processing_owner_key(conversation_key: str) -> str:
    return f"processing_owner:{conversation_key}"


def _processing_heartbeat_key(conversation_key: str) -> str:
    return f"processing_heartbeat:{conversation_key}"


def parse_conversation_key(conversation_key: str) -> tuple[int, str, str]:
    platform_id_str, page_id, sender_id = conversation_key.split(":", 2)
    return int(platform_id_str), page_id, sender_id


# ============================================================================
# Lua Scripts (Atomic Claim, Heartbeat, Finish, Recovery)
# ============================================================================

_CLAIM_SCRIPT = """
local removed = redis.call('ZREM', KEYS[1], ARGV[1])

if removed == 0 then
    return 0
end

if redis.call('EXISTS', KEYS[3]) == 1 then
    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[1])
    return 0
end

if redis.call('EXISTS', KEYS[2]) == 0 then
    return 0
end

redis.call('RENAME', KEYS[2], KEYS[3])

redis.call('SET', KEYS[4], ARGV[2])
redis.call('SET', KEYS[5], ARGV[3])

return 1
"""

_HEARTBEAT_SCRIPT = """
local current_owner = redis.call('GET', KEYS[1])

if not current_owner then
    return 0
end

if current_owner ~= ARGV[1] then
    return 0
end

redis.call('SET', KEYS[2], ARGV[2])

return 1
"""

_FINISH_SCRIPT = """
local current_owner = redis.call('GET', KEYS[2])

if not current_owner then
    return 0
end

if current_owner ~= ARGV[1] then
    return 0
end

redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2])
redis.call('DEL', KEYS[3])

return 1
"""

_RECOVER_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end

local owner = redis.call('GET', KEYS[4])
local heartbeat = redis.call('GET', KEYS[5])

if not owner or not heartbeat then
    return 0
end

local age = tonumber(ARGV[2]) - tonumber(heartbeat)

if age < tonumber(ARGV[3]) then
    return 0
end

while redis.call('LLEN', KEYS[1]) > 0 do
    local item = redis.call('RPOP', KEYS[1])
    redis.call('LPUSH', KEYS[2], item)
end

redis.call('ZADD', KEYS[3], ARGV[2], ARGV[1])

redis.call('DEL', KEYS[4])
redis.call('DEL', KEYS[5])

return 1
"""


# ============================================================================
# Claim & Ownership
# ============================================================================

def claim_due_conversations(
    r: redis.Redis,
    claim_script,
) -> list[tuple[str, str]]:
    now = time.time()
    candidates = r.zrangebyscore(DUE_ZSET_KEY, "-inf", now)
    claimed: list[tuple[str, str]] = []

    for conversation_key in candidates:
        owner_token = _new_owner_token()
        result = claim_script(
            keys=[
                DUE_ZSET_KEY,
                _queue_key(conversation_key),
                _processing_key(conversation_key),
                _processing_owner_key(conversation_key),
                _processing_heartbeat_key(conversation_key),
            ],
            args=[
                conversation_key,
                owner_token,
                now,
            ],
        )

        if result == 1:
            claimed.append((conversation_key, owner_token))
            logger.info(
                "[WORKER CLAIM] worker=%s conversation=%s",
                WORKER_ID, conversation_key,
            )

    return claimed


def _heartbeat(
    r: redis.Redis,
    conversation_key: str,
    owner_token: str,
    heartbeat_script,
) -> bool:
    result = heartbeat_script(
        keys=[
            _processing_owner_key(conversation_key),
            _processing_heartbeat_key(conversation_key),
        ],
        args=[
            owner_token,
            time.time(),
        ],
    )
    if result == 1:
        return True

    logger.warning(
        "[WORKER OWNERSHIP LOST] heartbeat rejected | worker=%s | conversation=%s",
        WORKER_ID, conversation_key,
    )
    return False


def _require_ownership(
    r: redis.Redis,
    conversation_key: str,
    owner_token: str,
    heartbeat_script,
) -> None:
    if not _heartbeat(r, conversation_key, owner_token, heartbeat_script):
        raise RuntimeError(f"Worker lost ownership of conversation={conversation_key}")


def _finish_processing(
    r: redis.Redis,
    conversation_key: str,
    owner_token: str,
    finish_script,
) -> bool:
    result = finish_script(
        keys=[
            _processing_key(conversation_key),
            _processing_owner_key(conversation_key),
            _processing_heartbeat_key(conversation_key),
        ],
        args=[owner_token],
    )
    if result == 1:
        logger.info(
            "[WORKER FINISH] worker=%s conversation=%s",
            WORKER_ID, conversation_key,
        )
        return True

    logger.warning(
        "[WORKER FINISH REJECTED] ownership lost | worker=%s | conversation=%s",
        WORKER_ID, conversation_key,
    )
    return False


# ============================================================================
# Agent Input Builder
# ============================================================================

def build_agent_text(entries: list[dict]) -> str:
    """Builds the agent's input: user texts and numbered images, in their real arrival order."""
    lines: list[str] = []
    image_no = 0

    for entry in entries:
        image = entry.get("image")

        if image:
            image_no += 1
            status = image.get("status")

            if status == "valid":
                tests = ", ".join(image.get("tests", []))
                lines.append(f"[Image #{image_no} - OCR Extracted Tests]: {tests}")

            elif status == "pending":
                lines.append(f"[Image #{image_no} - Prescription detected but unclear]")

            elif status == "offer":
                lines.append(f"[Image #{image_no} - LAB OFFER / BUNDLE FLYER]")
                offers = image.get("offers") or []
                if offers:
                    for offer in offers:
                        lines.append(
                            f"- {offer['name']} | Price on flyer: {offer.get('price') or 'not shown'}"
                        )
                else:
                    lines.append("- (offer name could not be read)")

            else:
                lines.append(f"[Image #{image_no} - spam or irrelevant]")

        elif entry.get("text"):
            lines.append(f"[User text]: {entry['text']}")

    return "\n".join(lines)


# ============================================================================
# Process Conversation
# ============================================================================

def process_conversation(
    r: redis.Redis,
    conversation_key: str,
    owner_token: str,
    heartbeat_script,
    finish_script,
    app=None,
) -> None:
    if app is None:
        app = create_app()

    platform_id, page_id, sender_id = parse_conversation_key(conversation_key)
    processing_key = _processing_key(conversation_key)

    with app.app_context():
        try:
            _require_ownership(r, conversation_key, owner_token, heartbeat_script)

            raw_items = r.lrange(processing_key, 0, -1)
            if not raw_items:
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            entries = [json.loads(raw) for raw in raw_items]
            entries.sort(key=lambda entry: entry.get("received_at", 0))

            page = PageService.get_page_by_page_and_platform(page_id=page_id, platform_id=platform_id)
            if not page:
                logger.error(
                    "[WORKER] Page not found | page_id=%s | platform_id=%s | conversation=%s",
                    page_id, platform_id, conversation_key,
                )
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            handler = get_handler(platform_id, page)

            combined_text = build_agent_text(entries)
            logger.info("[DEBUG agent_text]\n%s", combined_text)

            if not combined_text:
                _require_ownership(r, conversation_key, owner_token, heartbeat_script)
                _finish_processing(r, conversation_key, owner_token, finish_script)
                return

            _require_ownership(r, conversation_key, owner_token, heartbeat_script)
            handler.send_typing(sender_id)

            incoming = IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=handler.platform_name,
                msg_type="text",
                text=combined_text,
            )

            reply, pdf_bytes, visit_reference = run_agent(
                incoming,
                ocr_usage=None,
                laboratory_id=page.laboratory_id,
            )

            _require_ownership(r, conversation_key, owner_token, heartbeat_script)
            _send_reply(handler, sender_id, reply, pdf_bytes, visit_reference)

            _require_ownership(r, conversation_key, owner_token, heartbeat_script)
            finished = _finish_processing(r, conversation_key, owner_token, finish_script)

            if not finished:
                logger.warning(
                    "[WORKER] Response sent but finish rejected | conversation=%s",
                    conversation_key,
                )
                return

            logger.info(
                "[WORKER] Processed conversation | worker=%s | conversation=%s | items=%d | has_reply=%s",
                WORKER_ID, conversation_key, len(entries), bool(reply),
            )

        except RuntimeError as exc:
            logger.warning(
                "[WORKER] Processing stopped (ownership lost) | worker=%s | conversation=%s | reason=%s",
                WORKER_ID, conversation_key, exc,
            )
        except Exception as exc:
            logger.exception(
                "[WORKER] Failed processing conversation=%s: %s",
                conversation_key, exc,
            )
            db.session.rollback()
            try:
                send_production_alert(
                    subject="Redis Worker Processing Exception",
                    body_or_error=exc,
                    context={"conversation_key": conversation_key, "worker_id": WORKER_ID},
                )
            except Exception:
                logger.exception("[WORKER] Failed sending production alert")
        finally:
            db.session.remove()


# ============================================================================
# Recovery & Main Loop
# ============================================================================

def recover_stale_processing(
    r: redis.Redis,
    recover_script,
) -> None:
    now = time.time()
    pattern = "processing_heartbeat:*"

    for heartbeat_key in r.scan_iter(match=pattern):
        conversation_key = heartbeat_key.split("processing_heartbeat:", 1)[1]
        recovered = recover_script(
            keys=[
                _processing_key(conversation_key),
                _queue_key(conversation_key),
                DUE_ZSET_KEY,
                _processing_owner_key(conversation_key),
                heartbeat_key,
            ],
            args=[
                conversation_key,
                now,
                PROCESSING_STALE_SECONDS,
            ],
        )

        if recovered == 1:
            logger.warning(
                "[WORKER RECOVERY] Recovered stale conversation=%s",
                conversation_key,
            )


def run_worker_forever(
    r: redis.Redis,
    app=None,
) -> None:
    claim_script = r.register_script(_CLAIM_SCRIPT)
    heartbeat_script = r.register_script(_HEARTBEAT_SCRIPT)
    finish_script = r.register_script(_FINISH_SCRIPT)
    recover_script = r.register_script(_RECOVER_SCRIPT)

    if app is None:
        app = create_app()

    last_recovery_check = 0.0

    logger.info(
        "[WORKER] Started | worker=%s | poll=%.1fs | stale=%ss",
        WORKER_ID, POLL_INTERVAL_SECONDS, PROCESSING_STALE_SECONDS,
    )

    while True:
        try:
            claimed = claim_due_conversations(r, claim_script)

            for conversation_key, owner_token in claimed:
                process_conversation(
                    r,
                    conversation_key,
                    owner_token,
                    heartbeat_script,
                    finish_script,
                    app=app,
                )

            now = time.time()
            if now - last_recovery_check >= RECOVERY_INTERVAL_SECONDS:
                recover_stale_processing(r, recover_script)
                last_recovery_check = now

        except Exception:
            logger.exception(
                "[WORKER] Unexpected error in main loop | worker=%s", WORKER_ID,
            )

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    redis_client = get_redis_client()
    run_worker_forever(redis_client)