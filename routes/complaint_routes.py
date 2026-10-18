from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file
from flask_login import login_required
from models.models import Status
from services.domain.complaint_service import ComplaintService

complaints_bp = Blueprint('complaints', __name__, url_prefix='/complaints')

@complaints_bp.route('/')
@login_required
def list_complaints():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')

    complaint_service = ComplaintService()
    pagination, _ = complaint_service.get_all_complaints(page=page, search=search, status=status)
    return render_template('complaints/list.html', pagination=pagination, complaints=pagination.items,
                           search=search, status=status, Status=Status)


# ── NEW: single complaint detail page ───────────────────────────
# بيعرض نص الشكوى كامل بدل ما يتقصّ في الجدول.
@complaints_bp.route('/<int:complaint_id>')
@login_required
def complaint_detail(complaint_id):
    complaint_service = ComplaintService(complaint_id=complaint_id)

    # ⚠️ نفس الافتراض بتاع البوكينج: لو الـ property اسمها مختلف عندك غيّرها هنا.
    complaint = getattr(complaint_service, 'complaint', None)

    if not complaint:
        flash("الشكوى غير موجودة.", 'danger')
        return redirect(url_for('complaints.list_complaints'))

    return render_template('complaints/detail.html', complaint=complaint, Status=Status)


@complaints_bp.route('/update_status/<int:complaint_id>', methods=['POST'])
@login_required
def update_complaint_status(complaint_id):
    try:
        status_enum = Status(request.form.get('status_val'))
    except ValueError:
        flash("حالة غير صحيحة", 'danger')
        return redirect(url_for('complaints.list_complaints'))

    complaint_service = ComplaintService(complaint_id=complaint_id)
    updated, message = complaint_service.update_complaint_status(status_enum)
    flash(message, 'success' if updated else 'danger')

    return redirect(request.referrer or url_for('complaints.list_complaints'))


@complaints_bp.route('/export')
@login_required
def export_complaints():
    complaint_service = ComplaintService()
    output = complaint_service.export_to_excel(
        search=request.args.get('search', '').strip(),
        status=request.args.get('status', '')
    )
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='complaints.xlsx')