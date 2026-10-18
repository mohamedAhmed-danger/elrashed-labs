import logging

from schemas.prepare_result import PrepareResult
from services.messaging.prescription_intake import extract_prescription_payload
from services.shared.subscription_consumer import consume_subscription

logger = logging.getLogger(__name__)


class BaseHandler:
    """المنطق المشترك بين المنصات. كل منصة (فيسبوك، WAHA) بترث منه وتنفّذ الإرسال والتنزيل."""

    platform_id = None

    def __init__(self, page):
        self.page = page
        self.page_id = page.page_id
        self.token = page.token

    def prepare(self, message) -> PrepareResult:
        """
        بتجهز الرسالة، من غير ما تستدعي الـ agent أو تبعت رد.
        بترجع PrepareResult(mode, text, extra):

        - PrepareResult("agent_text", text, ocr_usage)
          → لازم يتحط في الـ debounce buffer

        - PrepareResult("immediate", reply, pdf)
          → لازم يتبعت فورًا للمستخدم
        """
        logger.debug(
            "[PREPARE] type=%s sender_id=%s has_text=%s has_media=%s",
            message.type, message.sender_id, bool(message.text), bool(message.media),
        )

        if message.type == "text":
            consume_subscription(message, count=1)
            return PrepareResult("agent_text", message.text, None)

        if message.type == "image":
            image_bytes = self.download_media(message.media, media_type="image")
            if not image_bytes:
                logger.warning("[PREPARE] Image download failed for user=%s", message.sender_id)
                return PrepareResult("immediate", "عذرًا، فشل تحميل الصورة المرفقة. يرجى المحاولة مرة أخرى.", None)

            result = extract_prescription_payload(image_bytes, message, self.page)
            if result["mode"] == "agent":
                return PrepareResult("agent_text", result["text"], result["ocr_usage"],result.get("image_result"))
            return PrepareResult("immediate", result["reply"], result.get("pdf"))

        logger.info("[PREPARE] Unsupported message type=%s -> immediate response", message.type)
        return PrepareResult("immediate", self._handle_media(message.type), None)

    def _handle_media(self, msg_type: str) -> str:
        responses = {
            "video":    "عذرًا، نقبل الرسائل النصية والصور فقط 📸\nيرجى كتابة استفسارك أو إرسال صورة.",
            "audio":    "عذرًا، نقبل الرسائل النصية والصور فقط 📸\nيرجى كتابة استفسارك أو إرسال صورة.",
            "voice":    "عذرًا، نقبل الرسائل النصية والصور فقط 📸\nيرجى كتابة استفسارك أو إرسال صورة.",
            "document": "عذرًا، نقبل الرسائل النصية والصور فقط 📸\nيرجى كتابة استفسارك أو إرسال صورة.",
            "location": "📍 تم استلام الموقع بنجاح.", # لو اللوكيشن شغال معاك، سيبه زي ما هو
        }
        return responses.get(msg_type, "عذرًا، نقبل الرسائل النصية والصور فقط 📸")

    # ── abstract interface: كل هاندلر لازم يعمل override ────────────────────────

    def download_media(self, media: dict, media_type: str = "media") -> bytes | None:
        raise NotImplementedError

    def send(self, recipient_id: str, text: str):
        raise NotImplementedError

    def send_typing(self, recipient_id: str):
        raise NotImplementedError

    def send_image(self, recipient_id: str, file_bytes: bytes, filename: str, mime_type: str):
        raise NotImplementedError

    def send_file(self, recipient_id: str, file_bytes: bytes, filename: str, mime_type: str):
        raise NotImplementedError

    def parse_message(self, payload, page_id):
        raise NotImplementedError

    # ── comment-related interface (Facebook only, WAHA can ignore) ────────────

    def reply_to_comment(self, comment_id: str, static_message: str):
        raise NotImplementedError

    def react_to_comment(self, comment_id: str):
        raise NotImplementedError

    def send_private_reply(self, page_id, token: str, comment_id: str, text: str):
        raise NotImplementedError

    def handle_comment(self, comment_id: str, page_id: str):
        raise NotImplementedError