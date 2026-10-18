import os
from flask import Blueprint, request, render_template, flash, url_for, redirect, current_app
from flask_login import login_required

from models.models import Status
from services.domain.inquiry_service import InquiryService

inquiries_bp = Blueprint('inquiries', __name__, url_prefix='/inquiries')


def _attach_image_info(inquiry):
    """
    بتاخد أي inquiry وتحط عليه image_url و image_exists جاهزين للـ template.
    بتتعامل مع الحالتين: القديمة (مسار كامل كان متخزن قبل التصحيح)
    والجديدة (اسم ملف بس)، من غير أي تعديل على الداتابيز.
    """
    inquiry.image_url = None
    inquiry.image_exists = False

    if not inquiry.prescription_img:
        return inquiry

    # basename بتشتغل صح سواء القيمة مسار كامل قديم أو اسم ملف جديد
    filename = os.path.basename(inquiry.prescription_img)
    uploads_dir = os.path.join(current_app.root_path, "static", "uploads")
    full_path = os.path.join(uploads_dir, filename)

    if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
        inquiry.image_exists = True
        inquiry.image_url = url_for('static', filename=f'uploads/{filename}')

    return inquiry


@inquiries_bp.route('/')
@login_required
def list_inquiries():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '')

    inquiry_service = InquiryService()
    pagination, _ = inquiry_service.get_all_inquiries(
        page=page, per_page=10, search=search or None, status=status or None
    )
    for inq in pagination.items:
        _attach_image_info(inq)

    stats = inquiry_service.get_stats()

    return render_template(
        'inquiries/list.html',
        inquiries=pagination.items,
        pagination=pagination,
        search=search,
        status=status,
        statuses=Status,
        stats=stats,
    )


@inquiries_bp.route('/<int:inquiry_id>')
@login_required
def inquiry_detail(inquiry_id):
    inquiry_service = InquiryService(inquiry_id=inquiry_id)
    result = inquiry_service.get_inquiry()
    if not result.success:
        flash(result.message, 'error')
        return redirect(url_for('inquiries.list_inquiries'))

    _attach_image_info(result.inquiry)
    return render_template(
        'inquiries/detail.html',
        inquiry=result.inquiry,
        discounts=InquiryService.DISCOUNTS,
    )


@inquiries_bp.route('/<int:inquiry_id>/status', methods=['POST'])
@login_required
def update_inquiry_status(inquiry_id):
    new_status = request.form.get('status')
    inquiry_service = InquiryService(inquiry_id=inquiry_id)
    result = inquiry_service.update_status(new_status)
    flash(result.message, 'success' if result.success else 'error')
    return redirect(request.referrer or url_for('inquiries.list_inquiries'))


@inquiries_bp.route('/<int:inquiry_id>/confirm', methods=['POST'])
@login_required
def confirm_inquiry(inquiry_id):
    selected_service_ids = request.form.getlist('selected_services')

    if not selected_service_ids:
        flash('يرجى تحديد خدمة واحدة على الأقل.', 'error')
        return redirect(url_for('inquiries.inquiry_detail', inquiry_id=inquiry_id))

    # نوع الخصم اختياري، وأي قيمة مش معروفة بتتتجاهل
    discount_type = request.form.get('discount_type') or None
    if discount_type not in InquiryService.DISCOUNTS:
        discount_type = None

    inquiry_service = InquiryService(inquiry_id=inquiry_id)
    success, message = inquiry_service.confirm_and_reply(
        selected_service_ids, discount_type=discount_type
    )

    flash(message, 'success' if success else 'error')
    return redirect(url_for('inquiries.inquiry_detail', inquiry_id=inquiry_id))