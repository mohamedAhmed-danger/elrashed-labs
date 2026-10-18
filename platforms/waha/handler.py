import base64
import logging
import os
from urllib.parse import urlparse

from notification_center import send_production_alert
from platforms import http_client
from platforms.base_handler import BaseHandler
from platforms.http_client import safe_post
from platforms.waha.instance_resolver import resolve_base_url

logger = logging.getLogger(__name__)


class WahaHandler(BaseHandler):
    platform_id = 2

    def __init__(self, page):
        super().__init__(page)
        self.base_url = resolve_base_url(getattr(page, "page_id", None))
        self.session = "default"  # اسم الـ session في WAHA
        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": os.environ.get("WAHA_API_KEY", ""),
        }

    @property
    def platform_name(self) -> str:
        try:
            return self.page.platform.name
        except AttributeError:
            return "WhatsApp"

    def _post(self, endpoint: str, payload: dict, alert: bool = True):
        return safe_post(
            f"{self.base_url}{endpoint}",
            label="WAHA",
            page_id=self.page_id,
            recipient_id=payload.get("chatId"),
            alert=alert,
            json=payload,
            headers=self.headers,
        )

    def _send_media(self, endpoint: str, recipient_id: str, file_bytes: bytes, filename: str, mime_type: str):
        return self._post(endpoint, {
            "session": self.session,
            "chatId": recipient_id,
            "file": {
                "mimetype": mime_type,
                "filename": filename,
                "data": base64.b64encode(file_bytes).decode("utf-8"),
            },
        })

    # ── text ─────────────────────────────────────────────────────────────────

    def send(self, recipient_id: str, text: str):
        if not text or not text.strip():
            return None
        logger.debug("[WAHA SEND] to=%s", recipient_id)
        return self._post("/api/sendText", {
            "session": self.session,
            "chatId": recipient_id,
            "text": str(text),
        })

    # ── image / file ─────────────────────────────────────────────────────────

    def send_image(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str = "ticket.png",
        mime_type: str = "image/png",
    ):
        logger.debug("[WAHA SEND IMAGE] to=%s file=%s", recipient_id, filename)
        return self._send_media("/api/sendImage", recipient_id, file_bytes, filename, mime_type)

    def send_file(
        self,
        recipient_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str = "application/pdf",
    ):
        logger.debug("[WAHA SEND FILE] to=%s file=%s", recipient_id, filename)
        return self._send_media("/api/sendFile", recipient_id, file_bytes, filename, mime_type)

    # ── typing indicator ─────────────────────────────────────────────────────

    def send_typing(self, recipient_id: str):
        logger.debug("[WAHA TYPING] to=%s", recipient_id)
        # ثانوي: لو فشل مش بنبعت alert
        return self._post(
            "/api/startTyping",
            {"session": self.session, "chatId": recipient_id},
            alert=False,
        )

    # ── media download ───────────────────────────────────────────────────────

    def _is_own_host(self, url: str) -> bool:
        """هل الرابط على نفس سيرفر WAHA بتاعنا؟ (عشان منبعتش الـ API key لسيرفر غريب)."""
        return urlparse(url).netloc == urlparse(self.base_url).netloc

    def download_media(self, media: dict, media_type: str = "media"):
        try:
            if not media:
                return None

            if media.get("data"):
                return base64.b64decode(media["data"])

            url = media.get("url")
            if not url:
                return None

            headers = None
            if self._is_own_host(url):
                headers = self.headers
            else:
                # الرابط جاي من الـ payload: مبنبعتش معاه الـ API key
                logger.warning("[WAHA DOWNLOAD] Media host differs from base_url, sending without API key")

            timeout = (5, 30) if media_type in ("pdf", "voice") else (5, 15)
            response = http_client.session.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.content

        except Exception as e:
            logger.exception("[WAHA %s DOWNLOAD ERROR]", media_type.upper())
            send_production_alert(
                subject=f"WAHA Media Download Error ({media_type})",
                body_or_error=e,
                context={"page_id": self.page_id, "media_type": media_type},
            )
            return None

    # ── parsing ──────────────────────────────────────────────────────────────

    def parse_message(self, payload, page_id):
        from platforms.waha.parser import parse_waha_message
        return parse_waha_message(
            payload,
            page_id,
            platform_id=self.platform_id,
            platform_name=self.platform_name,
        )