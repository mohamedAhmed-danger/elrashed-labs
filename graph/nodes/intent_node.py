import logging
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from graph.prompts.intent_prompt import INTENT_SYSTEM_PROMPT
from graph.state import AgentState
from llm.llm import get_gemini
from schemas.intent import IntentResponse, IntentType
from services.messaging.client_service import ClientService
from utils.history_utils import get_chat_history
from utils.llm_utils import extract_token_usage

logger = logging.getLogger(__name__)


def intent_node(state: AgentState) -> Dict[str, Any]:
    """
    Classify the user's intent and generate refined queries.

    Flow:
        Get Context
        → Load History
        → Build Messages (static system prompt + context in HumanMessage)
        → Gemini (structured output)
        → Return Intent
    """

    # 1. Get conversation context
    user_message = state.get("user_message", "")
    summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    # 2. Load recent conversation history
    client_service = ClientService(
        platform_id=state.get("platform_id"),
        page_id=state.get("page_id"),
        sender_id=state.get("sender_id"),
    )

    history, formatted_history = get_chat_history(
        state,
        client_service,
    )

    logger.info(
        "[INTENT] Processing message | history=%d",
        len(history),
    )

    # 3. Build the LLM messages
    # System prompt is static (better for caching);
    # the changing context goes in the HumanMessage.
    context_block = f"""Summary:
{summary or "None"}

Last Bot Message:
{last_bot_message or "None"}

Recent Exchanges:
{formatted_history or "None"}"""

    messages = [
        SystemMessage(content=INTENT_SYSTEM_PROMPT),
        HumanMessage(
            content=f"{context_block}\n\nCURRENT USER MESSAGE:\n{user_message}"
        ),
    ]

    # 4. Classify intent with structured output
    try:
        llm = get_gemini()

        structured_llm = llm.with_structured_output(
            IntentResponse,
            include_raw=True,
        )

        result = structured_llm.invoke(messages)
        logger.debug("RAW GEMINI RESPONSE: %s", result.get("raw"))

        parsed: Optional[IntentResponse] = result.get("parsed")

        if parsed is None:
            raise ValueError(
                "Gemini returned no parsed IntentResponse."
            )

        usage = extract_token_usage(result.get("raw"))

        logger.info(
            "[INTENT] Classified as: %s",
            parsed.intent.value,
        )

        # 5. Return state updates
        return {
            "intent": parsed.intent,
            "refined_queries": parsed.refined_queries,
            "is_bundle_query": parsed.is_bundle_query,
            "intent_usage": usage,
        }

    except Exception as exc:
        logger.exception(
            "[INTENT] Classification failed: %s",
            exc,
        )

        # Safe fallback when intent classification fails
        return {
            "intent": IntentType.DIRECT,
            "refined_queries": [],
            "is_bundle_query": False,
            "intent_usage": None,
        }