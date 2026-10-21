import logging
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from graph.prompts.booking_prompt import VISIT_SYSTEM_PROMPT
from graph.state import AgentState
from graph.tools.visit_tool import save_visit_tool
from llm.llm import get_gemini
from schemas.booking import VisitReply
from services.messaging.client_service import ClientService
from services.domain.laboratory_service import LaboratoryService
from services.domain.bundle_service import BundleService
from utils.history_utils import get_chat_history
from utils.llm_utils import extract_token_usage
from utils.text_utils import detect_language_fallback, get_platform_name

logger = logging.getLogger(__name__)

OFFER_FLYER_MARKER = "LAB OFFER / BUNDLE FLYER"


def booking_node(state: AgentState) -> dict:
    """
    Handle home visit booking conversations.

    Flow:
        Get Context
        → Load Lab & Bundle Info from DB
        → Load History + RAG
        → Build Prompt
        → Gemini Tool Calling
        → Handle Tool
        → Return State
    """

    # 1. Get conversation context
    page_id = state.get("page_id")
    sender_id = state.get("sender_id")
    platform_id = state.get("platform_id")

    user_message = state["user_message"]
    current_summary = state.get("summary") or ""
    last_bot_message = state.get("last_bot_message") or ""
    matched_context = state.get("rag_context") or ""

    # Offer flyers must always load the bundles context, even if the classifier missed it.
    is_bundle_query = (
        state.get("is_bundle_query", False)
        or OFFER_FLYER_MARKER in user_message
    )

    # 2. Fetch dynamic Lab Info & Bundles Context from DB
    lab_name, lab_location, lab_desc = LaboratoryService.get_current_lab_info(state.get("laboratory_id"))
    support_phone = LaboratoryService.get_support_phone(state.get("laboratory_id")) or "—"

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

    # 4. Build the LLM prompt with dynamic Lab details & Bundles
    current_time = datetime.now().strftime(
        "Today is %A, %B %d, %Y. Current time is %I:%M %p"
    )

    system_prompt = f"""
{VISIT_SYSTEM_PROMPT}

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
CRITICAL: CURRENT TEMPORAL CONTEXT
====================
{current_time}

====================
RECENT CONVERSATION
====================
{recent_history}

====================
VERIFIED LAB INFORMATION
====================
{matched_context or "(No matching laboratory test found.)"}

====================
ALREADY COLLECTED SUMMARY
====================
Summary:
{current_summary}

Last bot message:
{last_bot_message}
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    # 5. Ask Gemini to handle the booking
    try:
        llm = get_gemini().bind_tools(
            [save_visit_tool, VisitReply],
            tool_choice="any",
        )

        response = llm.invoke(messages)
        tokens = extract_token_usage(response) or {}

    except Exception:
        logger.exception(
            "[BOOKING] LLM error | sender_id=%s",
            sender_id,
        )

        fallback = detect_language_fallback(
            user_message,
            arabic=(
                f"عذرًا، حدث خطأ مؤقت أثناء معالجة طلبك ⚠️\n\n"
                f"يرجى المحاولة مرة أخرى بعد قليل، أو يمكنك التواصل مباشرة مع خدمة عملاء {lab_name} لمساعدتك فوراً عبر الرقم:\n"
                f"📞 **{support_phone}**\n\n"
                f"نحن في خدمتك دائمًا ✨"
            ),
            default=(
                f"Apologies, a temporary error occurred while processing your request ⚠️\n\n"
                f"Please try again in a moment, or contact {lab_name} customer service directly for assistance at:\n"
                f"📞 **{support_phone}**\n\n"
                f"We are always happy to help! ✨"
            ),
        )

        return {
            "response": fallback,
            "summary": current_summary,
            "last_bot_message": fallback,
            "booking_saved": False,
            "booking_reference": None,
            "booking_pdf": None,
            "booking_data": None,
            "booking_usage": None,
        }

    # 6. Handle the selected tool
    if not response.tool_calls:
        reply = response.content or "ممكن توضح طلبك أكتر؟"

        return {
            "response": reply,
            "summary": current_summary,
            "last_bot_message": reply,
            "booking_saved": False,
            "booking_reference": None,
            "booking_pdf": None,
            "booking_data": None,
            "booking_usage": tokens,
        }

    tool_call = response.tool_calls[0]
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})

    # Normal conversation reply
    if tool_name == "VisitReply":
        reply = tool_args.get("reply", "")
        updated_summary = tool_args.get(
            "summary",
            current_summary,
        )

        return {
            "response": reply,
            "summary": updated_summary,
            "last_bot_message": reply,
            "booking_saved": False,
            "booking_reference": None,
            "booking_pdf": None,
            "booking_data": None,
            "booking_usage": tokens,
        }

    # Save booking
    if tool_name == "save_visit_tool":
        tool_args["comes_from"] = get_platform_name(platform_id)
        tool_args["laboratory_id"] = state.get("laboratory_id")  # from the page, never from the LLM

        tool_result = save_visit_tool.invoke(tool_args)

        if tool_result.success and tool_result.visit:
            booking = tool_result.visit
            booking_reference = booking.reference_id

            booking_data = {
                "reference_id": booking_reference,
                "name": tool_args.get("name"),
                "phone": tool_args.get("phone_number"),
                "address": tool_args.get("address"),
                "details": tool_args.get("details"),
                "date": tool_args.get("date"),
                "time": tool_args.get("time"),
                "comes_from": tool_args["comes_from"],
                "laboratory_id": state.get("laboratory_id"),
            }

            reply = detect_language_fallback(
                user_message,
                arabic=(
                    f"تم استلام طلب حجزك بنجاح ✅\n\n"
                    f"📌 **رقم الطلب:** *{booking_reference}*\n\n"
                    f"سيقوم فريق خدمة العملاء في {lab_name} بالتواصل معك قريباً لتأكيد الموعد النهائي.\n\n"
                    f"مرفق أدناه تذكرة الحجز الخاصة بك 🎫"
                ),
                default=(
                    f"Your booking request has been successfully received ✅\n\n"
                    f"📌 **Reference ID:** *{booking_reference}*\n\n"
                    f"Our customer service team at {lab_name} will contact you shortly to confirm the final appointment.\n\n"
                    f"Here is your booking ticket below 🎫"
                ),
            )
            updated_summary = (
                f"{current_summary}\n\n"
                f"--- BOOKING STATUS UPDATE ---\n"
                f"✅ Visit booking confirmed & saved successfully\n"
                f"Booked Tests: {tool_args.get('details')}\n"
                f"Status: COMPLETED. Ready for any new inquiries or requests."
            ).strip()

            return {
                "response": reply,
                "summary": updated_summary,
                "last_bot_message": reply,
                "booking_saved": True,
                "booking_reference": booking_reference,
                "booking_pdf": booking.image_bytes,
                "booking_data": booking_data,
                "booking_usage": tokens,
            }

        reply = tool_result.message or "حدث خطأ أثناء حفظ الحجز."

        return {
            "response": reply,
            "summary": current_summary,
            "last_bot_message": reply,
            "booking_saved": False,
            "booking_reference": None,
            "booking_pdf": None,
            "booking_data": None,
            "booking_usage": tokens,
        }

    logger.warning(
        "[BOOKING] Unexpected tool call: %s",
        tool_name,
    )

    return {
        "response": "ممكن توضح طلبك أكتر؟",
        "summary": current_summary,
        "last_bot_message": "ممكن توضح طلبك أكتر؟",
        "booking_saved": False,
        "booking_reference": None,
        "booking_pdf": None,
        "booking_data": None,
        "booking_usage": tokens,
    }