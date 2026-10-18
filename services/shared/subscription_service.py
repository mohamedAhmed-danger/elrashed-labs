import logging
from datetime import datetime, timedelta, timezone

from models.models import Subscription, db


logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self, laboratory_id=None, subscription=None):
        """Initialize with a laboratory_id or a pre-loaded Subscription instance."""
        self.laboratory_id = laboratory_id
        self._subscription = subscription
        if subscription and getattr(subscription, "laboratory_id", None):
            self.laboratory_id = subscription.laboratory_id

    @property
    def subscription(self):
        """Lazily load and cache the Subscription tied to self.laboratory_id."""
        if self._subscription is None and self.laboratory_id is not None:
            self._subscription = Subscription.query.filter_by(
                laboratory_id=self.laboratory_id
            ).first()
        return self._subscription

    def _resolve_subscription(self, subscription=None):
        """Return the explicitly passed subscription, or fall back to self.subscription."""
        if subscription is not None:
            return subscription
        return self.subscription

    # ==========================================================
    # Getters
    # ==========================================================

    @staticmethod
    def get_subscription_by_laboratory_id(laboratory_id):
        """Fetch the subscription record for a laboratory ID directly from the database."""
        if not laboratory_id:
            return None
        try:
            return Subscription.query.filter_by(laboratory_id=laboratory_id).first()
        except Exception:
            logger.exception("[SubscriptionService.get_subscription_by_laboratory_id] Error")
            return None

    @staticmethod
    def get_by_page(page):
        """Retrieve the laboratory subscription associated with a Page instance."""
        if not page or not getattr(page, "laboratory_id", None):
            return None
        return SubscriptionService.get_subscription_by_laboratory_id(page.laboratory_id)

    def messages_remaining(self, subscription=None):
        """Regular quota messages left before the grace period kicks in (>= 0)."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return 0
        return max(resolved_subscription.message_limit - resolved_subscription.message_used, 0)

    def grace_remaining(self, subscription=None):
        """Grace-period messages left after the regular quota is exhausted (>= 0)."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return 0
        extra = max(resolved_subscription.message_used - resolved_subscription.message_limit, 0)
        return max(resolved_subscription.grace_limit - extra, 0)

    def usage_percentage(self, subscription=None):
        """Percentage of the regular message allowance consumed so far, rounded to 1 decimal."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription or resolved_subscription.message_limit == 0:
            return 0
        return round(
            (resolved_subscription.message_used / resolved_subscription.message_limit) * 100, 1
        )

    # ==========================================================
    # AI Permission
    # ==========================================================

    @staticmethod
    def can_use_ai(target=None, subscription=None) -> tuple[bool, str]:
        """
        Evaluate subscription state, expiration, and message thresholds for AI eligibility.

        This is a @staticmethod: calling it on an instance with no arguments
        (e.g. `sub_service.can_use_ai()`) does NOT pass the instance's subscription
        implicitly and will resolve to "No subscription." Callers must pass an
        explicit target. Supported call shapes:
            - SubscriptionService.can_use_ai(a_subscription_service_instance)
            - SubscriptionService.can_use_ai(a_subscription_model_instance)
            - SubscriptionService.can_use_ai(laboratory_id_int)
            - SubscriptionService.can_use_ai(subscription=an_explicit_subscription)
        """
        resolved_subscription = None
        if isinstance(target, SubscriptionService):
            resolved_subscription = target._resolve_subscription(subscription)
        elif isinstance(target, Subscription):
            resolved_subscription = target
        elif isinstance(target, int):
            resolved_subscription = SubscriptionService.get_subscription_by_laboratory_id(target)
        elif hasattr(target, "laboratory_id"):
            resolved_subscription = SubscriptionService.get_subscription_by_laboratory_id(
                target.laboratory_id
            )
        elif subscription is not None:
            resolved_subscription = subscription

        if not resolved_subscription:
            return False, "No subscription."

        if not resolved_subscription.is_active:
            return False, "Subscription suspended."

        if resolved_subscription.end_date:
            end_date_aware = (
                resolved_subscription.end_date.replace(tzinfo=timezone.utc)
                if resolved_subscription.end_date.tzinfo is None
                else resolved_subscription.end_date
            )
            if datetime.now(timezone.utc) > end_date_aware:
                return False, "Subscription expired by date."

        if (resolved_subscription.message_used or 0) >= (
            (resolved_subscription.message_limit or 0) + (resolved_subscription.grace_limit or 0)
        ):
            return False, "Message limit exceeded."

        return True, "OK"

    @staticmethod
    def consume(subscription, count: int = 1, cost: float = None) -> bool:
        """
        Increment message usage and accumulate estimated model API cost.

        Note: reads-then-writes message_used without row locking, so concurrent
        calls for the same subscription can lose an increment (same lost-update
        pattern as client_service.py chat_history). Not addressed here.
        """
        if not subscription:
            logger.warning("[SubscriptionService.consume] No valid Subscription instance provided.")
            return False

        try:
            subscription.message_used = (subscription.message_used or 0) + count
            if cost is not None:
                subscription.estimated_cost = round((subscription.estimated_cost or 0.0) + float(cost), 6)

            subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            logger.info(
                "[SubscriptionService.consume] Deducted %d messages, cost: %s USD | lab_id=%s | total_used=%d",
                count, cost, getattr(subscription, "laboratory_id", None), subscription.message_used
            )
            return True
        except Exception as e:
            db.session.rollback()
            logger.exception("[SubscriptionService.consume] Error")
            try:
                from notification_center import send_production_alert
                send_production_alert(
                    subject="Subscription Deduction Database Failure",
                    body_or_error=e,
                    context={"laboratory_id": self.laboratory_id, "count": count, "cost": cost},
                    level="ERROR"
                )
            except Exception:
                pass
            return False

    # ==========================================================
    # Status
    # ==========================================================

    def get_status(self, subscription=None):
        """Return {'text', 'color'} badge for the subscription's current state."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return {"text": "No Subscription", "color": "danger"}

        if not resolved_subscription.is_active:
            return {"text": "Suspended", "color": "danger"}
        if resolved_subscription.end_date:
            end_date_aware = (
                resolved_subscription.end_date.replace(tzinfo=timezone.utc)
                if resolved_subscription.end_date.tzinfo is None
                else resolved_subscription.end_date
            )
            if datetime.now(timezone.utc) > end_date_aware:
                return {"text": "Expired", "color": "danger"}

        if resolved_subscription.message_used >= (
            resolved_subscription.message_limit + resolved_subscription.grace_limit
        ):
            return {"text": "Limit Reached", "color": "warning"}

        return {"text": "Active", "color": "success"}

    # ==========================================================
    # Alerts
    # ==========================================================

    def get_alert(self, subscription=None):
        """
        Return a contextual {'type', 'message'} alert, or None if nothing to flag.

        Order of checks: missing subscription, suspended, expired by date, then
        quota (grace-period warning/exhaustion, then low-quota warning at <= 500
        messages remaining).
        """
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return {"type": "danger", "message": "No subscription found."}

        if not resolved_subscription.is_active:
            return {"type": "danger", "message": "AI service is suspended."}
        if resolved_subscription.end_date:
            end_date_aware = (
                resolved_subscription.end_date.replace(tzinfo=timezone.utc)
                if resolved_subscription.end_date.tzinfo is None
                else resolved_subscription.end_date
            )
            if datetime.now(timezone.utc) > end_date_aware:
                return {"type": "danger", "message": "Subscription has expired by date."}

        remaining = self.messages_remaining(resolved_subscription)

        if remaining == 0:
            grace = self.grace_remaining(resolved_subscription)
            if grace > 0:
                return {"type": "warning", "message": f"Main limit reached. {grace} grace messages remaining."}
            return {"type": "danger", "message": "Message limit exceeded."}

        if remaining <= 500:
            return {"type": "warning", "message": f"Only {remaining} messages remaining."}

        return None

    # ==========================================================
    # Renew
    # ==========================================================

    def renew(self, *args, **kwargs):
        """
        Reset usage and extend validity by (30 * months) days.

        Accepts (months) or (subscription, months) positionally, or
        subscription=/months= as keywords. NOTE: positional order is fragile —
        renew(3, some_subscription) would silently treat 3 as months and drop
        the subscription argument. Not changed here to avoid breaking callers;
        flagged as a design risk.
        """
        resolved_subscription = None
        months = 1
        if len(args) > 0 and isinstance(args[0], Subscription):
            resolved_subscription = args[0]
            if len(args) > 1:
                months = args[1]
        elif len(args) > 0:
            months = args[0]

        resolved_subscription = kwargs.get("subscription", resolved_subscription) or \
            self._resolve_subscription(resolved_subscription)
        months = kwargs.get("months", months)

        if not resolved_subscription:
            return

        try:
            now = datetime.now(timezone.utc)
            resolved_subscription.message_used = 0
            resolved_subscription.is_active = True
            if resolved_subscription.end_date:
                end_date_aware = (
                    resolved_subscription.end_date.replace(tzinfo=timezone.utc)
                    if resolved_subscription.end_date.tzinfo is None
                    else resolved_subscription.end_date
                )
                if end_date_aware > now:
                    resolved_subscription.end_date = end_date_aware + timedelta(days=30 * months)
                else:
                    resolved_subscription.start_date = now
                    resolved_subscription.end_date = now + timedelta(days=30 * months)
            else:
                resolved_subscription.start_date = now
                resolved_subscription.end_date = now + timedelta(days=30 * months)
            resolved_subscription.renew_count += 1
            resolved_subscription.last_renewed_at = now
            resolved_subscription.updated_at = now
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.renew] Error")

    # ==========================================================
    # Reset Usage
    # ==========================================================

    def reset_usage(self, subscription=None):
        """Reset message_used back to 0 without touching expiration dates."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return

        try:
            resolved_subscription.message_used = 0
            resolved_subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.reset_usage] Error")

    # ==========================================================
    # Suspend / Activate
    # ==========================================================

    def suspend(self, subscription=None):
        """Set is_active to False, blocking AI usage."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return

        try:
            resolved_subscription.is_active = False
            resolved_subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.suspend] Error")

    def activate(self, subscription=None):
        """Set is_active to True, restoring AI usage."""
        resolved_subscription = self._resolve_subscription(subscription)
        if not resolved_subscription:
            return

        try:
            resolved_subscription.is_active = True
            resolved_subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.activate] Error")

    def update_limit(self, *args, **kwargs):
        """
        Set the regular message_limit ceiling.

        Accepts (message_limit) or (subscription, message_limit) positionally,
        or subscription=/message_limit= as keywords. Same positional-order
        fragility as renew() — not changed here.
        """
        resolved_subscription = None
        limit = 0
        if len(args) > 0 and isinstance(args[0], Subscription):
            resolved_subscription = args[0]
            if len(args) > 1:
                limit = args[1]
        elif len(args) > 0:
            limit = args[0]

        resolved_subscription = kwargs.get("subscription", resolved_subscription) or \
            self._resolve_subscription(resolved_subscription)
        limit = kwargs.get("message_limit", limit)

        if not resolved_subscription:
            return

        try:
            resolved_subscription.message_limit = int(limit)
            resolved_subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.update_limit] Error")

    def update_grace_limit(self, *args, **kwargs):
        """
        Set the grace_limit ceiling.

        Accepts (grace_limit) or (subscription, grace_limit) positionally, or
        subscription=/grace_limit= as keywords. Same positional-order fragility
        as renew() — not changed here.
        """
        resolved_subscription = None
        grace = 0
        if len(args) > 0 and isinstance(args[0], Subscription):
            resolved_subscription = args[0]
            if len(args) > 1:
                grace = args[1]
        elif len(args) > 0:
            grace = args[0]

        resolved_subscription = kwargs.get("subscription", resolved_subscription) or \
            self._resolve_subscription(resolved_subscription)
        grace = kwargs.get("grace_limit", grace)

        if not resolved_subscription:
            return

        try:
            resolved_subscription.grace_limit = int(grace)
            resolved_subscription.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            self._subscription = resolved_subscription
        except Exception:
            db.session.rollback()
            logger.exception("[SubscriptionService.update_grace_limit] Error")