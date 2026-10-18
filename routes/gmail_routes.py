import json
import os
from flask import Blueprint, redirect, request, session, url_for, jsonify, render_template
from flask_login import login_required
from google_auth_oauthlib.flow import Flow
from config import Config
from services.domain.tenant_service import TenantService

gmail_auth_bp = Blueprint("gmail_auth", __name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# في البيئة الحية نلغي السماح بـ HTTP غير المشفر
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "0"


@gmail_auth_bp.route("/gmail/settings")
@login_required
def settings_page():
    settings = TenantService.get_tenant_settings("default_tenant")

    gmail_connected = bool(settings and settings.gmail_token_json)

    emails = []
    if settings and settings.notification_email:
        emails = [e.strip() for e in settings.notification_email.split(",") if e.strip()]

    status = request.args.get("status")

    return render_template(
        "settings.html",
        gmail_connected=gmail_connected,
        emails_json=json.dumps(emails, ensure_ascii=False),
        status=status,
    )


@gmail_auth_bp.route("/api/gmail/connect")
@login_required
def connect_gmail():
    # إجبار رابط الـ Callback على استخدام HTTPS
    redirect_uri = url_for("gmail_auth.gmail_callback", _external=True, _scheme="https")

    flow = Flow.from_client_secrets_file(
        Config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    
    session["oauth_state"] = state
    if hasattr(flow, "code_verifier") and flow.code_verifier:
        session["code_verifier"] = flow.code_verifier
    
    return redirect(authorization_url)


@gmail_auth_bp.route("/api/gmail/callback")
def gmail_callback():
    code_verifier = session.get("code_verifier")
    
    # استخدام نفس رابط الـ Callback بنفس البروتوكول
    redirect_uri = url_for("gmail_auth.gmail_callback", _external=True, _scheme="https")

    flow = Flow.from_client_secrets_file(
        Config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        state=session.get("oauth_state"),
        redirect_uri=redirect_uri,
        code_verifier=code_verifier
    )
    
    # تعديل الـ URL في الـ request ليتطابق مع HTTPS إذا قام Nginx بتحويله
    authorization_response = request.url
    if authorization_response.startswith("http://"):
        authorization_response = "https://" + authorization_response[7:]

    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    
    TenantService.save_gmail_credentials(credentials.to_json(), tenant_id="default_tenant")
        
    return redirect(url_for("gmail_auth.settings_page", status="gmail_success"))


@gmail_auth_bp.route("/api/gmail/save-recipient", methods=["POST"])
@login_required
def save_recipient():
    data = request.json
    tenant_id = session.get("tenant_id", "default_tenant")

    emails = data.get("emails")
    if emails and isinstance(emails, list):
        if len(emails) > 3:
            return jsonify({"success": False, "message": "يمكن إضافة 3 إيميلات بحد أقصى."})
        recipient_email = ", ".join(e.strip() for e in emails if e.strip())
    else:
        recipient_email = data.get("email", "").strip()

    if not recipient_email:
        return jsonify({"success": False, "message": "برجاء إدخال إيميل واحد على الأقل."})

    TenantService.save_notification_email(recipient_email, tenant_id=tenant_id)
    
    return jsonify({"success": True, "message": "تم حفظ إيميلات الاستقبال بنجاح."})