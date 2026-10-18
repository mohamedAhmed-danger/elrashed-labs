from typing import Any, Optional, TypedDict

from schemas.intent import IntentType, RefinedQuery


class AgentState(TypedDict, total=False):
    # =========================
    # Platform
    # =========================
    page_id: Optional[str]
    sender_id: Optional[str]
    platform_id: Optional[int]
    platform_name: Optional[str]
    laboratory_id: Optional[int]

    # =========================
    # Conversation
    # =========================
    user_message: str
    response: Optional[str]
    chat_history: Optional[list[dict[str, Any]]]
    summary: Optional[str]
    last_bot_message: Optional[str]

    # =========================
    # Routing
    # =========================
    intent: Optional[IntentType]
    is_bundle_query: Optional[bool]

    # =========================
    # RAG
    # =========================
    refined_queries: Optional[list[RefinedQuery]]
    rag_context: Optional[str]

    # =========================
    # Booking
    # =========================
    booking_data: Optional[dict[str, Any]]
    booking_reference: Optional[str]
    booking_pdf: Optional[bytes]
    booking_saved: Optional[bool]

    # =========================
    # Complaint
    # =========================
    complaint_saved: Optional[bool]

    # =========================
    # Usage
    # =========================
    intent_usage: Optional[dict[str, Any]]
    retrieval_usage: Optional[dict[str, Any]]
    booking_usage: Optional[dict[str, Any]]
    complaint_usage: Optional[dict[str, Any]]
    inquiry_usage: Optional[dict[str, Any]]
    direct_usage: Optional[dict[str, Any]]