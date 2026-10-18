import logging
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from models.models import Page, Platform, db

logger = logging.getLogger(__name__)


class PageService:
    def __init__(self, platform_id=None, page_id=None, page=None):
        """
        Wrap a page by (platform_id, page_id) or by a pre-loaded Page instance.

        A page is identified by (platform_id, page_id); page_id is the external ID
        and is always handled as a stripped str. Methods returning a tuple use
        (result, message); result is None on failure.
        """
        self.platform_id = platform_id
        self.page_id = str(page_id).strip() if page_id is not None else None
        self._page = page
        if page:
            self.platform_id = page.platform_id
            self.page_id = page.page_id

    @property
    def page(self):
        """The page for this instance's (platform_id, page_id), lazily loaded."""
        if self._page is None and self.platform_id is not None and self.page_id is not None:
            self._page = Page.query.filter_by(platform_id=self.platform_id, page_id=self.page_id).first()
        return self._page

    def get_all_platforms(self):
        """List all platforms. Returns (platforms, message); empty list on error."""
        try:
            from services.shared.platform_service import PlatformService
            platforms = PlatformService.get_all_platforms_list()
            return platforms, "تم العثور على المنصات"
        except Exception:
            logger.exception("[PageService.get_all_platforms] failed")
            return [], "حدث خطأ أثناء جلب المنصات"

    def get_all_pages(self):
        """List all pages with their platform and clients loaded. Returns (pages, message)."""
        try:
            pages = Page.query.options(joinedload(Page.platform), selectinload(Page.clients)).all()
            return pages, "تم العثور على الصفحات"
        except Exception:
            logger.exception("[PageService.get_all_pages] failed")
            return [], "حدث خطأ أثناء جلب الصفحات"

    def get_page(self, platform_id=None, page_id=None):
        """
        Get a page by (platform_id, page_id), defaulting to this instance's values.

        Returns (page, message); page is None if not found or on error.
        """
        resolved_platform_id = platform_id or self.platform_id
        resolved_page_id = str(page_id).strip() if page_id is not None else self.page_id

        if not resolved_platform_id or not resolved_page_id:
            if self._page:
                return self._page, "تم العثور على الصفحة"
            return None, "الصفحة غير موجودة"

        if self._page and self._page.platform_id == resolved_platform_id and self._page.page_id == resolved_page_id:
            return self._page, "تم العثور على الصفحة"

        try:
            page = Page.query.filter_by(platform_id=resolved_platform_id, page_id=resolved_page_id).first()
            if not page:
                return None, "الصفحة غير موجودة"
            if (resolved_platform_id == self.platform_id and resolved_page_id == self.page_id) or self._page is None:
                self._page = page
                self.platform_id = page.platform_id
                self.page_id = page.page_id
            return page, "تم العثور على الصفحة"
        except Exception:
            logger.exception("[PageService.get_page] failed")
            return None, "حدث خطأ أثناء جلب الصفحة"

    def create_page(self, laboratory_id, platform_id=None, page_id=None, token=None):
        """
        Create a page under a laboratory; (platform_id, page_id) must be unique.

        Returns (page, message); page is None on failure.
        """
        resolved_platform_id = platform_id or self.platform_id
        resolved_page_id = str(page_id).strip() if page_id is not None else self.page_id
        if not resolved_platform_id or not resolved_page_id:
            return None, "بيانات الصفحة غير مكتملة"

        try:
            existing = Page.query.filter_by(platform_id=resolved_platform_id, page_id=resolved_page_id).first()
            if existing:
                return None, "هذه الصفحة مضافة بالفعل لهذه المنصة"

            new_page = Page(
                laboratory_id=laboratory_id,
                platform_id=resolved_platform_id,
                page_id=resolved_page_id,
                token=token.strip() if token else "",
            )
            db.session.add(new_page)
            db.session.commit()
            self._page = new_page
            self.platform_id = new_page.platform_id
            self.page_id = new_page.page_id
            return new_page, "تم إضافة الصفحة بنجاح"
        except IntegrityError:
            db.session.rollback()
            return None, "هذه الصفحة مضافة بالفعل لهذه المنصة"
        except Exception:
            db.session.rollback()
            logger.exception("[PageService.create_page] failed")
            return None, "حدث خطأ أثناء إضافة الصفحة"

    def update_page_token(self, token=None, platform_id=None, page_id=None):
        """
        Set the access token of a page, defaulting to this instance's page.

        Arguments are (token, platform_id, page_id). Returns (page, message).
        """
        resolved_platform_id = platform_id or self.platform_id
        resolved_page_id = str(page_id).strip() if page_id is not None else self.page_id

        page = None
        if self._page and (not resolved_platform_id or self._page.platform_id == resolved_platform_id) and (not resolved_page_id or self._page.page_id == resolved_page_id):
            page = self._page
        elif resolved_platform_id and resolved_page_id:
            page = Page.query.filter_by(platform_id=resolved_platform_id, page_id=resolved_page_id).first()

        if not page:
            return None, "الصفحة غير موجودة"
        try:
            page.token = token.strip() if token else ""
            db.session.commit()
            self._page = page
            self.platform_id = page.platform_id
            self.page_id = page.page_id
            return page, "تم تحديث الرمز بنجاح"
        except Exception:
            db.session.rollback()
            logger.exception("[PageService.update_page_token] failed")
            return None, "حدث خطأ أثناء التحديث"

    def delete_page(self, platform_id=None, page_id=None):
        """
        Delete a page and, through the model's cascade, all of its clients.

        Both identifiers are required (from the arguments or this instance).
        Returns (deleted page, message).
        """
        resolved_platform_id = platform_id or self.platform_id
        resolved_page_id = str(page_id).strip() if page_id is not None else self.page_id
        if not resolved_platform_id or not resolved_page_id:
            return None, "الصفحة غير موجودة"

        if self._page and self._page.platform_id == resolved_platform_id and self._page.page_id == resolved_page_id:
            page = self._page
        else:
            page = Page.query.filter_by(platform_id=resolved_platform_id, page_id=resolved_page_id).first()

        if not page:
            return None, "الصفحة غير موجودة"
        try:
            db.session.delete(page)
            db.session.commit()
            self._page = None
            return page, "تم حذف الصفحة بنجاح"
        except Exception:
            db.session.rollback()
            logger.exception("[PageService.delete_page] failed")
            return None, "حدث خطأ أثناء الحذف"

    @staticmethod
    def get_page_by_page_and_platform(page_id: str | int, platform_id: int):
        """Look up a page by external page_id and platform_id, or None."""
        if page_id is None or platform_id is None:
            return None
        try:
            return Page.query.filter_by(
                page_id=str(page_id).strip(),
                platform_id=int(platform_id),
            ).first()
        except Exception:
            logger.exception("[PageService.get_page_by_page_and_platform] failed")
            return None