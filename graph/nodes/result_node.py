import logging
from config import Config
from graph.state import AgentState
from utils.trace_logger import trace_logger
from utils.request_profiler import RequestProfiler

logger = logging.getLogger(__name__)


def result_node(state: AgentState) -> dict:
    """
    Handle lab results inquiries with direct instructions and customer service contact.
    Static response (No LLM invocation required).
    """
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")
    user_message = state.get("user_message") or ""
    current_summary = state.get("summary") or ""

    RequestProfiler.record_stage("final_llm", 0.0)  # Static text, zero LLM duration

    trace_logger.step(
        "Lab Results Node Entry",
        input_data={
            "user_message": user_message,
            "sender_id": sender_id,
        },
    )

    logger.info(
        "\n" + "-"*60 + "\n"
        "📄 [LAB RESULTS NODE START]\n"
        "   Sender ID:    %s\n"
        "   User Message: %s\n"
        + "-"*60,
        sender_id,
        user_message,
    )

    # جلب رقم خدمة العملاء من Config أو استخدام الرقم المباشر
    phone_number = getattr(Config, "CUSTOMER_SERVICE_PHONE", "20 100 644 6508")

    result_text = f"""
📋 للاستعلام عن نتيجة التحاليل والحصول عليها:

يرجى التواصل مباشرة مع فريق خدمة العملاء والدعم الفني عبر الرقم التالي:
📞 {phone_number}

وسيقوم الفريق بمساعدتك وإرسال النتيجة فور اعتمادها من المعمل.
""".strip()

    trace_logger.log_output({
        "reply_type": "static_lab_results_instructions",
        "reply_length": len(result_text),
    })

    return {
        "response": result_text,
        "summary": current_summary,
        "last_bot_message": result_text,
    }