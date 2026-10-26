"""
Central lab-isolation helpers.

One place decides "which lab's data may this request see", so no route or
service has to remember to add a filter by hand.

- Admin (role == 'admin'): sees every lab.
- Lab user: sees only rows where laboratory_id == user.laboratory_id.
- Lab user with no laboratory_id: sees nothing (fail closed).
- Outside a request (agent / worker): no scoping here; the caller passes
  laboratory_id explicitly (it comes from the page, never from the LLM).
"""
from functools import wraps

from flask import abort, has_request_context
from flask_login import current_user

from models.models import db


def _user():
    if not has_request_context():
        return None
    if not getattr(current_user, "is_authenticated", False):
        return None
    return current_user


def is_scoped() -> bool:
    """True when the current request must be limited to one lab."""
    user = _user()
    return user is not None and not user.is_admin


def current_lab_id():
    """Lab id the current request is limited to, or None (admin / no request)."""
    user = _user()
    if user is None or user.is_admin:
        return None
    return user.laboratory_id


def scope_query(query, model):
    """Limit a query on `model` (must have laboratory_id) to the user's lab."""
    if not is_scoped():
        return query
    lab_id = current_lab_id()
    if lab_id is None:
        return query.filter(db.false())
    return query.filter(model.laboratory_id == lab_id)


def scope_feedback_query(query):
    """
    Limit a Feedback query to the user's lab.

    Matches either directly by Feedback.laboratory_id or via matching
    Booking.reference_id for backward compatibility. Fails closed.
    """
    if not is_scoped():
        return query
    from models.models import Booking, Feedback
    lab_id = current_lab_id()
    if lab_id is None:
        return query.filter(db.false())
    lab_refs = db.session.query(Booking.reference_id).filter(
        Booking.laboratory_id == lab_id,
        Booking.reference_id.isnot(None),
    )
    return query.filter(
        db.or_(
            Feedback.laboratory_id == lab_id,
            Feedback.reference_id.in_(lab_refs),
        )
    )


def can_access(record) -> bool:
    """True if the current request may see this record."""
    if record is None:
        return False
    if not is_scoped():
        return True
    lab_id = current_lab_id()
    return lab_id is not None and getattr(record, "laboratory_id", None) == lab_id


def get_scoped(model, record_id):
    """db.session.get that returns None for another lab's record."""
    record = db.session.get(model, record_id)
    return record if can_access(record) else None


def admin_required(view):
    """Only admins may call this route (everyone else gets 403)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = _user()
        if user is None or not user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper
