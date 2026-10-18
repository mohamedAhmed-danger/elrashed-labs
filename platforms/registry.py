from platforms.facebook.handler import FacebookHandler
from platforms.waha.handler import WahaHandler

PLATFORM_HANDLERS = {handler.platform_id: handler for handler in (FacebookHandler, WahaHandler)}


def get_handler(platform_id, page):
    """يرجع الـ handler المناسب حسب platform_id، بدل ما نكرر if/else في كل مكان."""
    handler_cls = PLATFORM_HANDLERS.get(platform_id)
    if not handler_cls:
        raise ValueError(f"Unsupported platform_id: {platform_id}")
    return handler_cls(page)