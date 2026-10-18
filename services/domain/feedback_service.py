import logging
from datetime import datetime, timezone

from sqlalchemy import case, func

from models.models import db, Feedback
from services.domain.booking_service import BookingService

logger = logging.getLogger(__name__)

MIN_RATING = 1
MAX_RATING = 5


class FeedbackService:
    def __init__(self, feedback_id=None, reference_id=None, feedback=None):
        """يقبل feedback_id أو reference_id أو Feedback جاهز (بيتزامن منه الاتنين)."""
        self.feedback_id = feedback_id
        self.reference_id = reference_id
        self._feedback = feedback
        if feedback:
            self.feedback_id = feedback.id
            self.reference_id = feedback.reference_id

    @property
    def feedback(self):
        """يحمّل الـ Feedback بالـ feedback_id أو reference_id (مرة واحدة ويتخزن)."""
        if self._feedback is None:
            if self.feedback_id is not None:
                self._feedback = db.session.get(Feedback, self.feedback_id)
            elif self.reference_id is not None:
                self._feedback = Feedback.query.filter_by(reference_id=self.reference_id).first()
        return self._feedback

    def _save_feedback(self, ref, name, phone_number, overall_rating, ease_of_use, feedback_text):
        """يحفظ تقييم جديد ويحدّث حالة الـ service. الـ rollback مسؤولية المستدعي."""
        feedback = Feedback(
            reference_id=ref,
            name=name,
            phone_number=phone_number,
            overall_rating=overall_rating,
            ease_of_use=ease_of_use,
            feedback_text=feedback_text,
            created_at=datetime.now(timezone.utc),
        )
        db.session.add(feedback)
        db.session.commit()
        self._feedback = feedback
        self.feedback_id = feedback.id
        self.reference_id = feedback.reference_id
        return feedback

    def create_feedback(self, reference_id=None, name=None, phone_number=None,
                        overall_rating=None, ease_of_use=None, feedback_text=None):
        """ينشئ تقييم. يرجّع (Feedback أو None، رسالة)."""
        ref = reference_id or self.reference_id
        try:
            feedback = self._save_feedback(
                ref, name, phone_number,
                int(overall_rating), int(ease_of_use), feedback_text,
            )
            return feedback, "تم حفظ التقييم بنجاح"
        except Exception:
            db.session.rollback()
            logger.exception("[FeedbackService.create_feedback] Failed | ref=%s", ref)
            return None, "حدث خطأ أثناء حفظ التقييم"

    def _filtered_query(self, ref, min_rating):
        query = Feedback.query.order_by(Feedback.created_at.desc())
        if ref:
            query = query.filter(Feedback.reference_id == ref)
        if min_rating:
            query = query.filter(Feedback.overall_rating >= min_rating)
        return query

    def get_feedbacks(self, page=1, per_page=15, reference_id=None, min_rating=None):
        """تقييمات مقسّمة صفحات، مع فلتر اختياري بالمرجع وأقل تقييم. يرجّع (Pagination أو None، رسالة)."""
        ref = reference_id or self.reference_id
        try:
            query = self._filtered_query(ref, min_rating)
            return query.paginate(page=page, per_page=per_page, error_out=False), "تم جلب التقييمات"
        except Exception:
            logger.exception("[FeedbackService.get_feedbacks] Failed")
            return None, "حدث خطأ أثناء جلب التقييمات"

    def get_visit_by_reference(self, reference_id=None):
        """يرجّع الحجز المرتبط بالمرجع، أو None."""
        ref = reference_id or self.reference_id
        if not ref:
            return None
        return BookingService.get_booking_by_ref(ref)

    def submit_feedback(self, data):
        """
        يتحقق من بيانات التقييم القادمة من الفورم/API ويحفظه.
        يرجّع (نجاح، رسالة، HTTP status).
        """
        ref = data.get("reference_id") or self.reference_id

        missing = [f for f in ("name", "phone_number", "overall_rating", "ease_of_use") if not data.get(f)]
        if not ref:
            missing.append("reference_id")
        if missing:
            return False, f"الحقول دي ناقصة: {', '.join(missing)}", 400

        try:
            overall_rating = int(data.get("overall_rating"))
            ease_of_use = int(data.get("ease_of_use"))
        except (TypeError, ValueError):
            return False, "overall_rating و ease_of_use لازم يكونوا أرقام", 400

        if not (MIN_RATING <= overall_rating <= MAX_RATING) or not (MIN_RATING <= ease_of_use <= MAX_RATING):
            return False, f"التقييم لازم يكون بين {MIN_RATING} و {MAX_RATING}", 400

        try:
            self._save_feedback(
                ref, data.get("name"), data.get("phone_number"),
                overall_rating, ease_of_use, data.get("feedback_text"),
            )
            return True, "تم إرسال تقييمك بنجاح", 201
        except Exception:
            db.session.rollback()
            logger.exception("[FeedbackService.submit_feedback] Failed | ref=%s", ref)
            return False, "حدث خطأ داخلي، يرجى المحاولة لاحقًا", 500

    def get_feedbacks_with_stats(self, page=1, per_page=15, ref_id=None, min_rating=None):
        """
        تقييمات مقسّمة صفحات + إحصائيات.
        الإحصائيات (total, avg_overall, avg_ease, low_ratings) على كل التقييمات
        ومش متأثرة بفلتر ref_id/min_rating بتاع القايمة.
        """
        ref = ref_id or self.reference_id
        pagination = self._filtered_query(ref, min_rating).paginate(
            page=page, per_page=per_page, error_out=False
        )

        total, avg_overall, avg_ease, low_ratings = db.session.query(
            func.count(Feedback.id),
            func.avg(Feedback.overall_rating),
            func.avg(Feedback.ease_of_use),
            func.sum(case((Feedback.overall_rating <= 2, 1), else_=0)),
        ).one()

        # MySQL بيرجّع Decimal، فنحوّل لأنواع بايثون عادية عشان الـ JSON
        stats = {
            "total": int(total or 0),
            "avg_overall": round(float(avg_overall), 1) if avg_overall else 0,
            "avg_ease": round(float(avg_ease), 1) if avg_ease else 0,
            "low_ratings": int(low_ratings or 0),
        }
        return pagination, stats