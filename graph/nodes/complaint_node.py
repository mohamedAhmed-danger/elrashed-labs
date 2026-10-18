import logging

from langchain_core.messages import HumanMessage, SystemMessage

from graph.prompts.complaint_prompt import COMPLAINT_SYSTEM_PROMPT
from graph.state import AgentState
from graph.tools.complaint_tool import save_complaint_tool
from llm.llm import get_gemini
from schemas.complaint import ComplaintResponse
from services.messaging.client_service import ClientService
from utils.history_utils import get_chat_history
from utils.llm_utils import extract_token_usage
from utils.text_utils import detect_language_fallback, get_platform_name

logger = logging.getLogger(__name__)


def complaint_node(state: AgentState) -> dict:
    """
    Handle customer complaints.

    Flow:
        Get Context
        → Load History
        → Build Prompt
        → Gemini Tool Calling
        → ComplaintResponse / Save Complaint
        → Return State
    """

    # 1. Get conversation context
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state.get("user_message", "")
    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""

    # 2. Load recent conversation history
    client_service = ClientService(
        platform_id=platform_id,
        page_id=page_id,
        sender_id=sender_id,
    )

    history, recent_history = get_chat_history(
        state,
        client_service,
    )

    # 3. Build the LLM prompt
    system_prompt = f"""
{COMPLAINT_SYSTEM_PROMPT}

====================
ALREADY COLLECTED
====================

Summary:
{current_summary or "(None)"}

Last Bot Message:
{last_bot_message or "(None)"}

====================
RECENT CONVERSATION
====================

{recent_history or "(None)"}
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    # 4. Ask Gemini to handle the complaint
    try:
        llm = get_gemini().bind_tools(
            [save_complaint_tool, ComplaintResponse],
            tool_choice="any",
        )

        response = llm.invoke(messages)
        complaint_usage = extract_token_usage(response) or {}

    except Exception:
        logger.exception(
            "[COMPLAINT] LLM error | sender_id=%s",
            sender_id,
        )

        fallback = detect_language_fallback(
            user_message,
            arabic=(
                   f"عذرًا، حدث خطأ مؤقت أثناء معالجة طلبك ⚠️\n\n"
                   f"يرجى المحاولة مرة أخرى بعد قليل، أو يمكنك التواصل مباشرة مع خدمة عملاء معامل الصدارة لمساعدتك فوراً عبر الرقم:\n"
                   f"📞 **01006446508**\n\n"
                   f"نحن في خدمتك دائمًا ✨"
                   ),
            default=(
                    f"Apologies, a temporary error occurred while processing your request ⚠️\n\n"
                    f"Please try again in a moment, or contact El Sadara Labs customer service directly for assistance at:\n"
                    f"📞 **01006446508**\n\n"
                    f"We are always happy to help! ✨"
                    ),
              )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "complaint_saved": False,
            "complaint_usage": None,
        }

    # 5. Handle Gemini tool call
    if not response.tool_calls:
        reply = response.content or "ممكن توضح شكوتك أكتر؟"

        return {
            "response": reply,
            "summary": current_summary,
            "last_bot_message": reply,
            "complaint_saved": False,
            "complaint_usage": complaint_usage,
        }

    tool_call = response.tool_calls[0]
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})

    # Normal complaint conversation
    if tool_name == "ComplaintResponse":
        reply = tool_args.get("reply", "")
        updated_summary = tool_args.get(
            "summary",
            current_summary,
        )

        return {
            "response": reply,
            "summary": updated_summary,
            "last_bot_message": reply,
            "complaint_saved": False,
            "complaint_usage": complaint_usage,
        }

    # Save complaint
    if tool_name == "save_complaint_tool":
        tool_args["comes_from"] = get_platform_name(platform_id)

        try:
            result = save_complaint_tool.invoke(tool_args)

        except Exception:
            logger.exception(
                "[COMPLAINT] Tool error | sender_id=%s",
                sender_id,
            )

            reply = detect_language_fallback(
                user_message,
                arabic="حدث خطأ أثناء تسجيل الشكوى. حاول مرة أخرى.",
                default="An error occurred while saving your complaint.",
            )

            return {
                "response": reply,
                "summary": current_summary,
                "last_bot_message": reply,
                "complaint_saved": False,
                "complaint_usage": complaint_usage,
            }

        if result.success:
            reply = detect_language_fallback(
                user_message,
                arabic=(
                    "تم تسجيل شكواك بنجاح ✅\n"
                    "وسيتواصل معك فريقنا في أقرب وقت."
                ),
                default=(
                    "Your complaint has been successfully "
                    "registered. Our team will contact you soon."
                ),
            )

            updated_summary = (
            f"{current_summary}\n\n"
            f"--- COMPLAINT STATUS UPDATE ---\n"
            f"✅ Complaint submitted successfully for phone: {tool_args.get('phone')}.\n"
            f"Complaint Text: {tool_args.get('complaint_text')}\n"
            f"Status: CLOSED. Ready for any new inquiries or requests."
            ).strip()
            logger.info(
                "[COMPLAINT] Complaint saved | sender_id=%s",
                sender_id,
            )

            return {
                "response": reply,
                "summary": updated_summary,
                "last_bot_message": reply,
                "complaint_saved": True,
                "complaint_usage": complaint_usage,
            }

        reply = result.message or "حدث خطأ أثناء تسجيل الشكوى."

        return {
            "response": reply,
            "summary": current_summary,
            "last_bot_message": reply,
            "complaint_saved": False,
            "complaint_usage": complaint_usage,
        }

    logger.warning(
        "[COMPLAINT] Unexpected tool call: %s",
        tool_name,
    )

    reply = "ممكن توضح شكوتك أكتر؟"

    return {
        "response": reply,
        "summary": current_summary,
        "last_bot_message": reply,
        "complaint_saved": False,
        "complaint_usage": complaint_usage,
    }