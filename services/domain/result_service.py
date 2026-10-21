import logging
from datetime import datetime, timezone, timedelta

from models.models import db, ResultRequest, Status
from services.domain.tenancy import scope_query, get_scoped

logger = logging.getLogger(__name__)


class ResultService:
    DEDUP_HOURS = 24

    @staticmethod
    def create_request(user_identity, laboratory_id=None):
        """Create a result request unless the same identity already has a recent PENDING one for this lab."""
        since = datetime.now(timezone.utc) - timedelta(hours=ResultService.DEDUP_HOURS)
        query = ResultRequest.query.filter(
            ResultRequest.user_identity == user_identity,
            ResultRequest.status == Status.PENDING,
            ResultRequest.created_at >= since,
        )
        if laboratory_id is not None:
            query = query.filter(ResultRequest.laboratory_id == laboratory_id)

        existing = query.first()
        if existing:
            return existing, False

        req = ResultRequest(
            user_identity=user_identity,
            laboratory_id=laboratory_id,
        )
        try:
            db.session.add(req)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[ResultService.create_request] Error")
            raise
        return req, True

    @staticmethod
    def list_requests(status=None, search=None, page=1, per_page=20):
        """Fetch paginated result requests, scoped to current lab user when applicable."""
        q = scope_query(ResultRequest.query, ResultRequest).order_by(ResultRequest.created_at.desc())
        if status:
            try:
                q = q.filter(ResultRequest.status == Status(status))
            except ValueError:
                pass
        if search:
            q = q.filter(ResultRequest.user_identity.ilike(f"%{search}%"))
        return q.paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def update_status(request_id, status_value):
        """Update a result request's status, scoped by lab access."""
        req = get_scoped(ResultRequest, request_id)
        if not req or not status_value:
            return None
        try:
            req.status = Status(status_value)
            db.session.commit()
        except ValueError:
            return None
        except Exception:
            db.session.rollback()
            logger.exception("[ResultService.update_status] Error")
            return None
        return req

    @staticmethod
    def delete(request_id):
        """Delete a result request, scoped by lab access."""
        req = get_scoped(ResultRequest, request_id)
        if not req:
            return
        try:
            db.session.delete(req)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[ResultService.delete] Error")

    @staticmethod
    def count_pending():
        """Count pending result requests, scoped to current lab user."""
        q = scope_query(ResultRequest.query, ResultRequest)
        return q.filter(ResultRequest.status == Status.PENDING).count()
