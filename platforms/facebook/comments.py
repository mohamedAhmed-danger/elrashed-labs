import logging

from notification_center import send_production_alert
from platforms.http_client import safe_post

logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_REPLY = "منوّرنا يا فندم 💙 ردينا عليك على الخاص، معمل الصدارة تحت أمرك."
DEFAULT_PRIVATE_REPLY = "أهلاً وسهلاً بحضرتك 💙 معمل الصدارة تحت أمرك، تحب أساعدك في إيه؟"

def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def react_to_comment(comment_id: str, base_url: str, headers: dict):
    """تفاعل (Love) على التعليق. ثانوي: لو فشل بيتسجل بس من غير alert."""
    logger.debug("[FB LOVE COMMENT] comment_id=%s", comment_id)
    return safe_post(
        f"{base_url}/{comment_id}/reactions?type=LOVE",  # التعديل هنا
        label="Facebook Love Reaction",
        alert=False,
        headers=headers,
        timeout=(5, 10),
    )


def reply_to_comment(
    comment_id: str,
    base_url: str,
    headers: dict,
    page_id,
    static_message: str = DEFAULT_PUBLIC_REPLY,
):
    """رد عام على التعليق برسالة ثابتة."""
    logger.debug("[FB COMMENT REPLY] comment_id=%s", comment_id)
    return safe_post(
        f"{base_url}/{comment_id}/comments",
        label="Facebook Comment Reply",
        page_id=page_id,
        json={"message": static_message},
        headers=headers,
    )


def send_private_reply(page_id, page_access_token: str, comment_id: str, text: str, base_url: str) -> dict:
    """رسالة خاصة على التعليق. يرجّع dict فيه status و ok و data."""
    logger.debug("[FB PRIVATE REPLY] comment_id=%s page_id=%s", comment_id, page_id)

    response = safe_post(
        f"{base_url}/{page_id}/messages",
        label="Facebook Private Reply",
        page_id=page_id,
        json={
            "recipient": {"comment_id": comment_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        },
        headers=_auth_headers(page_access_token),
    )
    if response is None:
        return {"status": 500, "ok": False, "data": "connection error"}

    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:500]}
    return {"status": response.status_code, "ok": response.ok, "data": data}


def handle_comment(comment_id: str, page_id: str, base_url: str, token: str):
    """يشغّل خطوات التعليق: لايك + رد عام + رسالة خاصة (كل خطوة مستقلة عن التانية)."""
    headers = _auth_headers(token)
    try:
        react_to_comment(comment_id, base_url, headers)
        reply_to_comment(comment_id, base_url, headers, page_id)
        send_private_reply(page_id, token, comment_id, DEFAULT_PRIVATE_REPLY, base_url)
    except Exception as e:
        logger.exception("[FB HANDLE COMMENT] Unexpected error | comment_id=%s", comment_id)
        send_production_alert(
            subject="Facebook Handle Comment Failure",
            body_or_error=e,
            context={"comment_id": comment_id, "page_id": page_id},
        )