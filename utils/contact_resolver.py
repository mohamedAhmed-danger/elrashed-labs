import os
import logging
import requests

from config import Config
from models.models import db, Page, Platform

logger = logging.getLogger(__name__)

GRAPH_URL = f"https://graph.facebook.com/{getattr(Config, 'FB_API_VERSION', 'v19.0')}"
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")


def _get_waha_base_url(page_id=None) -> str:
    """Resolve the base URL for WAHA using instance_resolver or environment fallbacks."""
    if page_id:
        try:
            from platforms.waha.instance_resolver import resolve_base_url
            url = resolve_base_url(page_id)
            if url:
                return url.rstrip("/")
        except Exception:
            pass

    return (
        os.getenv("WAHA_URL")
        or os.getenv("WAHA_API_URL")
        or os.getenv("WAHA1_BASE_URL")
        or "http://waha1:3000"
    ).rstrip("/")


def _platform_name(platform_id) -> str:
    """Safely return lowercase platform name from fast ID check or DB lookup."""
    if not platform_id:
        return ""
    try:
        pid = int(platform_id)
        if pid == 2:
            return "whatsapp"
        if pid == 1:
            return "facebook"
        platform = db.session.get(Platform, pid)
        return (platform.name if platform else "").lower()
    except Exception:
        return ""


def _waha_phone(session, sender_id, page_id=None):
    """
    Extracts phone number from WhatsApp sender_id.
    - If sender_id ends with @c.us or @s.whatsapp.net, returns the phone directly.
    - If sender_id ends with @lid, calls WAHA API /api/{session}/lids/{sender_id} to resolve to phone number.
    """
    if not sender_id:
        return None

    clean_sender = str(sender_id).strip()

    # 1. Standard WhatsApp user JID: 201208140337@c.us -> 201208140337
    if clean_sender.endswith("@c.us") or clean_sender.endswith("@s.whatsapp.net"):
        return clean_sender.split("@")[0]

    # 2. Pure digits phone number
    if clean_sender.isdigit():
        return clean_sender

    # 3. WhatsApp LID (Linked ID): resolve via WAHA API
    if clean_sender.endswith("@lid"):
        waha_url = _get_waha_base_url(page_id or session)
        # In WAHA, session name is 'default' unless explicitly named; page_id is a phone number JID
        session_name = "default" if (not session or "@" in str(session)) else str(session)
        api_key = os.getenv("WAHA_API_KEY", "") or WAHA_API_KEY
        headers = {"X-Api-Key": api_key} if api_key else {}

        try:
            r = requests.get(
                f"{waha_url}/api/{session_name}/lids/{clean_sender}",
                headers=headers,
                timeout=4,
            )
            status_code = getattr(r, "status_code", 200)
            if not isinstance(status_code, int) or status_code == 200:
                data = r.json() or {}
                pn = data.get("pn") or ""
                if pn:
                    return pn.split("@")[0]
            else:
                logger.warning(
                    "[WAHA LID LOOKUP] Status %s for lid %s: %s",
                    status_code, clean_sender, getattr(r, "text", "")[:200]
                )
        except Exception as e:
            logger.warning("[WAHA LID LOOKUP] Error calling WAHA API for lid %s: %s", clean_sender, e)

    return clean_sender.split("@")[0] if "@" in clean_sender else clean_sender


def _facebook_name(page_id, platform_id, sender_id):
    """Query Facebook Graph API for the user's name given a Page-Scoped ID (PSID)."""
    if not page_id or not sender_id:
        return None
    try:
        pid = int(platform_id) if platform_id else 1
    except (ValueError, TypeError):
        pid = 1

    page = db.session.get(Page, (str(page_id), pid))
    if not page or not page.token:
        logger.warning("[FB PROFILE] Page record or token not found for page_id=%s platform=%s", page_id, pid)
        return None

    try:
        r = requests.get(
            f"{GRAPH_URL}/{sender_id}",
            params={"fields": "name", "access_token": page.token},
            timeout=5,
        )
        status_code = getattr(r, "status_code", 200)
        if not isinstance(status_code, int) or status_code == 200:
            data = r.json() or {}
            name = data.get("name")
            if name:
                return name
        else:
            err_data = (r.json() or {}).get("error", {}) if hasattr(r, "json") else {}
            logger.warning(
                "[FB PROFILE] Graph API failed for sender=%s | code=%s subcode=%s message=%s",
                sender_id,
                err_data.get("code"),
                err_data.get("error_subcode"),
                err_data.get("message"),
            )
            return None
    except Exception as e:
        # do not log the request URL: it contains the access token
        logger.warning("[FB PROFILE] Graph API name lookup failed for sender %s: %s", sender_id, e)
        return None


def resolve_user_phone(page_id, platform_id, sender_id) -> str | None:
    """
    Returns phone number if sender is on WhatsApp.
    Returns None for Facebook (PSID is not a phone number).
    """
    if not sender_id:
        return None
    plat = _platform_name(platform_id)
    if "whatsapp" in plat:
        return _waha_phone(page_id, sender_id, page_id=page_id)
    return None


def resolve_user_name(page_id, platform_id, sender_id) -> str | None:
    """
    Returns user's name from Facebook Graph API if sender is on Facebook.
    Returns None for WhatsApp (unless named in profile).
    """
    if not sender_id:
        return None
    plat = _platform_name(platform_id)
    if "facebook" in plat:
        return _facebook_name(page_id, platform_id, sender_id)
    return None


def resolve_user_identity(page_id, platform_id, sender_id, fallback_name: str | None = None) -> str:
    """
    WhatsApp -> phone (WAHA API or JID parsing).
    Facebook -> name (Meta Graph API).
    Never empty: returns resolved identity, fallback_name (if provided), or sender_id.
    """
    if not sender_id:
        return fallback_name or ""

    identity = None
    try:
        plat = _platform_name(platform_id)
        if "whatsapp" in plat:
            identity = _waha_phone(page_id, sender_id, page_id=page_id)
        else:
            identity = _facebook_name(page_id, platform_id, sender_id)
    except Exception:
        logger.exception("resolve_user_identity failed for sender %s", sender_id)
        identity = None

    if identity:
        return identity

    if fallback_name and fallback_name.strip():
        return fallback_name.strip()

    return str(sender_id)


def resolve_phone_for_state(state) -> str | None:
    """Resolve phone for state (returns WhatsApp phone or None)."""
    return resolve_user_phone(
        state.get("page_id"),
        state.get("platform_id"),
        state.get("sender_id"),
    )


def resolve_name_for_state(state) -> str | None:
    """Resolve user profile name for state (returns Facebook profile name or None)."""
    return resolve_user_name(
        state.get("page_id"),
        state.get("platform_id"),
        state.get("sender_id"),
    )


def resolve_identity_for_state(state, fallback_name: str | None = None) -> str:
    """Resolve general user identity (Phone on WhatsApp, Name on Facebook)."""
    return resolve_user_identity(
        state.get("page_id"),
        state.get("platform_id"),
        state.get("sender_id"),
        fallback_name=fallback_name,
    )