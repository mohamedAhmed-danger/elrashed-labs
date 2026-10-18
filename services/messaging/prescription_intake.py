import logging
import os
import uuid
from typing import Optional, Tuple

from services.messaging.ocr_service import analyze_prescription_image
from services.domain.inquiry_service import InquiryService
from utils.usage_calculator import calc_total_usage
from services.shared.subscription_consumer import consume_subscription
from models.models import Status
from notification_center import send_production_alert, send_pending_prescription_email
from utils.trace_logger import trace_logger

logger = logging.getLogger(__name__)

# ── Image validity check (magic bytes) ──────────────────────────────────────
# بنتأكد إن الـ bytes اللي وصلتنا فعلاً صورة (JPEG/PNG/WEBP/GIF) مش رد خطأ أو صفحة HTML
# كل signature هنا مرتبطة بامتداد الملف الصحيح، عشان نحفظ الملف بامتداده الحقيقي
# بدل ما نفترض .jpg دايمًا (ده كان بيسبب مشكلة تحديد mime type غلط لصور GIF لاحقًا).
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),        # JPEG
    (b"\x89PNG\r\n\x1a\n", "png"),   # PNG
    (b"GIF87a", "gif"),              # GIF
    (b"GIF89a", "gif"),              # GIF
)


def _detect_image_extension(image_bytes: bytes) -> Optional[str]:
    """Return the correct file extension based on magic bytes, or None if unrecognized."""
    for signature, extension in _IMAGE_SIGNATURES:
        if image_bytes.startswith(signature):
            return extension
    # WEBP needs a two-part check: RIFF header AND "WEBP" at bytes 8-16,
    # otherwise any other RIFF-based format (e.g. WAV, AVI) would false-match.
    if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 16 and b"WEBP" in image_bytes[8:16]:
        return "webp"
    return None


def _looks_like_valid_image(image_bytes: bytes) -> bool:
    """Verifies image bytes match a known image magic byte signature."""
    if not image_bytes or len(image_bytes) < 16:
        return False
    return _detect_image_extension(image_bytes) is not None


def _save_prescription_image(image_bytes: bytes, sender_id: str) -> Tuple[str, str]:
    """Writes image bytes to disk with their real extension and returns (filename, absolute_path)."""
    # Navigate up 3 levels: services/messaging/prescription_intake.py -> services/messaging -> services -> project root
    project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    uploads_dir = os.path.join(project_dir, "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    extension = _detect_image_extension(image_bytes) or "jpg"
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(uploads_dir, filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    logger.info(
        "[PRESCRIPTION INTAKE] Saved Image: %s | sender_id=%s",
        image_path, sender_id,
    )
    trace_logger.step(
        "Prescription Image Ingested",
        input_data={
            "sender_id": sender_id,
            "image_path": image_path,
            "bytes_len": len(image_bytes),
        },
    )
    return filename, image_path


def _handle_non_prescription(message, ocr_usage: dict) -> dict:
    """Handles images classified as non-prescription/spam."""
    agent_text = "[Image classified as spam or not a valid prescription]"
    trace_logger.step(
        "Prescription Decision: Non-Prescription",
        input_data={"is_prescription": False, "agent_text": agent_text},
    )
    return {"mode": "agent", "text": agent_text, "ocr_usage": ocr_usage}


def _handle_offer_or_bundle(ocr_result, ocr_usage: dict) -> dict:
    """Routes lab offer/bundle flyers to the agent with an explicit label (name + price only)."""
    offers = [o for o in ocr_result.offers if o.name and o.name.strip()]

    if offers:
        offers_lines = "\n".join(
            f"- {o.name.strip()} | Price on flyer: {o.price.strip() if o.price else 'not shown'}"
            for o in offers
        )
    else:
        offers_lines = "- (offer name could not be read)"

    agent_text = (
        "[IMAGE TYPE: LAB OFFER / BUNDLE FLYER - not a doctor's prescription]\n"
        f"Offers on the flyer:\n{offers_lines}\n"
        "The customer sent this flyer and is asking about this offer. Look it up by name in the "
        "lab's own data and explain its details, included tests, current price, and preparation. "
        "If the lab's data doesn't have it or the price differs, say so; do not invent contents or prices."
    )
    trace_logger.step(
        "Prescription Decision: Offer/Bundle Routed to Agent",
        input_data={
            "status": "OFFER_BUNDLE",
            "offers": [{"name": o.name, "price": o.price} for o in offers],
        },
    )
    return {"mode": "agent", "text": agent_text, "ocr_usage": ocr_usage}


def _determine_prescription_pending(ocr_result) -> bool:
    """Returns True if prescription requires manual doctor review due to low confidence."""
    if not ocr_result.tests:
        return True
    return any(test.confidence < 0.85 for test in ocr_result.tests)


def _save_inquiry_record(message, page, filename: str, ocr_result, pending: bool) -> float:
    """Persists prescription inquiry in DB and returns min_confidence score."""
    inquiry_service = InquiryService()
    min_confidence = min((t.confidence for t in ocr_result.tests), default=0.0)
    services_mentioned = ", ".join(t.name for t in ocr_result.tests) if ocr_result.tests else None
    comes_from = f"{message.platform_name}:{message.sender_id}:{message.page_id}"

    inquiry_result = inquiry_service.save_inquiry(
        laboratory_id=page.laboratory_id if page else 1,
        phone_number="",
        comes_from=comes_from,
        prescription_img=filename,
        ocr_extracted_text=ocr_result.extracted_text,
        confidence_score=min_confidence,
        services_mentioned=services_mentioned,
        status=Status.PENDING if pending else Status.REVIEWED,
    )

    logger.info(
        "[PRESCRIPTION INQUIRY SAVED] Inquiry ID: %s | Status: %s",
        inquiry_result.inquiry.id if inquiry_result and inquiry_result.inquiry else "None",
        Status.PENDING.value if pending else Status.REVIEWED.value,
    )
    trace_logger.log_db_operation(
        "save_inquiry",
        "inquiries",
        success=True,
        extra={"status": Status.PENDING.value if pending else Status.REVIEWED.value, "min_confidence": min_confidence},
    )

    # Send email alert for pending prescriptions (best-effort, won't block main flow)
    if pending and inquiry_result and inquiry_result.inquiry:
        try:
            send_pending_prescription_email(
                inquiry_id=inquiry_result.inquiry.id,
                comes_from=comes_from,
                confidence_score=min_confidence,
                extracted_tests=services_mentioned or "",
                ocr_extracted_text=ocr_result.extracted_text or "",
            )
        except Exception:
            logger.exception(
                "[PRESCRIPTION INTAKE] Pending prescription email failed | inquiry_id=%s",
                inquiry_result.inquiry.id,
            )

    return min_confidence


def _handle_pending_review(message, ocr_usage: dict, min_confidence: float) -> dict:
    """Handles low-confidence flow routed to agent."""
    agent_text = (
        f"[Prescription image received. Low OCR confidence ({min_confidence:.2f}). "
        f"Case has been queued for manual doctor review.]"
    )
    trace_logger.step(
        "Prescription Decision: Pending Review",
        input_data={"status": "PENDING", "min_confidence": min_confidence, "agent_text": agent_text},
    )
    return {"mode": "agent", "text": agent_text, "ocr_usage": ocr_usage}


def _handle_reviewed_prescription(ocr_result, ocr_usage: dict) -> dict:
    """Builds agent query text for high-confidence prescription tests."""
    extracted_tests = [t.name for t in ocr_result.tests if t.name]
    tests_list = ", ".join(extracted_tests)
    agent_text = (
        f"[Prescription OCR Extracted Tests]: {tests_list}\n"
        f"Please provide full details, preparations needed, and prices for these tests."
    )
    trace_logger.step(
        "Prescription Decision: Routed to Agent",
        input_data={"status": "REVIEWED", "tests_count": len(extracted_tests), "tests": extracted_tests},
    )
    return {"mode": "agent", "text": agent_text, "ocr_usage": ocr_usage}


def _image_result(status: str, ocr_result=None) -> dict:
    """status: "valid" | "pending" | "spam" | "offer"."""
    tests = []
    offers = []
    if ocr_result:
        tests = [t.name for t in ocr_result.tests if t.name]
        if status == "offer":
            offers = [
                {"name": o.name.strip(), "price": (o.price or "").strip() or None}
                for o in ocr_result.offers
                if o.name and o.name.strip()
            ]
    return {"status": status, "tests": tests, "offers": offers}


def extract_prescription_payload(image_bytes: bytes, message, page) -> dict:
    """
    Ingests prescription image bytes, performs OCR analysis, deducts 2 subscription units,
    and returns {"mode": "agent", "text": "...", "ocr_usage": {...}} for debounce buffer.
    """
    try:
        if not _looks_like_valid_image(image_bytes):
            logger.error(
                "[PRESCRIPTION INTAKE] Received invalid/corrupt image bytes (len=%s) | sender_id=%s",
                len(image_bytes) if image_bytes else 0, message.sender_id,
            )
            trace_logger.step(
                "Prescription Intake Rejected: Invalid Image Bytes",
                input_data={"sender_id": message.sender_id, "bytes_len": len(image_bytes) if image_bytes else 0},
            )
            send_production_alert(
                subject="Prescription Intake: Corrupt/Empty Image Received",
                body_or_error="Downloaded media did not match any known image signature.",
                context={
                    "sender_id": message.sender_id,
                    "page_id": message.page_id,
                    "platform": message.platform_name,
                    "bytes_len": len(image_bytes) if image_bytes else 0,
                },
            )
            error_reply = "عذرًا، لم نتمكن من استقبال الصورة بشكل صحيح. يرجى محاولة إرسالها مرة أخرى."
            return {"mode": "immediate", "reply": error_reply, "pdf": None}

        filename, image_path = _save_prescription_image(image_bytes, message.sender_id)
        ocr_result, ocr_usage = analyze_prescription_image(image_path)

        # Single shared deduction point for all image messages: deduct 2 units immediately after OCR
        usage = calc_total_usage({}, ocr_usage=ocr_usage) if ocr_usage else None
        if usage:
            from utils.usage_calculator import check_and_alert_high_token_usage
            check_and_alert_high_token_usage(
                usage,
                context={
                    "sender_id": message.sender_id,
                    "platform": message.platform_name or str(message.platform_id),
                    "page_id": message.page_id,
                    "flow": "prescription_ocr_intake",
                },
                threshold=40000,
            )
        consume_subscription(message, usage=usage, count=2)

        logger.info(
            "[PRESCRIPTION OCR RESULT]\n"
            "   Sender ID:        %s\n"
            "   Is Prescription:  %s\n"
            "   Is Offer/Bundle:  %s\n"
            "   Offers Found:     %s\n"
            "   Tests Found:      %s\n"
            "   Tokens Used:      %s",
            message.sender_id,
            ocr_result.is_prescription,
            ocr_result.is_offer_or_bundle,
            [f"{o.name} - {o.price}" for o in ocr_result.offers],
            [f"{t.name} ({t.confidence:.2f})" for t in ocr_result.tests],
            ocr_usage.get("total_tokens", 0) if ocr_usage else 0,
        )

        try:
            tests_list = getattr(ocr_result, "tests", [])
            avg_conf = (sum([t.confidence for t in tests_list]) / max(len(tests_list), 1) * 100) if tests_list else 0.0

            if not ocr_result.is_prescription:
                summary_status = "NON_PRESCRIPTION"
            elif ocr_result.is_offer_or_bundle:
                summary_status = "OFFER_BUNDLE"
            else:
                summary_status = "SUCCESS"

            if ocr_result.is_offer_or_bundle:
                recognized_services = [f"{o.name} - {o.price or 'no price'}" for o in ocr_result.offers]
            else:
                recognized_services = [f"{t.name} ({t.confidence:.2f})" for t in tests_list]

            ocr_summary_data = {
                "status": summary_status,
                "extracted_text": getattr(ocr_result, "extracted_text", ""),
                "recognized_services": recognized_services,
                "confidence_score": round(avg_conf, 1),
            }
            trace_logger.log_production_summary(
                sender_id=message.sender_id,
                platform_name=message.platform_name or str(message.platform_id),
                page_id=message.page_id,
                user_message="[Prescription Image Attachment]",
                detected_intent="prescription_ocr_intake",
                usage=usage,
                ocr_result=ocr_summary_data,
            )
        except Exception as summary_err:
            logger.exception("[prescription_intake] Production summary logging failed: %s", summary_err)

        # Step A: Classification check (not a prescription / spam)
        if not ocr_result.is_prescription:
            payload = _handle_non_prescription(message, ocr_usage)
            payload["image_result"] = _image_result("spam")
            return payload

        # Step B: Lab offer / bundle flyer -> straight to agent with a clear label.
        # Skips inquiry persistence, confidence check and the doctor-review email on purpose.
        if ocr_result.is_offer_or_bundle:
            payload = _handle_offer_or_bundle(ocr_result, ocr_usage)
            payload["image_result"] = _image_result("offer", ocr_result)
            return payload

        # Step C: Standard prescription: confidence check & persistence
        pending = _determine_prescription_pending(ocr_result)
        min_confidence = _save_inquiry_record(message, page, filename, ocr_result, pending)

        if pending:
            payload = _handle_pending_review(message, ocr_usage, min_confidence)
            payload["image_result"] = _image_result("pending")
            return payload

        # Step D: Reviewed flow -> ALL tests >= 0.85
        payload = _handle_reviewed_prescription(ocr_result, ocr_usage)
        payload["image_result"] = _image_result("valid", ocr_result)
        return payload

    except Exception as e:
        logger.exception(
            "[extract_prescription_payload] Error | sender_id=%s", message.sender_id,
        )
        trace_logger.error(f"extract_prescription_payload error: {e}")
        send_production_alert(
            subject="Prescription Intake / OCR Failure",
            body_or_error=e,
            context={
                "sender_id": message.sender_id,
                "page_id": message.page_id,
                "platform": message.platform_name,
            },
        )
        return {"mode": "immediate", "reply": "عذرًا، حدث خطأ أثناء معالجة الصورة المرفقة. يرجى المحاولة مرة أخرى.", "pdf": None}