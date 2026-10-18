import logging
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, abort, current_app

from config import Config
from services.messaging.webhook_service import process_facebook_payload, process_waha_payload

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("webhook", __name__, url_prefix="/webhook")

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN") or os.environ.get("FB_VERIFY_TOKEN", "")

# Bounded thread pool for handling webhook background processing (SEC-5)
webhook_executor = ThreadPoolExecutor(
    max_workers=Config.WEBHOOK_THREAD_POOL_SIZE,
    thread_name_prefix="webhook_worker",
)


@webhook_bp.route("/facebook", methods=["GET", "POST"])
def facebook_webhook():
    """
    Facebook Messenger & Page Webhook:
    - GET: Responds to Meta verification challenge.
    - POST: Quickly acknowledges platform with 200 OK and delegates to background processor.
    """
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge", "")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            logger.info("[FB WEBHOOK] Verification challenge successful")
            return challenge, 200

        logger.warning("[FB WEBHOOK] Verification failed: mode=%s token=%s", mode, token)
        abort(403)

    payload = request.get_json(silent=True) or {}
    if not payload:
        return "EVENT_RECEIVED", 200

    logger.info("[FB WEBHOOK] POST received | entries=%d", len(payload.get("entry", [])))

    app = current_app._get_current_object()
    webhook_executor.submit(process_facebook_payload, payload, app)

    return "EVENT_RECEIVED", 200


@webhook_bp.route("/waha", methods=["POST"])
def waha_webhook():
    """
    WAHA WhatsApp Webhook:
    - POST: Quickly acknowledges WAHA with 200 OK and delegates to background processor.
    """
    payload = request.get_json(silent=True) or {}
    if not payload:
        return "OK", 200

    logger.info("[WAHA WEBHOOK] POST received | event=%s", payload.get("event"))

    app = current_app._get_current_object()
    webhook_executor.submit(process_waha_payload, payload, app)

    return "OK", 200