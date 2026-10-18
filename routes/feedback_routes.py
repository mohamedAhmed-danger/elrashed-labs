from flask import Blueprint, request, render_template, jsonify
from flask_login import login_required
from services.domain.feedback_service import FeedbackService 

feedbacks_bp = Blueprint('feedbacks', __name__)

@feedbacks_bp.route("/feedback/<reference_id>", methods=["GET"])
def submit_feedback_page(reference_id):
    feedback_service = FeedbackService(reference_id=reference_id)
    visit = feedback_service.get_visit_by_reference()
    return render_template(
        "feedback/submit_feedback.html",
        reference_id=reference_id,
        visit_name=visit.name if visit else None,
        visit_phone=visit.phone_number if visit else None,
        not_found=not bool(visit),
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