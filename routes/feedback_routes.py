from flask import Blueprint, request, render_template, jsonify
from flask_login import login_required
from services.domain.feedback_service import FeedbackService 

feedbacks_bp = Blueprint('feedbacks', __name__)

@feedbacks_bp.route("/feedback/<reference_id>", methods=["GET"])
def submit_feedback_page(reference_id):
    feedback_service = FeedbackService(reference_id=reference_id)
    visit = feedback_service.get_visit_by_reference()
    lab_name = None
    laboratory_id = None
    if visit and visit.laboratory_id:
        from models.models import Laboratory, db
        lab = db.session.get(Laboratory, visit.laboratory_id)
        if lab:
            lab_name = lab.name
            laboratory_id = lab.id
    return render_template(
        "feedback/submit_feedback.html",
        reference_id=reference_id,
        visit_name=visit.name if visit else None,
        visit_phone=visit.phone_number if visit else None,
        not_found=not bool(visit),
        lab_name=lab_name,
        laboratory_id=laboratory_id,
        is_direct_lab=False,
    )

@feedbacks_bp.route("/feedback/lab/<int:lab_id>", methods=["GET"])
def submit_lab_feedback_page(lab_id):
    from models.models import Laboratory, db
    lab = db.session.get(Laboratory, lab_id)
    if not lab:
        return render_template(
            "feedback/submit_feedback.html",
            reference_id=None,
            visit_name=None,
            visit_phone=None,
            not_found=True,
            lab_name=None,
            laboratory_id=None,
            is_direct_lab=True,
        )
    return render_template(
        "feedback/submit_feedback.html",
        reference_id=None,
        visit_name=None,
        visit_phone=None,
        not_found=False,
        lab_name=lab.name,
        laboratory_id=lab.id,
        is_direct_lab=True,
    )

@feedbacks_bp.route("/api/feedback", methods=["POST"])
def submit_feedback():
    data = request.get_json(silent=True) or {}
    feedback_service = FeedbackService()
    success, message, status_code = feedback_service.submit_feedback(data)
    
    return jsonify({
        "success": success,
        "message" if success else "error": message
    }), status_code

@feedbacks_bp.route('/admin/feedbacks')
@login_required
def list_feedbacks_page():
    feedback_service = FeedbackService()
    pagination, stats = feedback_service.get_feedbacks_with_stats(
        page=request.args.get("page", 1, type=int),
        ref_id=request.args.get("reference_id"),
        min_rating=request.args.get("min_rating", type=int)
    )
    
    return render_template(
        "feedback/dashboard_feedback.html",
        feedbacks=pagination.items,
        pagination=pagination,
        stats=stats
    )