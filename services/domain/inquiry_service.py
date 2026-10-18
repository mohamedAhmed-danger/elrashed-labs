"""
software_services/inquiry_service.py
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from models.models import Inquiry, Status, db
from services.messaging.client_service import ClientService
from services.domain.page_service import PageService
from services.shared.platform_service import PlatformService
from services.domain.tests_service import TestsService

logger = logging.getLogger(__name__)


# ── result dataclass ──────────────────────────────────────────────────────────

@dataclass
class InquiryResult:
    success: bool
    inquiry: object
    message: str


# ── service ───────────────────────────────────────────────────────────────────

class InquiryService:
    DISCOUNTS = {
        'general':   {'label': 'خصم 30%',     'percent': 30},
        'insurance': {'label': 'خصم التأمين', 'percent': 50}, 
    }

    def __init__(self, inquiry_id=None, inquiry=None):
        """Initialize with an inquiry_id or a pre-loaded Inquiry instance."""
        self.inquiry_id = inquiry_id
        self._inquiry = inquiry
        if inquiry:
            self.inquiry_id = inquiry.id

    @property
    def inquiry(self):
        """Lazily load and cache the Inquiry tied to self.inquiry_id."""
        if self._inquiry is None and self.inquiry_id is not None:
            self._inquiry = db.session.get(Inquiry, self.inquiry_id)
        return self._inquiry

    # ── read ──────────────────────────────────────────────────────────────────

    def get_all_inquiries(self, page=1, per_page=10, search=None, status=None):
        """Fetch paginated inquiries filtered by search and status. Returns (Pagination or None, message)."""
        try:
            query = Inquiry.query

            if search:
                query = query.filter(
                    db.or_(
                        Inquiry.phone_number.ilike(f'%{search}%'),
                        Inquiry.comes_from.ilike(f'%{search}%'),
                        Inquiry.services_mentioned.ilike(f'%{search}%'),
                    )
                )

            if status:
                try:
                    query = query.filter(Inquiry.status == Status(status))
                except ValueError:
                    pass

            query = query.order_by(Inquiry.created_at.desc())
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            return pagination, "تم العثور على الاستفسارات"
        except Exception:
            logger.exception("[InquiryService.get_all_inquiries] Query failed")
            return None, "حدث خطأ أثناء جلب الاستفسارات"

    def get_inquiry(self, inquiry_id=None):
        """
        Fetch an inquiry by ID or instance context. Returns an InquiryResult.

        Resolves target ID from the argument or self.inquiry_id, prefers the
        cached instance when it matches, and syncs the instance cache on a
        successful DB lookup.
        """
        target_id = inquiry_id or self.inquiry_id
        if not target_id and self._inquiry:
            return InquiryResult(True, self._inquiry, "تم العثور على الاستفسار")
        if not target_id:
            return InquiryResult(False, None, "الاستفسار غير موجود")

        if self._inquiry and self._inquiry.id == target_id:
            return InquiryResult(True, self._inquiry, "تم العثور على الاستفسار")

        inquiry = db.session.get(Inquiry, target_id)
        if not inquiry:
            return InquiryResult(False, None, "الاستفسار غير موجود")
        if target_id == self.inquiry_id or self.inquiry_id is None:
            self._inquiry = inquiry
            self.inquiry_id = inquiry.id
        return InquiryResult(True, inquiry, "تم العثور على الاستفسار")

    def get_inquiry_by_id(self, inquiry_id=None):
        """Backward-compatible alias for get_inquiry()."""
        return self.get_inquiry(inquiry_id=inquiry_id)

    def get_pending_count(self):
        """Count inquiries currently in PENDING status."""
        try:
            return Inquiry.query.filter_by(status=Status.PENDING).count()
        except Exception:
            logger.exception("[InquiryService.get_pending_count] Error")
            return 0

    # ── stats ─────────────────────────────────────────────────────────────────

    def get_stats(self):
        """Return counts (total/pending/reviewed) plus average OCR confidence as a 0-100 percentage."""
        try:
            total = Inquiry.query.count()
            pending = Inquiry.query.filter_by(status=Status.PENDING).count()
            reviewed = Inquiry.query.filter_by(status=Status.REVIEWED).count()

            from sqlalchemy import func
            avg_conf = db.session.query(
                func.avg(Inquiry.confidence_score)
            ).filter(Inquiry.confidence_score.isnot(None)).scalar()

            return {
                "total": total,
                "pending": pending,
                "done": reviewed,
                "confirmed": reviewed,
                "avg_conf": round((avg_conf or 0) * 100, 1),
            }
        except Exception:
            logger.exception("[InquiryService.get_stats] Error")
            return {"total": 0, "pending": 0, "done": 0, "confirmed": 0, "avg_conf": 0.0}

    # ── write ─────────────────────────────────────────────────────────────────

    def save_inquiry(
        self,
        laboratory_id: int,
        phone_number: str,
        comes_from: str,
        prescription_img: str = None,
        ocr_extracted_text: str = None,
        confidence_score: float = None,
        services_mentioned: str = None,
        status: Status = Status.PENDING,
    ):
        """Persist a new prescription inquiry with OCR metadata. Returns an InquiryResult."""
        try:
            inquiry = Inquiry(
                laboratory_id=laboratory_id,
                phone_number=phone_number,
                comes_from=comes_from,
                prescription_img=prescription_img,
                ocr_extracted_text=ocr_extracted_text,
                confidence_score=confidence_score,
                services_mentioned=services_mentioned,
                status=status,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(inquiry)
            db.session.commit()
            self._inquiry = inquiry
            self.inquiry_id = inquiry.id
            return InquiryResult(True, inquiry, "تم حفظ الاستفسار بنجاح")
        except Exception:
            db.session.rollback()
            logger.exception("[InquiryService.save_inquiry] Error")
            return InquiryResult(False, None, "حدث خطأ أثناء حفظ الاستفسار")

    def update_status(self, new_status: str, inquiry_id=None):
        """Update an inquiry's status from a status-string. Returns an InquiryResult."""
        target_id = inquiry_id or self.inquiry_id
        inquiry = None
        if self._inquiry and (not target_id or self._inquiry.id == target_id):
            inquiry = self._inquiry
        elif target_id:
            inquiry = db.session.get(Inquiry, target_id)

        if not inquiry:
            return InquiryResult(False, None, "الاستفسار غير موجود")
        try:
            inquiry.status = Status(new_status)
            db.session.commit()
            self._inquiry = inquiry
            self.inquiry_id = inquiry.id
            return InquiryResult(True, inquiry, "تم تحديث الحالة بنجاح")
        except ValueError:
            return InquiryResult(False, None, "حالة غير صحيحة")
        except Exception:
            db.session.rollback()
            logger.exception("[InquiryService.update_status] Error")
            return InquiryResult(False, None, "حدث خطأ أثناء تحديث الحالة")

    def _build_prescription_reply(self, services, discount_type=None):
        """
        Build the doctor's confirmation reply text and a comma-separated
        services list. Computes the total price across all selected services,
        and applies an optional discount (general / insurance).
        """
        message_lines = [
            "📋 تمت مراجعة الروشتة الخاصة بك من قبل الطبيب.",
            "التحاليل المطلوبة:",
            ""
        ]

        total_price = 0.0
        service_names = []

        for s in services:
            service_names.append(s.name)
            total_price += float(s.price or 0)

            message_lines.extend([
                f"▫️ {s.name}",
                f"   • السعر: {s.price} ج.م",
                f"   • العينة: {s.sample_type or 'غير محددة'}",
                f"   • النتيجة خلال: {s.duration or 'غير محددة'}",
                f"   • التعليمات: {s.patient_instructions or 'لا توجد تعليمات'}",
                ""
            ])

        message_lines.append(f"💰 الإجمالي: {total_price:g} ج.م")

        discount = self.DISCOUNTS.get(discount_type)
        if discount:
            discount_amount = round(total_price * discount['percent'] / 100, 2)
            final_price = total_price - discount_amount
            message_lines.append(f"🎁 {discount['label']}: -{discount_amount:g} ج.م")
            message_lines.append(f"✅ الإجمالي بعد الخصم: {final_price:g} ج.م")

        message_lines.append('لتأكيد الحجز، ابعتلي كلمة "تأكيد" وهنكمل معاك خطوات الحجز 👍')

        return "\n".join(message_lines), ", ".join(service_names)

    def _resolve_inquiry_and_services(self, inquiry_id, selected_service_ids):
        """Validate and retrieve the target inquiry and requested lab services."""
        result = self.get_inquiry(inquiry_id)
        if not result.success:
            return None, None, result.message

        selected_services = TestsService.get_services_by_ids(selected_service_ids)
        if not selected_services:
            return None, None, 'الخدمات المحددة غير صالحة.'

        return result.inquiry, selected_services, None

    def _dispatch_to_channel(self, comes_from: str, reply_text: str):
        """
        Persist the reviewed inquiry and chat history first, then attempt the
        actual customer-facing send last.

        This order matters: the customer-facing send cannot be rolled back
        once it happens, so if it ran first and a later DB write failed, the
        customer would already have the doctor's reply while the DB rolled
        back to PENDING — risking a duplicate send on retry and a DB state
        that contradicts reality. By committing first, a DB failure means no
        message was ever sent (safe to retry). The residual risk is the
        opposite case: DB commit succeeds but the send itself fails (e.g.
        network issue) — the inquiry is already REVIEWED and chat history
        already recorded the reply, but the customer never received it, and
        there is currently no automatic retry for that case; it needs a
        manual resend using the stored reply_text.
        """
        try:
            platform, sender_id, page_id = (comes_from or "").split(":", 2)
        except ValueError:
            db.session.commit()
            return True, "تمت المراجعة وحفظ البيانات محلياً (لا يوجد مصدر محدد للمحادثة)."

        try:
            from platforms.facebook.handler import FacebookHandler
            from platforms.waha.handler import WahaHandler
            platform_map = {"facebook": FacebookHandler, "whatsapp": WahaHandler}
        except (ImportError, ModuleNotFoundError) as err:
            logger.warning("[InquiryService._dispatch_to_channel] Could not import platform handlers: %s", err)
            platform_map = {}

        if platform not in platform_map:
            db.session.commit()
            return True, "تمت المراجعة وحفظ البيانات، لكن الإرسال الفعلي للعميل محتاج ربط قنوات التواصل أولاً"

        platform_row = PlatformService.get_platform_by_name(platform)
        if not platform_row:
            db.session.rollback()
            return False, "منصة غير معروفة في قاعدة البيانات."

        page = PageService.get_page_by_page_and_platform(page_id=page_id, platform_id=platform_row.id)
        if not page:
            db.session.rollback()
            return False, "الصفحة المرتبطة بهذا الاستفسار غير موجودة."

        try:
            client_service = ClientService(platform_id=platform_row.id, page_id=page_id, sender_id=sender_id)
            client_service.get_or_create_client()
            client_service.save_chat_exchange(
                user_message="[SYSTEM] الطبيب راجع الروشتة وأكد التحاليل.",
                bot_reply=reply_text,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[InquiryService._dispatch_to_channel] Error saving review before send")
            return False, "حدث خطأ أثناء حفظ المراجعة، لم يتم إرسال أي رسالة للعميل."

        try:
            handler_class = platform_map[platform]
            handler = handler_class(page)
            handler.send(sender_id, reply_text)
            return True, "تم تأكيد الروشتة وإرسالها للمستخدم بنجاح."
        except Exception:
            logger.exception(
                "[InquiryService._dispatch_to_channel] Review saved but send failed (platform=%s, sender_id=%s)",
                platform, sender_id,
            )
            return False, "تم حفظ المراجعة في النظام، لكن حدث خطأ أثناء إرسال الرسالة للعميل فعليًا. برجاء إعادة الإرسال يدويًا."

    def confirm_and_reply(self, selected_service_ids, inquiry_id=None, discount_type=None):
        """
        Confirm doctor-selected services for an inquiry and dispatch the reply via the origin channel.
        discount_type is optional: a key of DISCOUNTS ('general' / 'insurance') or None for no discount.
        """
        target_id = inquiry_id or self.inquiry_id
        inquiry, selected_services, error = self._resolve_inquiry_and_services(target_id, selected_service_ids)
        if error:
            return False, error

        if discount_type not in self.DISCOUNTS:
            discount_type = None

        reply_text, services_mentioned = self._build_prescription_reply(selected_services, discount_type)
        inquiry.services_mentioned = services_mentioned
        inquiry.status = Status.REVIEWED

        return self._dispatch_to_channel(inquiry.comes_from, reply_text)

    @staticmethod
    def get_pending_inquiries_count() -> int:
        """Fetch total count of pending prescription inquiries."""
        try:
            return Inquiry.query.filter(Inquiry.status == Status.PENDING).count()
        except Exception:
            logger.exception("[InquiryService.get_pending_inquiries_count] Error")
            return 0