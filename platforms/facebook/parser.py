import logging

from schemas.incoming_message import IncomingMessage

logger = logging.getLogger(__name__)


def parse_facebook_message(
    messaging,
    page_id,
    platform_id,
    platform_name: str = "Facebook",
) -> list[IncomingMessage]:
    try:
        if "delivery" in messaging or "read" in messaging:
            logger.debug("[FB PARSER] Ignoring delivery/read receipt")
            return []

        if "message" not in messaging:
            logger.debug("[FB PARSER] No 'message' key in event")
            return []

        msg = messaging["message"]

        if msg.get("is_echo", False):
            logger.debug("[FB PARSER] Ignoring echo message")
            return []

        sender_id = messaging.get("sender", {}).get("id")
        if not sender_id:
            logger.debug("[FB PARSER] Missing sender.id in event")
            return []

        # استخراج النص العام للرسالة (إن وجد) ومعرف الستيكر من الرسالة نفسها
        text = msg.get("text", "")
        msg_sticker_id = msg.get("sticker_id")

        # معالجة الرسائل النصية الخالصة (بدون مرفقات)
        if text and not msg.get("attachments") and not msg_sticker_id:
            logger.debug(
                "[FB PARSER] Parsed text message sender_id=%s len=%d",
                sender_id, len(text),
            )
            return [IncomingMessage(
                sender_id=sender_id,
                page_id=page_id,
                platform_id=platform_id,
                platform_name=platform_name,
                msg_type="text",
                text=text,
            )]

        attachments = msg.get("attachments")
        if attachments or msg_sticker_id:
            parsed_list = []
            
            # إذا لم يكن هناك مرفقات ولكن يوجد sticker_id (حالة نادرة في بعض إصدارات API)
            attachments_to_process = attachments if attachments else [{"type": "sticker", "payload": {"sticker_id": msg_sticker_id}}]

            for att in attachments_to_process:
                att_type = att.get("type", "media")
                payload = att.get("payload", {})

                # فحص إذا كان المرفق عبارة عن لايك (إبهام أزرق) أو ستيكر
                is_sticker = (
                    bool(msg_sticker_id)
                    or att_type == "sticker"
                    or (isinstance(payload, dict) and bool(payload.get("sticker_id")))
                )

                if is_sticker:
                    # تحويله فوراً لرسالة نصية حتى لا يدخل على الـ OCR
                    parsed_list.append(
                        IncomingMessage(
                            sender_id=sender_id,
                            page_id=page_id,
                            platform_id=platform_id,
                            platform_name=platform_name,
                            msg_type="text",
                            # إذا كان النص فارغاً، نرسل تعبير يدل على الإعجاب لتفادي رسائل فارغة
                            text=text if text else "👍", 
                        )
                    )
                    continue

                # المرفقات العادية (صور روشتات، ملفات، إلخ) التي ستذهب للـ OCR
                parsed_list.append(
                    IncomingMessage(
                        sender_id=sender_id,
                        page_id=page_id,
                        platform_id=platform_id,
                        platform_name=platform_name,
                        msg_type=att_type,
                        media=payload,
                    )
                )

            logger.debug(
                "[FB PARSER] Parsed %d attachment(s)/sticker(s) sender_id=%s",
                len(parsed_list), sender_id,
            )
            return parsed_list

        return []

    except Exception:
        logger.exception("Fatal error in parse_facebook_message")
        return []


def parse_facebook_comment(change: dict) -> dict | None:
    try:
        if change.get("field") != "feed":
            return None

        value = change.get("value", {})

        if value.get("item") != "comment" or value.get("verb") != "add":
            return None

        if value.get("parent_id") and value.get("parent_id") != value.get("post_id"):
            return None

        comment_id = value.get("comment_id")
        if not comment_id:
            return None

        post_id = value.get("post_id")
        page_id = post_id.split("_")[0] if post_id else None

        return {
            "comment_id": comment_id,
            "page_id": page_id,
        }

    except Exception:
        logger.exception("Fatal error in parse_facebook_comment")
        return None