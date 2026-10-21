import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage

from graph.prompts.results_prompt import RESULTS_SYSTEM_PROMPT
from graph.state import AgentState
from llm.llm import get_gemini
from services.domain.laboratory_service import LaboratoryService
from services.domain.result_service import ResultService
from services.messaging.client_service import ClientService
from utils.contact_resolver import resolve_user_identity
from utils.history_utils import get_chat_history
from utils.llm_utils import extract_token_usage
from utils.request_profiler import RequestProfiler
from utils.trace_logger import trace_logger

logger = logging.getLogger(__name__)


def _static_reply(phone_numbers: list[str]) -> str:
    """Fallback if the LLM fails."""
    contact_text = (
        "يمكنك أيضًا التواصل مع فريق خدمة العملاء عبر الرقم التالي:\n"
        f"📞 {', '.join(phone_numbers)}"
        if phone_numbers
        else ""
    )
    return (
        "✅ تم تسجيل طلبك للاستعلام عن نتيجة التحاليل.\n\n"
        "سيتواصل معك فريق خدمة العملاء فور اعتماد النتيجة من المعمل.\n\n"
        f"{contact_text}"
    ).strip()


def _to_text(content) -> str:
    """Gemini may return a list of parts instead of a string."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            p if isinstance(p, str) else p.get("text", "") for p in content
        ).strip()
    return str(content).strip()


def result_node(state: AgentState) -> dict:
    """
    Handle lab results inquiries.
    Saves a result request (user identity + lab), then replies using an LLM.
    Falls back to a static reply if the LLM fails.
    """
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")
    user_message = state.get("user_message") or ""
    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    trace_logger.step(
        "Lab Results Node Entry",
        input_data={"user_message": user_message, "sender_id": sender_id},
    )

    # 1. Save the request (never break the reply if this fails)
    created = None
    try:
        identity = state.get("user_identity") or resolve_user_identity(page_id, platform_id, sender_id)
        _, created = ResultService.create_request(
            user_identity=identity,
            laboratory_id=state.get("laboratory_id"),
        )
        logger.info(
            "Result request %s for %s",
            "created" if created else "already pending",
            identity,
        )
    except Exception:
        logger.exception("Failed to save result request")

    # 2. Facts
    support_phone = LaboratoryService.get_support_phone(state.get("laboratory_id"))
    phone_numbers = [support_phone] if support_phone else []

    # 3. History for context
    try:
        client_service = ClientService(
            platform_id=platform_id, page_id=page_id, sender_id=sender_id
        )
        _, formatted_history = get_chat_history(state, client_service)
    except Exception:
        logger.exception("Failed to load history")
        formatted_history = ""

    # 4. LLM reply
    usage = None
    start = time.perf_counter()
    try:
        status = "already_pending" if created is False else "new"
        human = f"""FACTS
request_status: {status}
branch_phones: {', '.join(phone_numbers) if phone_numbers else 'None'}

Summary:
{current_summary or 'None'}

Last Bot Message:
{last_bot_message or 'None'}

Recent Exchanges:
{formatted_history or 'None'}

CURRENT USER MESSAGE:
{user_message}"""

        llm = get_gemini()
        raw = llm.invoke([
            SystemMessage(content=RESULTS_SYSTEM_PROMPT),
            HumanMessage(content=human),
        ])
        result_text = _to_text(raw.content)
        usage = extract_token_usage(raw)
        if not result_text:
            raise ValueError("Empty LLM reply")
        reply_type = "llm_lab_results"
    except Exception:
        logger.exception("Results LLM failed, using static fallback")
        result_text = _static_reply(phone_numbers)
        reply_type = "static_lab_results_fallback"
    finally:
        RequestProfiler.record_stage("final_llm", time.perf_counter() - start)

    trace_logger.log_output({
        "reply_type": reply_type,
        "reply_length": len(result_text),
    })

    return {
        "response": result_text,
        "summary": current_summary,
        "last_bot_message": result_text,
        "result_usage": usage,
    }