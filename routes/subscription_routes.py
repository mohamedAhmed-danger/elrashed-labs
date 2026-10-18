from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from services.shared.subscription_service import SubscriptionService
from services.domain.laboratory_service import LaboratoryService


subscription_bp = Blueprint('subscription', __name__, url_prefix='/admin/subscription')

@subscription_bp.route("/dashboard")
@login_required
def admin_subscription():
    lab_id = LaboratoryService().get_current_laboratory_id()
    if not lab_id:
        flash("لم يتم العثور على معمل.", "error")
        return redirect(url_for("main.dashboard")) 

    sub_service = SubscriptionService(laboratory_id=lab_id)
    subscription = sub_service.subscription
    if not subscription:
        flash("لا توجد بيانات اشتراك.", "error")
        return redirect(url_for("main.dashboard"))

    return render_template(
        "subscription/index.html",
        subscription=subscription,
        status=sub_service.get_status(),
        alert=sub_service.get_alert(),
        remaining=sub_service.messages_remaining(),
        usage=sub_service.usage_percentage(),
    )

@subscription_bp.route("/renew", methods=["POST"])
@login_required
def renew_subscription():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)
    
    try:
        months = int(request.form.get("months", 1))
        sub_service.renew(months=months)
        flash("تم تجديد الاشتراك بنجاح.", "success")
    except ValueError:
        flash("عدد الشهور غير صحيح.", "error")
        
    return redirect(url_for("subscription.admin_subscription"))

@subscription_bp.route("/reset", methods=["POST"])
@login_required
def reset_subscription_usage():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)

    sub_service.reset_usage()
    flash("تم إعادة ضبط الاستهلاك بنجاح.", "success")
    return redirect(url_for("subscription.admin_subscription"))

@subscription_bp.route("/suspend", methods=["POST"])
@login_required
def suspend_subscription():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)

    sub_service.suspend()
    flash("تم إيقاف الاشتراك.", "warning")
    return redirect(request.referrer or url_for("main.dashboard"))

@subscription_bp.route("/activate", methods=["POST"])
@login_required
def activate_subscription():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)

    sub_service.activate()
    flash("تم تنشيط الاشتراك.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))

@subscription_bp.route("/update-limit", methods=["POST"])
@login_required
def update_subscription_limit():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)

    try:
        new_limit = int(request.form.get("new_limit", 0))
        sub_service.update_limit(new_limit)
        flash("تم تحديث حد الرسائل بنجاح.", "success")
    except ValueError:
        flash("قيمة حد الرسائل غير صحيحة.", "error")

    return redirect(url_for("subscription.admin_subscription"))

@subscription_bp.route("/update-grace", methods=["POST"])
@login_required
def update_subscription_grace():
    lab_id = LaboratoryService().get_current_laboratory_id()
    sub_service = SubscriptionService(laboratory_id=lab_id)

    try:
        new_grace = int(request.form.get("new_grace", 0))
        sub_service.update_grace_limit(new_grace)
        flash("تم تحديث فترة السماح بنجاح.", "success")
    except ValueError:
        flash("قيمة فترة السماح غير صحيحة.", "error")

    return redirect(url_for("subscription.admin_subscription"))