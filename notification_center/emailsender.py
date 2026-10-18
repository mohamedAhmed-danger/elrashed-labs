import os
import smtplib
import logging
import traceback
import threading
import time
import base64
import json
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from typing import Any, Callable, Dict, Optional
from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from notification_center.exceptions import LabSystemException
from services.domain.tenant_service import TenantService

load_dotenv() 

logger = logging.getLogger(__name__)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
IMAP_SERVER = os.environ.get("IMAP_SERVER", "")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))

# Keys that may contain sensitive data and should be masked in alert emails
SENSITIVE_KEYS = {"token", "password", "secret", "key", "access_token", "api_key", "authorization"}


def _sanitize_value(key: str, val: Any) -> Any:
    if not isinstance(key, str):
        return val
    k_lower = key.lower()
    if any(s in k_lower for s in SENSITIVE_KEYS) and isinstance(val, str) and len(val) > 8:
        return val[:4] + "..." + val[-4:]
    return val


def _sanitize_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not context or not isinstance(context, dict):
        return {}
    return {k: _sanitize_value(k, v) for k, v in context.items() if v is not None}


class EmailClient:
    def __init__(self, smtp_server=None, smtp_port=None, imap_server=None, imap_port=None):
        self.smtp_server = smtp_server or os.environ.get("SMTP_SERVER", "")
        self.smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", "465"))
        self.imap_server = imap_server or os.environ.get("IMAP_SERVER", "")
        self.imap_port = int(imap_port or os.environ.get("IMAP_PORT", "993"))
        
        # Deduplication / throttling state
        self._lock = threading.Lock()
        self._dedup_cache: Dict[str, Dict[str, Any]] = {}
        self._cooldown_seconds = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "300"))  # 5 minutes

    def _should_throttle(self, dedup_key: str, force: bool = False) -> tuple[bool, int]:
        """Check if an alert with this key was recently sent, to prevent spam loops."""
        if force or self._cooldown_seconds <= 0:
            return False, 1

        now = time.time()
        with self._lock:
            # Clean old entries
            expired_keys = [k for k, v in self._dedup_cache.items() if now - v["first_seen"] > 3600]
            for k in expired_keys:
                del self._dedup_cache[k]

            entry = self._dedup_cache.get(dedup_key)
            if entry:
                entry["count"] += 1
                if now - entry["last_sent"] < self._cooldown_seconds:
                    return True, entry["count"]
                else:
                    entry["last_sent"] = now
                    return False, entry["count"]
            else:
                self._dedup_cache[dedup_key] = {
                    "first_seen": now,
                    "last_sent": now,
                    "count": 1,
                }
                return False, 1

    # =========================
    # SMTP Send
    # =========================
    def send_email(self, subject: str, body: str) -> bool:
        sender = os.environ.get("NOTIFICATION_EMAIL_SENDER", "")
        password = os.environ.get("NOTIFICATION_EMAIL_PASSWORD", "")
        receivers_str = os.environ.get("NOTIFICATION_EMAIL_RECEIVERS", "")
        receivers = [r.strip() for r in receivers_str.split(",") if r.strip()]

        if not sender or not password or not receivers:
            logger.error("[NotificationCenter] Missing email credentials or receivers in environment.")
            return False

        machine_identifier = os.environ.get("SERVER_IDENTIFIER", "elbedawy-labs-agent")
        final_body = f"[{machine_identifier}]\n\n{body}"

        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=15) as server:
                server.login(sender, password)
                for receiver in receivers:
                    msg = MIMEMultipart()
                    msg["From"] = sender
                    msg["To"] = receiver
                    msg["Subject"] = subject
                    msg.attach(MIMEText(final_body, "plain", "utf-8"))
                    server.send_message(msg)
            logger.info("[NotificationCenter] Alert email sent: '%s' to %s", subject, receivers)
            return True
        except Exception as e:
            logger.error("[NotificationCenter] SMTP Error sending email '%s': %s", subject, e, exc_info=True)
            return False


email_client = EmailClient()


def send_production_alert(
    subject: str,
    body_or_error: Any,
    context: Optional[Dict[str, Any]] = None,
    level: str = "ERROR",
    force: bool = False,
) -> bool:
    """
    Centralized helper function to send production alert notifications with rate-limiting.
    Included in context: page_id, client_id, booking_id, sender_id, route, etc.
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Extract exception details
    error_code = "SYSTEM_ERROR"
    combined_context = {}

    if isinstance(body_or_error, LabSystemException):
        error_code = body_or_error.error_code
        combined_context.update(body_or_error.context)
        body_or_error.alert_sent = True
        error_type = type(body_or_error).__name__
        error_msg = body_or_error.message
        tb_str = body_or_error.get_full_traceback()
        error_str = f"Exception Type: {error_type} [{error_code}]\nMessage: {error_msg}\nTraceback:\n{tb_str}"
    elif isinstance(body_or_error, Exception):
        error_type = type(body_or_error).__name__
        error_msg = str(body_or_error)
        tb_str = traceback.format_exc()
        error_str = f"Exception Type: {error_type}\nMessage: {error_msg}\nTraceback:\n{tb_str}"
    else:
        error_type = "GenericAlert"
        error_msg = str(body_or_error)
        error_str = f"Details:\n{error_msg}"

    if context and isinstance(context, dict):
        combined_context.update(context)

    sanitized_context = _sanitize_context(combined_context)

    # Throttling key
    dedup_key = f"{subject}:{error_type}:{error_code}"
    should_throttle, occurrence_count = email_client._should_throttle(dedup_key, force=force)
    
    if should_throttle:
        logger.warning(
            "[NotificationCenter] Throttled duplicate alert: '%s' | %s (Occurred %d times)",
            subject, error_type, occurrence_count
        )
        return False

    context_lines = [f"  • {k}: {v}" for k, v in sanitized_context.items()]
    context_str = "\nContext Information:\n" + "\n".join(context_lines) if context_lines else ""

    throttle_note = f"\n(Notice: this alert occurred {occurrence_count} times in the current window)" if occurrence_count > 1 else ""

    body = (
        f"🚨 PRODUCTION FAILURE / ALERT DETECTED\n"
        f"═══════════════════════════════════════════════════════════════\n"
        f"Timestamp:   {now_utc}\n"
        f"Alert Level: {level.upper()}\n"
        f"Subject:     {subject}\n"
        f"Error Code:  {error_code}\n"
        f"═══════════════════════════════════════════════════════════════\n\n"
        f"{error_str}\n"
        f"{context_str}\n"
        f"{throttle_note}"
    )

    formatted_subject = f"[{level.upper()}] {subject}"
    return email_client.send_email(subject=formatted_subject, body=body)


from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

def send_visit_confirmation_email(
    reference_id: str,
    name: str,
    phone: str,
    address: str,
    details: str,
    date: str,
    time: str,
    comes_from: str,
) -> bool:
    """
    Sends a home visit booking confirmation email using Gmail API with automatic token refresh handling.
    """
    try:
        # Fetch default tenant settings
        settings = TenantService.get_tenant_settings("default_tenant")
        
        if not settings or not settings.notification_email or not settings.gmail_token_json:
            logger.error("[NotificationCenter] Missing settings, email, or token for home visit notification.")
            return False

        # Build email body
        email_body = (
            f"New Home Visit Booking\n\n"
            f"Reference ID: {reference_id}\n"
            f"Patient Name: {name}\n"
            f"Phone: {phone}\n"
            f"Address: {address}\n"
            f"Lab Tests: {details}\n"
            f"Date: {date}\n"
            f"Time: {time}\n"
            f"Source: {comes_from}\n"
        )
        subject = f"New Home Visit Booking - #{reference_id}"
        # Parse comma-separated recipients
        recipients = [r.strip() for r in settings.notification_email.split(",") if r.strip()]

        # Setup credentials
        SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
        token_info = json.loads(settings.gmail_token_json)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

        # 🛠️ Refresh token handling
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Update saved settings with refreshed token if necessary
                if hasattr(settings, 'gmail_token_json'):
                    settings.gmail_token_json = creds.to_json()
                    # db.session.commit() # Save if DB model
            except RefreshError as refresh_err:
                logger.error("[NotificationCenter] Refresh token expired/revoked: %s", refresh_err)
                send_production_alert(
                    subject="Gmail OAuth Refresh Token Failure",
                    body_or_error=refresh_err,
                    context={"reference_id": reference_id, "recipients": recipients},
                    level="ERROR"
                )
                return False

        gmail_service = build("gmail", "v1", credentials=creds)

        # Send email to each recipient
        for recipient in recipients:
            message = (
                f"To: {recipient}\r\n"
                f"Subject: {subject}\r\n"
                f"\r\n"
                f"{email_body}"
            )
            raw_message = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            gmail_service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()

        logger.info("[NotificationCenter] Booking email sent successfully to %s", recipients)
        return True

    except Exception as e:
        logger.exception("[NotificationCenter] Failed to send home visit notification: %s", e)
        send_production_alert(
            subject=f"Home Visit Notification Delivery Failure (#{reference_id})",
            body_or_error=e,
            context={"reference_id": reference_id, "patient_name": name, "phone": phone},
            level="ERROR"
        )
        return False


def send_pending_prescription_email(
    inquiry_id: int,
    comes_from: str,
    confidence_score: float,
    extracted_tests: str,
    ocr_extracted_text: str = "",
) -> bool:
    """
    Sends an email alert when a prescription is saved with PENDING status
    (low OCR confidence requiring manual doctor review).
    Uses the same Gmail API flow as send_visit_confirmation_email.
    """
    try:
        # Fetch default tenant settings
        settings = TenantService.get_tenant_settings("default_tenant")

        if not settings or not settings.notification_email or not settings.gmail_token_json:
            logger.error("[NotificationCenter] Missing settings, email, or token for pending prescription notification.")
            return False

        # Build email body
        email_body = (
            f"⚠️ New Pending Prescription – Doctor Review Required\n\n"
            f"Inquiry ID: {inquiry_id}\n"
            f"Source: {comes_from}\n"
            f"OCR Confidence: {confidence_score:.2f}\n"
            f"This prescription has low OCR confidence and requires manual review.\n"
            f"Please log in to the dashboard to review and confirm the required tests.\n"
        )
        subject = f"⚠️ Pending Prescription Review – Inquiry #{inquiry_id}"
        # Parse comma-separated recipients
        recipients = [r.strip() for r in settings.notification_email.split(",") if r.strip()]

        # Setup credentials
        SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
        token_info = json.loads(settings.gmail_token_json)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

        # 🛠️ Refresh token handling
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                if hasattr(settings, 'gmail_token_json'):
                    settings.gmail_token_json = creds.to_json()
            except RefreshError as refresh_err:
                logger.error("[NotificationCenter] Refresh token expired/revoked: %s", refresh_err)
                send_production_alert(
                    subject="Gmail OAuth Refresh Token Failure (Pending Prescription)",
                    body_or_error=refresh_err,
                    context={"inquiry_id": inquiry_id, "recipients": recipients},
                    level="ERROR"
                )
                return False

        gmail_service = build("gmail", "v1", credentials=creds)

        # Send email to each recipient
        for recipient in recipients:
            message = (
                f"To: {recipient}\r\n"
                f"Subject: {subject}\r\n"
                f"\r\n"
                f"{email_body}"
            )
            raw_message = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            gmail_service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()

        logger.info("[NotificationCenter] Pending prescription email sent successfully to %s | inquiry_id=%s", recipients, inquiry_id)
        return True

    except Exception as e:
        logger.exception("[NotificationCenter] Failed to send pending prescription notification: %s", e)
        send_production_alert(
            subject=f"Pending Prescription Notification Delivery Failure (Inquiry #{inquiry_id})",
            body_or_error=e,
            context={"inquiry_id": inquiry_id, "comes_from": comes_from},
            level="ERROR"
        )
        return False