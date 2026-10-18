import logging
import os

logger = logging.getLogger(__name__)


def resolve_base_url(page_id):
    """Pick the right WAHA container for this page, via env-var mapping."""
    instances = [
        (os.environ.get("WAHA1_PAGE_ID"), os.environ.get("WAHA1_BASE_URL")),
        (os.environ.get("WAHA2_PAGE_ID"), os.environ.get("WAHA2_BASE_URL")),
        (os.environ.get("WAHA3_PAGE_ID"), os.environ.get("WAHA3_BASE_URL")),
        (os.environ.get("WAHA4_PAGE_ID"), os.environ.get("WAHA4_BASE_URL")),
        (os.environ.get("WAHA5_PAGE_ID"), os.environ.get("WAHA5_BASE_URL")),
    ]

    for mapped_page_id, base_url in instances:
        if page_id and mapped_page_id and page_id == mapped_page_id and base_url:
            return base_url.rstrip("/")

    logger.warning(
        "[WAHA] No instance mapping for page_id=%s, falling back to WAHA_API_URL",
        page_id,
    )

    return os.environ.get("WAHA_API_URL", "http://waha:3000").rstrip("/")