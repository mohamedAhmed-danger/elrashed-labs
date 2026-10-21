from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from services.domain.laboratory_service import LaboratoryService
from services.shared.subscription_service import SubscriptionService
from services.domain.tenancy import admin_required
from models.models import Laboratory, db

laboratory_bp = Blueprint('laboratory', __name__, url_prefix='/laboratories')

@laboratory_bp.route('/')
@login_required
def list_laboratories():
    lab_service = LaboratoryService()
    laboratories, _ = lab_service.get_all_laboratories()
    laboratories = laboratories or []
    return render_template(
        'laboratory/list.html',
        laboratories=laboratories,
        ai_info={lab.id: _ai_info(lab, laboratories) for lab in laboratories},
    )


def _labs_sharing(subscription, laboratories):
    """Labs whose messages are billed to this subscription (its owner + labs pointing at it)."""
    owner_id = subscription.laboratory_id
    return [
        lab for lab in laboratories
        if lab.id == owner_id or lab.billing_laboratory_id == owner_id
    ]


def _ai_info(lab, laboratories):
    """AI status for one lab row: which subscription pays for it, its state and usage."""
    subscription = SubscriptionService.get_subscription_by_laboratory_id(lab.id)
    if not subscription:
        return {"has_subscription": False}
    status = SubscriptionService(subscription=subscription).get_status()
    sharing = _labs_sharing(subscription, laboratories)
    limit = subscription.message_limit or 0
    return {
        "has_subscription": True,
        "is_active": subscription.is_active,
        "status": status,
        "used": subscription.message_used or 0,
        "limit": limit,
        "percent": round((subscription.message_used or 0) / limit * 100, 1) if limit else 0,
        "shared": len(sharing) > 1,
        "shared_names": [other.name for other in sharing if other.id != lab.id],
        "paid_by": subscription.laboratory.name if subscription.laboratory_id != lab.id else None,
    }


def _set_lab_ai(lab_id, active):
    lab = db.session.get(Laboratory, lab_id)
    if not lab:
        flash("المعمل غير موجود.", "error")
        return redirect(url_for('laboratory.list_laboratories'))

    subscription = SubscriptionService.get_subscription_by_laboratory_id(lab_id)
    if not subscription:
        flash(f"{lab.name}: لا يوجد اشتراك مرتبط بالمعمل ده.", "error")
        return redirect(url_for('laboratory.list_laboratories'))

    service = SubscriptionService(subscription=subscription)
    service.activate() if active else service.suspend()

    sharing = [other.name for other in _labs_sharing(subscription, Laboratory.query.all())]
    scope = f" (الاشتراك مشترك بين: {'، '.join(sharing)})" if len(sharing) > 1 else ""
    if active:
        flash(f"تم تفعيل الذكاء الاصطناعي لـ {lab.name}{scope}.", "success")
    else:
        flash(f"تم إيقاف الذكاء الاصطناعي لـ {lab.name}{scope}.", "warning")
    return redirect(url_for('laboratory.list_laboratories'))


@laboratory_bp.route('/<int:lab_id>/ai/suspend', methods=['POST'])
@login_required
@admin_required
def suspend_laboratory_ai(lab_id):
    return _set_lab_ai(lab_id, active=False)


@laboratory_bp.route('/<int:lab_id>/ai/activate', methods=['POST'])
@login_required
@admin_required
def activate_laboratory_ai(lab_id):
    return _set_lab_ai(lab_id, active=True)

@laboratory_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_laboratory():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()

        lab_service = LaboratoryService()
        lab, msg = lab_service.create_laboratory(name, location, description)
        
        if lab:
            flash(msg, 'success')
            return redirect(url_for('laboratory.list_laboratories'))
        
        flash(msg, 'error') 

    return render_template('laboratory/create.html')

@laboratory_bp.route('/<int:lab_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_laboratory(lab_id):
    lab_service = LaboratoryService(lab_id=lab_id)
    lab, msg = lab_service.get_laboratory()
    if not lab:
        flash(msg, 'error')
        return redirect(url_for('laboratory.list_laboratories'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()

        updated_lab, update_msg = lab_service.update_laboratory(
            name=name, location=location, description=description,
            logo_path=request.form.get('logo_path', ''),
            support_phone=request.form.get('support_phone', ''),
            notification_email=request.form.get('notification_email', ''),
            billing_laboratory_id=request.form.get('billing_laboratory_id', type=int),
            set_billing=True,
        )
        if updated_lab:
            flash(update_msg, 'success')
            return redirect(url_for('laboratory.list_laboratories'))
        
        flash(update_msg, 'error')

    all_labs, _ = lab_service.get_all_laboratories()
    return render_template('laboratory/edit.html', laboratory=lab, all_labs=all_labs or [])