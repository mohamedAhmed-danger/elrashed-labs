import logging

from types import SimpleNamespace

from models.models import db, Laboratory, Subscription
from services.messaging.client_service import ClientService
from services.domain.booking_service import BookingService
from services.domain.inquiry_service import InquiryService
from services.domain.tests_service import TestsService
from services.shared.subscription_service import SubscriptionService
from services.domain.tenancy import current_lab_id, is_scoped

logger = logging.getLogger(__name__)


def _safe(label: str, fn, default=0):
    """
    ينفّذ fn ويرجّع نتيجتها. لو فشلت: يسجّل الخطأ ويرجّع default،
    عشان فشل رقم واحد ميوقّعش الداشبورد كلها.
    """
    try:
        return fn()
    except Exception:
        db.session.rollback()  # بدونها أي استعلام بعد الخطأ ممكن يفشل هو كمان
        logger.exception("[DashboardService] %s failed", label)
        return default


class DashboardService:
    def __init__(self, laboratory_id=None):
        self.laboratory_id = laboratory_id

    def _resolve_laboratory_id(self):
        """Lab the numbers are for: the one passed in, or the lab user's own. None = admin overview (all labs)."""
        if self.laboratory_id:
            return self.laboratory_id
        return current_lab_id() if is_scoped() else None

    @staticmethod
    def _build_payload(subscription, status, sub_service=None) -> dict:
        """Shape the subscription numbers the dashboard template expects."""
        limit = subscription.message_limit or 0
        used = subscription.message_used or 0
        return {
            "subscription": subscription,
            "subscription_status": status,
            "usage_percentage": round(used / limit * 100, 1) if limit else 0,
            "remaining_messages": max(limit - used, 0),
        }

    def _get_subscription_data(self, lab_id) -> dict:
        """One lab's subscription (its billing lab's, when the lab shares a subscription)."""
        subscription = SubscriptionService.get_subscription_by_laboratory_id(lab_id)
        if not subscription:
            return {}
        sub_service = SubscriptionService(subscription=subscription)
        return self._build_payload(subscription, sub_service.get_status())

    def _get_aggregate_subscription_data(self) -> dict:
        """
        Admin overview: one combined subscription across all labs.

        Only subscriptions that are actually billed are counted: a lab with
        billing_laboratory_id set draws from another lab's subscription, so
        its own row is idle and would inflate the totals.
        """
        subscriptions = (
            Subscription.query
            .join(Laboratory, Laboratory.id == Subscription.laboratory_id)
            .filter(Laboratory.billing_laboratory_id.is_(None))
            .all()
        )
        if not subscriptions:
            return {}

        statuses = [SubscriptionService(subscription=sub).get_status() for sub in subscriptions]
        problems = [(sub, status) for sub, status in zip(subscriptions, statuses) if status["text"] != "Active"]
        if len(problems) == len(subscriptions):
            # every subscription is stopped / expired / out of messages: the total really is down
            overall = next(
                (
                    status for text in ("Suspended", "Expired", "Limit Reached")
                    for status in statuses if status["text"] == text
                ),
                statuses[0],
            )
        else:
            overall = {"text": "Active", "color": "success"}
        labels = {"Suspended": "متوقف", "Expired": "منتهي", "Limit Reached": "الحد خلص"}
        lab_names = {lab.id: lab.name for lab in Laboratory.query.all()}
        notice = "، ".join(
            f"{lab_names.get(sub.laboratory_id, sub.laboratory_id)}: {labels.get(status['text'], status['text'])}"
            for sub, status in problems
        ) if len(problems) < len(subscriptions) else ""
        starts = [sub.start_date for sub in subscriptions if sub.start_date]
        ends = [sub.end_date for sub in subscriptions if sub.end_date]
        combined = SimpleNamespace(
            plan_name="إجمالي كل المعامل",
            start_date=min(starts) if starts else None,
            end_date=min(ends) if ends else None,  # earliest expiry is the one that needs attention
            message_limit=sum(sub.message_limit or 0 for sub in subscriptions),
            message_used=sum(sub.message_used or 0 for sub in subscriptions),
            grace_limit=sum(sub.grace_limit or 0 for sub in subscriptions),
            is_active=any(sub.is_active for sub in subscriptions),
        )
        payload = self._build_payload(combined, overall)
        payload["subscription_is_aggregate"] = True
        payload["aggregate_notice"] = notice
        return payload

    def get_summary_data(self) -> dict:
        """
        أرقام الداشبورد: حالة الاشتراك والاستهلاك وعدّادات العملاء والحجوزات والاستفسارات والتحاليل.
        كل رقم بيفشل لوحده ويرجع قيمته الافتراضية (0) مع تسجيل الخطأ.
        """
        lab_id = _safe("resolve laboratory", self._resolve_laboratory_id, default=None)
        # A lab user with no lab sees nothing (fail closed): don't fall through to the all-labs overview.
        if lab_id is None and is_scoped():
            return {
                "subscription": None, "subscription_status": None, "usage_percentage": 0, "remaining_messages": 0,
                "clients_count": 0, "booking_stats": {"total": 0},
                "pending_inquiries_count": 0, "tests_count": 0,
            }

        data = {
            "subscription": None,
            "subscription_status": None,
            "usage_percentage": 0,
            "remaining_messages": 0,
            "clients_count": _safe("clients count", ClientService.get_total_clients_count),
            "booking_stats": {"total": _safe("bookings count", BookingService.get_total_bookings_count)},
            "pending_inquiries_count": _safe("pending inquiries count", InquiryService.get_pending_inquiries_count),
            "tests_count": _safe("tests count", TestsService.get_total_tests_count),
        }

        if lab_id:
            data.update(_safe("subscription data", lambda: self._get_subscription_data(lab_id), default={}))
        else:
            data.update(_safe("aggregate subscription data", self._get_aggregate_subscription_data, default={}))

        return data