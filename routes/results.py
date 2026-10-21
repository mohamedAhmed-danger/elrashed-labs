from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from models.models import Status
from services.domain.result_service import ResultService

bp = Blueprint('results', __name__, url_prefix='/results')


@bp.route('/')
@login_required
def list_results():
    search = request.args.get('search') or None
    status = request.args.get('status') or None
    pagination = ResultService.list_requests(
        status=status,
        search=search,
        page=request.args.get('page', 1, type=int),
    )
    return render_template(
        'results/list.html',
        results=pagination.items,
        pagination=pagination,
        search=search,
        status=status,
        Status=Status,
    )


@bp.route('/<int:request_id>/status', methods=['POST'])
@login_required
def update_result_status(request_id):
    ResultService.update_status(request_id, request.form.get('status_val'))
    flash('تم تحديث حالة الطلب', 'success')
    return redirect(request.referrer or url_for('results.list_results'))


@bp.route('/<int:request_id>/delete', methods=['POST'])
@login_required
def delete_result(request_id):
    ResultService.delete(request_id)
    flash('تم حذف الطلب', 'success')
    return redirect(url_for('results.list_results'))