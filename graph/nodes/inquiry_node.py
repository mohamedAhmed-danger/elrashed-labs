import logging

from langchain_core.messages import HumanMessage, SystemMessage

from graph.prompts.inquiry_prompt import INQUIRY_SYSTEM_PROMPT
from graph.state import AgentState
from llm.llm import get_gemini
from schemas.inquiry import InquiryResponse
from services.messaging.client_service import ClientService
from services.domain.laboratory_service import LaboratoryService
from services.domain.bundle_service import BundleService
from utils.history_utils import get_chat_history
from utils.llm_utils import extract_token_usage

logger = logging.getLogger(__name__)

OFFER_FLYER_MARKER = "LAB OFFER / BUNDLE FLYER"


def inquiry_node(state: AgentState) -> dict:
    """
    Handle laboratory inquiry messages using RAG context.

    Flow:
        Get Context
        → Load Lab & Bundle Info from DB
        → Load History + RAG
        → Build Prompt
        → Structured Gemini
        → Return State
    """

    # 1. Get conversation context
    user_message = state.get("user_message", "")
    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    rag_context = state.get("rag_context") or ""

    # Offer flyers must always load the bundles context, even if the classifier missed it.
    is_bundle_query = (
        state.get("is_bundle_query", False)
        or OFFER_FLYER_MARKER in user_message
    )

    platform_id = state.get("platform_id")
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")

    # 2. Fetch dynamic Lab Info & Bundles Context from DB
    lab_name, lab_location, lab_desc = LaboratoryService.get_current_lab_info()

    if is_bundle_query:
        bundles_context = BundleService.get_bundles_formatted_context()
    else:
        bundles_context = "(No bundle context required for this request.)"

    # 3. Load recent conversation history
    client_service = ClientService(
        platform_id=platform_id,
        page_id=page_id,
        sender_id=sender_id,
    )

    history, recent_history = get_chat_history(
        state,
        client_service,
    )

    logger.info(
        "[INQUIRY] Processing message | history=%d | has_rag=%s | is_bundle=%s",
        len(history),
        bool(rag_context),
        is_bundle_query,
    )

    # 4. Build the LLM prompt with dynamic Lab details & Bundles
    system_prompt = f"""
{INQUIRY_SYSTEM_PROMPT}

====================
LABORATORY INFORMATION
====================
Name: {lab_name}
Location: {lab_location}
Description: {lab_desc}

====================
AVAILABLE BUNDLES
====================
{bundles_context}

====================
RETRIEVED KNOWLEDGE
====================
{rag_context or "(No laboratory information retrieved.)"}

====================
MEMORY & CONTEXT
====================
Summary: {current_summary or "None"}

Last Bot Message: {last_bot_message or "None"}

Recent History:
{recent_history or "None"}
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    # 5. Generate structured inquiry response
    try:
        llm = get_gemini()

        structured_llm = llm.with_structured_output(
            InquiryResponse,
            include_raw=True,
        )

        result = structured_llm.invoke(messages)

        parsed = result.get("parsed")

        if parsed is None:
            raise ValueError(
                "Gemini returned no parsed InquiryResponse."
            )

        tokens = extract_token_usage(
            result.get("raw")
        ) or {}

        # 6. Return updated graph state
        return {
            "response": parsed.reply,
            "summary": parsed.summary,
            "last_bot_message": parsed.reply,
            "inquiry_usage": tokens,
        }

    except Exception as exc:
        logger.exception(
            "[INQUIRY] Failed to generate response: %s",
            exc,
        )

        fallback = (
            "عذراً، حدث خطأ مؤقت أثناء معالجة الاستفسار. "
            "يرجى المحاولة مرة أخرى."
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "inquiry_usage": None,
        }