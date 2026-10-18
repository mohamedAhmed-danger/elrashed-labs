import logging

import requests

from notification_center import send_production_alert

logger = logging.getLogger(__name__)

# Shared session (connection pooling) for Facebook Graph API, WAHA, and media downloads
session = requests.Session()

DEFAULT_TIMEOUT = (5, 15)  # (connect, read) seconds
_MAX_BODY_CHARS = 500


def safe_post(url: str, *, label: str, page_id=None, recipient_id=None, alert: bool = True, **request_kwargs):
    """
    POST مع معالجة أخطاء موحدة. يرجّع الـ Response، أو None لو الاتصال فشل.

    - request_kwargs: json / data / files / headers / params / timeout
    - الـ alerts فيها معلومات تشخيصية بس: مفيش payload (فيه نص العميل) ومفيش token
      (الـ tokens بتتبعت في headers مش في الـ URL).
    - alert=False للعمليات الثانوية زي الـ typing indicator.
    """
    request_kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    context = {"platform": label, "url": url, "page_id": page_id, "recipient_id": recipient_id}

    try:
        response = session.post(url, **request_kwargs)
    except Exception as e:
        logger.exception("[%s] Connection failed | url=%s", label, url)
        if alert:
            send_production_alert(
                subject=f"{label} Connection Exception",
                body_or_error=e,
                context=context,
            )
        return None

    if not response.ok:
        body = response.text[:_MAX_BODY_CHARS]
        logger.error("[%s] HTTP %s | url=%s | body=%s", label, response.status_code, url, body)
        if alert:
            send_production_alert(
                subject=f"{label} API HTTP Error",
                body_or_error=f"HTTP {response.status_code}: {body}",
                context=context,
            )
    return response