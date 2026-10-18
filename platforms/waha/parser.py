import logging


from schemas.incoming_message import IncomingMessage

logger = logging.getLogger(__name__)

# أنواع الرسائل اللي مش هنرد عليها (ريأكشنز، حذف رسالة، إلخ)
IGNORED_MSG_TYPES = {"e2e_notification", "notification_template", "revoked", "reaction"}


def _is_ignored_chat(chat_id: str) -> bool:
    """تجاهل الجروبات، الاستوري/الحالة، النشرات، والبرودكاست"""
    if not chat_id:
        return True
    return (
        "@g.us" in chat_id           # جروب
        or "@newsletter" in chat_id  # قناة/نشرة
        or "@broadcast" in chat_id   # برودكاست (يشمل status@broadcast)
    )


def _is_ad_referral(payload: dict) -> bool:
    """
    تجاهل رسائل الإعلانات (Click-to-WhatsApp Ads).
    غالبًا بتوصل بحقل referral/ctwaContext جوه raw data الرسالة.
    """
    raw = payload.get("_data", {}) or {}
    return bool(
        raw.get("ctwaContext")
        or raw.get("isAd")
        or (payload.get("referral") or {}).get("source_type") == "ad"
    )


def parse_waha_message(
    payload: dict,
    page_id,
    platform_id,
    platform_name: str = "WhatsApp",
) -> IncomingMessage | None:
    try:
        if not isinstance(payload, dict):
            logger.debug("[WAHA PARSER] Payload is not a dict")
            return None

        if payload.get("fromMe"):
            logger.debug("[WAHA PARSER] Ignoring fromMe message")
            return None

        sender_id = payload.get("from")
        if not sender_id:
            logger.warning("WAHA payload received without 'from' field")
            return None

        if _is_ignored_chat(sender_id):
            logger.debug("Ignoring non-personal chat: %s", sender_id)
            return None

        raw_type = (payload.get("_data", {}) or {}).get("type", "")
        if raw_type in IGNORED_MSG_TYPES:
            logger.debug("Ignoring WAHA event type: %s", raw_type)
            return None

        if _is_ad_referral(payload):
            logger.debug("Ignoring ad-referral message from: %s", sender_id)
            return None

        has_media = payload.get("hasMedia", False)
        media = payload.get("media")
        msg_body = payload.get("body")

        if has_media and media:
            mimetype = media.get("mimetype", "")

            if "image/webp" in mimetype:
                msg_type = "sticker"
            elif "image/" in mimetype:
                msg_type = "image"
            elif "video/" in mimetype:
                msg_type = "video"
            elif "audio/" in mimetype or "ptt" in raw_type:
                msg_type = "voice"
            elif "application/pdf" in mimetype:
                msg_type = "document"
            else:
                msg_type = "file"

            logger.debug(
                "[WAHA PARSER] Parsed %s message sender_id=%s has_text=%s",
                msg_type, sender_id, bool(msg_body),
            )
            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type=msg_type,
                text=msg_body,
                media=media,
            )

        if msg_body and str(msg_body).strip():
            logger.debug(
                "[WAHA PARSER] Parsed text message sender_id=%s len=%d",
                sender_id, len(str(msg_body)),
            )
            return IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type="text",
                text=msg_body,
            )

        return None

    except Exception:
        # مش بنسجل الـ payload كامل: ممكن يحتوي media base64 ضخم وبيانات عملاء
        logger.exception(
            "Fatal error in parse_waha_message (payload keys: %s)",
            list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )
        return None