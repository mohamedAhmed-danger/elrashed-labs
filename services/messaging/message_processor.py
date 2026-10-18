import logging
import time

from graph.graph import get_agent_graph
from graph.response import AgentResponse
from notification_center import send_production_alert, send_visit_confirmation_email
from schemas.incoming_message import IncomingMessage
from services.messaging.client_service import ClientService
from services.domain.page_service import PageService
from utils.history_utils import format_chat_history
from utils.request_profiler import RequestProfiler
from utils.usage_calculator import calc_total_usage, check_and_alert_high_token_usage

logger = logging.getLogger(__name__)

FALLBACK_REPLY = "عذرًا، حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى بعد لحظات."


def run_agent(
    message: IncomingMessage,
    ocr_usage: dict | None = None,
    laboratory_id: int | None = None,
) -> tuple[str, bytes | None, str | None]:
    """
    يشغّل الـ agent graph على رسالة واحدة ويرجّع (الرد، PDF الحجز، رقم المرجع).

    laboratory_id: لو المستدعي عارفه (webhook_service) بيتبعت عشان نوفر استعلام.
    لو مش متبعت، بنجيبه من الـ page.
    """
    t_start = time.perf_counter()
    t0 = time.perf_counter()
    client_service = ClientService(
        platform_id=message.platform_id,
        page_id=message.page_id,
        sender_id=message.sender_id,
    )
    client = client_service.get_or_create_client()
    if laboratory_id is None:
        laboratory_id = _lookup_laboratory_id(message)
    lookup_duration = time.perf_counter() - t0
    RequestProfiler.record_stage("client_lookup", lookup_duration)
    RequestProfiler.record_external("mysql_client_lookup", lookup_duration)

    t0 = time.perf_counter()
    history_rows = client_service.get_chat_history(limit=8)
    RequestProfiler.record_stage("chat_history_load", time.perf_counter() - t0)

    _log_incoming(message, client, history_rows)
    state = _build_state(message, client, laboratory_id, history_rows)

    # 1) تشغيل الـ graph: لو فشل نرجّع رد اعتذار
    try:
        result = get_agent_graph().invoke(state)
        response_obj = AgentResponse.from_result(result)
    except Exception as e:
        logger.exception(
            "[run_agent] Graph execution failed | sender_id=%s platform=%s",
            message.sender_id, message.platform_name,
        )
        send_production_alert(
            subject="Agent Graph Execution Failure",
            body_or_error=e,
            context={
                "sender_id": message.sender_id,
                "platform": message.platform_name,
                "page_id": message.page_id,
            },
        )
        return FALLBACK_REPLY, None, None

    # 2) من هنا وطالع كل خطوة best-effort: فشلها ميضيّعش الرد على العميل
    t0 = time.perf_counter()
    usage = _record_usage(message, result, ocr_usage)
    _save_exchange(client_service, client, message, result, response_obj)
    RequestProfiler.record_stage("db_save", time.perf_counter() - t0)

    _send_booking_email(result)

    booking_ref = result.get("booking_reference") or result.get("visit_reference")
    duration = time.perf_counter() - t_start
    _log_completed(message, result, response_obj, usage, booking_ref, duration=duration)

    return response_obj.response, result.get("booking_pdf"), booking_ref


# ── Steps ─────────────────────────────────────────────────────────────────────

def _lookup_laboratory_id(message: IncomingMessage) -> int | None:
    page = PageService.get_page_by_page_and_platform(
        page_id=message.page_id,
        platform_id=message.platform_id,
    )
    return page.laboratory_id if page else None


def _build_state(message: IncomingMessage, client, laboratory_id, history_rows) -> dict:
    """يبني الـ initial state اللي هيتبعت للـ agent graph."""
    return {
        "page_id":           message.page_id,
        "sender_id":         message.sender_id,
        "platform_id":       message.platform_id,
        "platform_name":     message.platform_name or str(message.platform_id),
        "user_message":      message.text or "",
        "summary":           client.summary or "",
        "last_bot_message":  client.last_bot_reply or "",
        "chat_history":      history_rows or [],
        "laboratory_id":     laboratory_id,

        "intent":            None,
        "response":          None,
        "intent_usage":      None,
        "retrieval_usage":   None,
        "lab_info_usage":    None,
        "booking_usage":     None,
        "complaint_usage":   None,
        "direct_usage":      None,
        "inquiry_usage":     None,
        "booking_reference": None,
        "booking_saved":     None,
        "booking_data":      None,
        "complaint_saved":   None,
        "inquiry_saved":     None,
    }


def _record_usage(message: IncomingMessage, result: dict, ocr_usage: dict | None) -> dict | None:
    """يحسب الاستهلاك للتسجيل ويتحقق من تجاوز حد 40,000 توكن لإرسال تنبيه."""
    try:
        usage = calc_total_usage(result, ocr_usage=ocr_usage)
        if usage:
            check_and_alert_high_token_usage(
                usage,
                context={
                    "sender_id": message.sender_id,
                    "platform": message.platform_name or str(message.platform_id),
                    "page_id": message.page_id,
                    "user_message": message.text or "",
                },
                threshold=40000,
            )
        return usage
    except Exception as e:
        logger.exception(
            "[run_agent] Usage calculation failed | sender_id=%s", message.sender_id
        )
        return None


def _save_exchange(client_service, client, message, result, response_obj) -> None:
    """حفظ الرسالة والرد (نقطة الحفظ الوحيدة لكل الـ intents)."""
    try:
        client_service.save_chat_exchange(
            user_message=message.text or "",
            bot_reply=response_obj.response,
            summary=result.get("summary") or client.summary,
        )
    except Exception:
        logger.exception(
            "[run_agent] save_chat_exchange failed | sender_id=%s", message.sender_id
        )


def _send_booking_email(result: dict) -> None:
    """إيميل تأكيد الحجز (synchronous: بيتبعت قبل ما الرد يرجع)."""
    booking = result.get("booking_data")
    if not (result.get("booking_saved") and booking):
        return

    reference_id = booking.get("reference_id", "")
    try:
        send_visit_confirmation_email(
            reference_id=reference_id,
            name=booking.get("name", ""),
            phone=booking.get("phone", ""),
            address=booking.get("address", ""),
            details=booking.get("details", ""),
            date=booking.get("date", ""),
            time=booking.get("time", ""),
            comes_from=booking.get("comes_from", ""),
        )
        logger.info("[run_agent] Booking confirmation email sent | ref=%s", reference_id)
    except Exception:
        logger.exception("[run_agent] Booking email failed | ref=%s", reference_id)


# ── Logging ───────────────────────────────────────────────────────────────────
# INFO: بيانات تشغيل بدون محتوى العميل. DEBUG: التفاصيل الكاملة (محتوى + history).

def _log_incoming(message: IncomingMessage, client, history_rows) -> None:
    logger.info(
        "[run_agent] Incoming | sender_id=%s platform=%s page_id=%s text_len=%d history_turns=%d",
        message.sender_id,
        message.platform_name or str(message.platform_id),
        message.page_id,
        len(message.text or ""),
        len(history_rows),
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "[run_agent] Context | text=%s | summary=%s | last_bot_reply=%s | history=\n%s",
            message.text or "(empty)",
            client.summary or "(none)",
            client.last_bot_reply or "(none)",
            format_chat_history(history_rows) or "(none)",
        )


def _log_completed(
    message: IncomingMessage,
    result: dict,
    response_obj,
    usage: dict | None,
    booking_ref: str | None,
    duration: float = 0.0,
    ocr_result: dict | None = None,
) -> None:
    logger.info(
        "[run_agent] Completed | sender_id=%s intent=%s reply_len=%d has_booking_pdf=%s "
        "reference=%s tokens=%s cost_usd=%s",
        message.sender_id,
        result.get("intent"),
        len(response_obj.response or ""),
        bool(result.get("booking_pdf")),
        booking_ref or "None",
        usage["total_tokens"] if usage else "n/a",
        f"{usage['total_cost_usd']:.6f}" if usage else "n/a",
    )
    if usage and logger.isEnabledFor(logging.DEBUG):
        for node, u in usage["breakdown"].items():
            logger.debug(
                "[run_agent] Usage | %-18s in=%d out=%d cost=$%.6f",
                node, u["input"], u["output"], u["cost_usd"],
            )
        logger.debug("[run_agent] Reply | %s", response_obj.response)

    # 📊 Emit clean production summary box & token table
    try:
        from utils.trace_logger import trace_logger
        trace_logger.log_production_summary(
            sender_id=message.sender_id,
            platform_name=message.platform_name or str(message.platform_id),
            page_id=message.page_id,
            user_message=message.text or "",
            detected_intent=result.get("intent"),
            chat_summary=result.get("summary"),
            bot_response=response_obj.response,
            usage=usage,
            ocr_result=ocr_result,
            duration=duration,
        )
    except Exception as exc:
        logger.exception("[run_agent] Production summary formatting failed: %s", exc)