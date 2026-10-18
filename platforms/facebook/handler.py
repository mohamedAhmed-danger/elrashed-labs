import io
import json
import logging

from config import Config
from notification_center import send_production_alert
from platforms import http_client
from platforms.base_handler import BaseHandler
from platforms.facebook import comments as fb_comments
from platforms.http_client import safe_post

logger = logging.getLogger(__name__)


class FacebookHandler(BaseHandler):
    platform_id = 1
    # النسخة من Config.FB_API_VERSION. الافتراضي هو القديم عشان السلوك ميتغيرش
    # لحد ما تراجع الـ changelog وتحدّد النسخة الجديدة.
    API_VERSION = getattr(Config, "FB_API_VERSION", "v19.0")

    MAX_FB_TEXT_LEN = 2000

    def __init__(self, page):
        super().__init__(page)
        self.base_url = f"https://graph.facebook.com/{self.API_VERSION}"
        # الـ token في الـ header مش في الـ URL، عشان ميظهرش في رسائل الأخطاء واللوجز
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @property
    def platform_name(self) -> str:
        try:
            return self.page.platform.name
        except AttributeError:
            return "Facebook"

    def _post(self, path: str, payload: dict, recipient_id=None, alert: bool = True):
        return safe_post(
            f"{self.base_url}{path}",
            label="Facebook",
            page_id=self.page_id,
            recipient_id=recipient_id,
            alert=alert,
            json=payload,
            headers=self.headers,
        )

    # ── text ─────────────────────────────────────────────────────────────────

    def _split_text(self, text: str, max_len: int = None):
        """يقسم النص لأجزاء كل جزء أقل من أو يساوي الحد الأقصى، من غير ما يقطع كلمة نص نص."""
        max_len = max_len or self.MAX_FB_TEXT_LEN
        text = text.strip()
        if len(text) <= max_len:
            return [text]

        parts = []
        while len(text) > max_len:
            split_at = text.rfind("\n\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1:
                split_at = max_len
            parts.append(text[:split_at].strip())
            text = text[split_at:].strip()
        if text:
            parts.append(text)
        return parts

    def send(self, recipient_id: str, text: str):
        if not text or not text.strip():
            return None

        chunks = self._split_text(text)
        response = None

        for i, chunk in enumerate(chunks, start=1):
            logger.debug("[FB SEND] to=%s part=%d/%d", recipient_id, i, len(chunks))
            response = self._post(
                "/me/messages",
                {
                    "messaging_type": "RESPONSE",
                    "recipient": {"id": recipient_id},
                    "message": {"text": chunk},
                },
                recipient_id,
            )
            if response is None or not response.ok:
                # منكمّلش باقي الأجزاء: العميل يستلم رد مقطّع ومش مترتب
                logger.warning("[FB SEND] Stopped at part %d/%d | to=%s", i, len(chunks), recipient_id)
                break

        return response

    # ── image (ticket) ───────────────────────────────────────────────────────

    def send_image(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str = "ticket.png",
        mime_type: str = "image/png",
    ):
        logger.debug("[FB SEND IMAGE] to=%s file=%s", recipient_id, filename)
        return safe_post(
            f"{self.base_url}/me/messages",
            label="Facebook Image",
            page_id=self.page_id,
            recipient_id=recipient_id,
            headers=self.headers,
            data={
                "messaging_type": "RESPONSE",
                "recipient": json.dumps({"id": recipient_id}),
                "message": json.dumps({
                    "attachment": {"type": "image", "payload": {"is_reusable": False}}
                }),
            },
            files={"filedata": (filename, io.BytesIO(file_bytes), mime_type)},
            timeout=(5, 30),
        )

    # ── typing indicator ─────────────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        logger.debug("[FB TYPING] to=%s", recipient_id)
        # ثانوي: لو فشل مش بنبعت alert (وإلا كل رسالة هتعمل alerts وقت أي عطل)
        return self._post(
            "/me/messages",
            {"recipient": {"id": recipient_id}, "sender_action": "typing_on"},
            recipient_id,
            alert=False,
        )

    # ── comments (delegated to platforms/facebook/comments.py) ───────────────

    def handle_comment(self, comment_id: str, page_id: str):
        fb_comments.handle_comment(comment_id, page_id, self.base_url, self.token)

    def react_to_comment(self, comment_id: str):
        return fb_comments.react_to_comment(comment_id, self.base_url, self.headers)

    def reply_to_comment(self, comment_id: str, static_message: str = "شكراً على تعليقك! راسلنا خاصةً للمساعدة. 🙏"):
        return fb_comments.reply_to_comment(comment_id, self.base_url, self.headers, self.page_id, static_message)

    def send_private_reply(self, page_id, token: str, comment_id: str, text: str):
        return fb_comments.send_private_reply(page_id, token, comment_id, text, self.base_url)

    # ── parsing ──────────────────────────────────────────────────────────────

    def parse_message(self, payload, page_id):
        from platforms.facebook.parser import parse_facebook_message
        return parse_facebook_message(
            payload,
            page_id,
            platform_id=self.platform_id,
            platform_name=self.platform_name,
        )

    # ── media download ───────────────────────────────────────────────────────

    def download_media(self, media: dict, media_type: str = "media") -> bytes | None:
        image_url = media.get("url") if media else None
        if not image_url:
            logger.warning("[FacebookHandler] download_media: no url in media")
            return None
        try:
            response = http_client.session.get(image_url, timeout=(5, 30))
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.exception("[FacebookHandler] download_media failed")
            send_production_alert(
                subject="Facebook Media Download Failure",
                body_or_error=e,
                context={"page_id": self.page_id, "media_type": media_type},
            )
            return None