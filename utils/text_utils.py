import uuid
from typing import Any

from utils.embedding_utils import build_embedding_text


PLATFORM_MAP = {
    1: "Facebook",
    2: "WhatsApp",
}


def make_reference_id() -> str:
    """Generates a short unique ID like BK-A3F2-91C0."""
    raw = uuid.uuid4().hex.upper()
    return f"BK-{raw[:4]}-{raw[4:8]}"


def get_platform_name(platform_id: Any) -> str:
    """Convert platform_id to platform name string."""
    if not platform_id:
        return "unknown"
    try:
        key = int(platform_id)
        return PLATFORM_MAP.get(key, str(platform_id))
    except ValueError:
        return str(platform_id)


def detect_language_fallback(
    user_message: str, arabic: str, default: str
) -> str:
    """Return `arabic` if the user message contains Arabic characters, otherwise return `default`."""
    if any("\u0600" <= c <= "\u06ff" for c in user_message):
        return arabic
    return default


def build_test_text(name: str, description: str, keywords: list[str]) -> str:
    """Build the text that will be converted into an embedding."""
    return build_embedding_text(name, description, keywords)
