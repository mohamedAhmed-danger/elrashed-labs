import logging
from sqlalchemy.exc import IntegrityError
from models.models import Bundle, db
from config import Config
logger = logging.getLogger(__name__)

MAX_BUNDLES = Config.MAX_BUNDLES

DUPLICATE_BUNDLE_MSG = "يوجد باقة أخرى بنفس هذا الاسم"
BUNDLE_REQUIRED_MSG = "اسم الباقة مطلوب"
BUNDLE_LIMIT_REACHED_MSG = f"عذراً، الحد الأقصى للباقات هو {MAX_BUNDLES} باقات فقط"
INVALID_PRICE_MSG = "سعر الباقة غير صحيح"

class BundleService:
    def __init__(self, bundle_id=None, bundle=None):
        """Wrap a single bundle, given its ID or a pre-loaded instance."""
        self.bundle_id = bundle_id
        self._bundle = bundle
        if bundle:
            self.bundle_id = bundle.id

    @property
    def bundle(self):
        """The bundle, lazily loaded by ID on first access."""
        if self._bundle is None and self.bundle_id is not None:
            self._bundle = db.session.get(Bundle, self.bundle_id)
        return self._bundle

    @staticmethod
    def _clean_text(value):
        """Strip a text field; empty input becomes an empty string."""
        return (value or "").strip()

    def create_bundle(self, name, price, description=None, instructions=None):
        try:
            name = self._clean_text(name)
            if not name:
                return None, BUNDLE_REQUIRED_MSG

            try:
                price_val = float(price) if price not in (None, "") else None
            except (ValueError, TypeError):
                return None, "سعر الباقة يجب أن يكون رقماً صحيحاً"

            if price_val is None or price_val < 0:
                return None, INVALID_PRICE_MSG
            
            if Bundle.query.count() >= MAX_BUNDLES:
                return None, BUNDLE_LIMIT_REACHED_MSG

            if Bundle.query.filter_by(name=name).first():
                return None, DUPLICATE_BUNDLE_MSG

            new_bundle = Bundle(
                name=name,
                price=price_val,
                description=self._clean_text(description),
                instructions=self._clean_text(instructions),
            )
            db.session.add(new_bundle)
            db.session.commit()

            self._bundle = new_bundle
            self.bundle_id = new_bundle.id
            return new_bundle, "تم إنشاء الباقة بنجاح"
        except IntegrityError:
            db.session.rollback()
            return None, DUPLICATE_BUNDLE_MSG
        except Exception:
            db.session.rollback()
            logger.exception("[BundleService.create_bundle] failed")
            return None, "حدث خطأ أثناء إنشاء الباقة"

    def get_bundle(self, bundle_id=None):
        """Get a bundle by ID. Returns (bundle, message)."""
        target_id = bundle_id or self.bundle_id
        if not target_id and self._bundle:
            return self._bundle, "تم العثور على الباقة"
        if not target_id:
            return None, "الباقة غير موجودة"

        if self._bundle and self._bundle.id == target_id:
            return self._bundle, "تم العثور على الباقة"

        try:
            bundle = db.session.get(Bundle, target_id)
            if not bundle:
                return None, "الباقة غير موجودة"

            if target_id == self.bundle_id or self.bundle_id is None:
                self._bundle = bundle
                self.bundle_id = bundle.id
            return bundle, "تم العثور على الباقة"
        except Exception:
            logger.exception("[BundleService.get_bundle] failed")
            return None, "حدث خطأ أثناء جلب الباقة"

    def update_bundle(self, name=None, price=None, description=None,
                      instructions=None, bundle_id=None):
        """Update a bundle. Fields left as None are not changed."""
        try:
            target_id = bundle_id or self.bundle_id
            if not target_id:
                return None, "الباقة غير موجودة"

            bundle = db.session.get(Bundle, target_id)
            if not bundle:
                return None, "الباقة غير موجودة"

            if name is not None:
                new_name = self._clean_text(name)
                if not new_name:
                    return None, BUNDLE_REQUIRED_MSG
                duplicate = Bundle.query.filter(
                    Bundle.name == new_name, Bundle.id != bundle.id
                ).first()
                if duplicate:
                    return None, DUPLICATE_BUNDLE_MSG
                bundle.name = new_name

            if price is not None and price != "":
                try:
                    price_val = float(price)
                except (ValueError, TypeError):
                    return None, "سعر الباقة يجب أن يكون رقماً صحيحاً"
                if price_val < 0:
                    return None, INVALID_PRICE_MSG
                bundle.price = price_val

            if description is not None:
                bundle.description = self._clean_text(description)

            if instructions is not None:
                bundle.instructions = self._clean_text(instructions)

            db.session.commit()
            self._bundle = bundle
            self.bundle_id = bundle.id
            return bundle, "تم تحديث الباقة بنجاح"
        except IntegrityError:
            db.session.rollback()
            return None, DUPLICATE_BUNDLE_MSG
        except Exception:
            db.session.rollback()
            logger.exception("[BundleService.update_bundle] failed")
            return None, "حدث خطأ أثناء تحديث الباقة"

    def delete_bundle(self, bundle_id=None):
        """Delete a bundle. Returns (deleted_bundle, message)."""
        target_id = bundle_id or self.bundle_id
        if not target_id:
            return None, "الباقة غير موجودة"

        try:
            bundle = db.session.get(Bundle, target_id)
            if not bundle:
                return None, "الباقة غير موجودة"

            db.session.delete(bundle)
            db.session.commit()
            self._bundle = None
            return bundle, "تم حذف الباقة بنجاح"
        except Exception:
            db.session.rollback()
            logger.exception("[BundleService.delete_bundle] failed")
            return None, "حدث خطأ أثناء حذف الباقة"

    @staticmethod
    def get_all_bundles():
        """Return all bundles ordered by ID."""
        try:
            return Bundle.query.order_by(Bundle.id.asc()).all()
        except Exception:
            logger.exception("[BundleService.get_all_bundles] failed")
            return []
    @staticmethod
    def can_add_bundle():
        """True while the bundle count is below MAX_BUNDLES."""
        return Bundle.query.count() < MAX_BUNDLES
    @staticmethod
    def get_bundles_formatted_context():
        """Bundles as text for the LLM prompt (includes patient instructions)."""
        try:
            bundles = Bundle.query.order_by(Bundle.id.asc()).all()
            if not bundles:
                return "لا توجد باقات فحصية مضافة حالياً."

            lines = []
            for b in bundles:
                desc = f" | التفاصيل: {b.description}" if b.description else ""
                instr = f" | التعليمات: {b.instructions}" if b.instructions else ""
                lines.append(f"• {b.name} - السعر: {b.price:g} جنيه{desc}{instr}")

            return "\n".join(lines)
        except Exception:
            logger.exception("[BundleService.get_bundles_formatted_context] failed")
            return "تعذر جلب معلومات الباقات."