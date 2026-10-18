import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from models.models import Platform, db

logger = logging.getLogger(__name__)

DUPLICATE_NAME_MSG = "يوجد منصة أخرى بنفس هذا الاسم"
NAME_REQUIRED_MSG = "اسم المنصة مطلوب"


class PlatformService:
    def __init__(self, platform_id=None, platform=None):
        """Wrap a single platform, given its ID or a pre-loaded instance."""
        self.platform_id = platform_id
        self._platform = platform

    @property
    def platform(self):
        """The platform, lazily loaded by ID on first access."""
        if self._platform is None and self.platform_id is not None:
            self._platform = db.session.get(Platform, self.platform_id)
        return self._platform

    def create_platform(self, name):
        """
        Create a platform with a normalized, unique name.

        Returns (platform, message); platform is None on failure.
        """
        try:
            name = (name or "").strip().lower()
            if not name:
                return None, NAME_REQUIRED_MSG

            existing_platform = Platform.query.filter_by(name=name).first()
            if existing_platform:
                return None, DUPLICATE_NAME_MSG

            new_platform = Platform(name=name)
            db.session.add(new_platform)
            db.session.commit()
            self._platform = new_platform
            self.platform_id = new_platform.id
            return new_platform, "تم إنشاء المنصة بنجاح"
        except IntegrityError:
            db.session.rollback()
            return None, DUPLICATE_NAME_MSG
        except Exception:
            db.session.rollback()
            logger.exception("[PlatformService.create_platform] failed")
            return None, "حدث خطأ أثناء إنشاء المنصة"

    def get_platform(self, platform_id=None):
        """
        Get a platform by ID, using this instance's ID and cache as defaults.

        Returns (platform, message); platform is None if not found or on error.
        """
        target_id = platform_id or self.platform_id
        if not target_id and self._platform:
            return self._platform, "تم العثور على المنصة"
        if not target_id:
            return None, "المنصة غير موجودة"

        if self._platform and self._platform.id == target_id:
            return self._platform, "تم العثور على المنصة"

        try:
            platform = db.session.get(Platform, target_id)
        except Exception:
            logger.exception("[PlatformService.get_platform] failed")
            return None, "حدث خطأ أثناء جلب المنصة"

        if not platform:
            return None, "المنصة غير موجودة"

        if target_id == self.platform_id or self.platform_id is None:
            self._platform = platform
            self.platform_id = platform.id

        return platform, "تم العثور على المنصة"

    def update_platform(self, name=None, platform_id=None):
        """
        Rename a platform using the same normalization and uniqueness rules.

        Returns (platform, message); platform is None on failure.
        """
        try:
            target_id = platform_id or self.platform_id
            platform = None

            if self._platform and (not target_id or self._platform.id == target_id):
                platform = self._platform
            elif target_id:
                platform = db.session.get(Platform, target_id)

            if not platform:
                return None, "المنصة غير موجودة"

            if name:
                name = name.strip().lower()
                if not name:
                    return None, NAME_REQUIRED_MSG

                existing_platform = Platform.query.filter_by(name=name).first()
                if existing_platform and existing_platform.id != platform.id:
                    return None, DUPLICATE_NAME_MSG

                platform.name = name

            db.session.commit()
            self._platform = platform
            self.platform_id = platform.id
            return platform, "تم تحديث المنصة بنجاح"

        except IntegrityError:
            db.session.rollback()
            return None, DUPLICATE_NAME_MSG
        except Exception:
            db.session.rollback()
            logger.exception("[PlatformService.update_platform] failed")
            return None, "حدث خطأ أثناء تحديث المنصة"

    def get_all_platforms(self):
        """Get all platforms with their pages eager-loaded."""
        try:
            platforms = Platform.query.options(joinedload(Platform.pages)).all()
            return platforms, "تم العثور على جميع المنصات"
        except Exception:
            logger.exception("[PlatformService.get_all_platforms] failed")
            return [], "حدث خطأ أثناء جلب المنصات"

    @staticmethod
    def get_platform_by_name(name: str):
        """
        Get a platform by exact name or partial name match.

        Returns None when no matching platform is found.
        """
        if not name:
            return None

        name_clean = str(name).strip().lower()
        if not name_clean:
            return None

        try:
            platform = Platform.query.filter_by(name=name_clean).first()
            if platform:
                return platform

            return Platform.query.filter(
                Platform.name.ilike(f"%{name_clean}%")
            ).first()
        except Exception:
            logger.exception("[PlatformService.get_platform_by_name] failed")
            return None

    @staticmethod
    def get_all_platforms_list():
        """Return all platforms as a list (empty list on error)."""
        try:
            return Platform.query.all()
        except Exception:
            logger.exception("[PlatformService.get_all_platforms_list] failed")
            return []