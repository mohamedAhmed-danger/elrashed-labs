import json
import logging
import time
import redis

from config import Config

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 7
DUE_ZSET_KEY = "conversations:due"


def _conversation_key(platform_id: int, page_id: str, sender_id: str) -> str:
    return f"{platform_id}:{page_id}:{sender_id}"


def _queue_key(conversation_key: str) -> str:
    return f"queue:{conversation_key}"


def get_redis_client(url: str | None = None) -> redis.Redis:
    redis_url = url or getattr(Config, "REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(redis_url, decode_responses=True)


def enqueue_message(
    r: redis.Redis,
    platform_id: int,
    page_id: str,
    sender_id: str,
    platform_name: str,
    text: str,
    received_at: float | None = None,
    image_result:dict | None = None,
) -> None:
    """
    Enqueues an incoming agent_text payload into the Redis-backed conversation queue.

    DESIGN DECISION: There is intentionally no distributed lock around enqueue.
    Two near-simultaneous messages landing on different workers is an accepted rare edge case
    (at most a rare duplicate-billing event), traded off for simplicity.
    """
    conversation_key = _conversation_key(platform_id, page_id, sender_id)
    queue_key = _queue_key(conversation_key)

    item = {
        "text": text,
        "image": image_result,
        "received_at": received_at if received_at is not None else time.time(),
    }

    due_at = time.time() + DEBOUNCE_SECONDS

    # RPUSH + ZADD in one atomic MULTI/EXEC transaction
    pipe = r.pipeline(transaction=True)
    pipe.rpush(queue_key, json.dumps(item, ensure_ascii=False))
    pipe.zadd(DUE_ZSET_KEY, {conversation_key: due_at})
    pipe.execute()

    logger.info(
        "[REDIS QUEUE] enqueued | conversation=%s | due_in=%.1fs",
        conversation_key, DEBOUNCE_SECONDS,
    )
