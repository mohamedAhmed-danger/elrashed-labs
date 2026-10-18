"""
notfication_center/exceptions.py
================================
Comprehensive hierarchy of custom domain exceptions for the Medical Laboratory Agent Platform.
Every custom exception provides:
  - message: User-friendly or developer-friendly description
  - error_code: Unique programmatic error identifier (e.g. DB_COMMIT_ERROR, LLM_AUTH_ERROR)
  - context: Key-value dictionary providing runtime details (user_id, platform, page_id, etc.)
  - original_exception: The underlying cause if chained
"""

import traceback
from typing import Any, Dict, Optional


class LabSystemException(Exception):
    """Base exception for all domain-specific exceptions in the laboratory system."""

    default_code: str = "SYSTEM_ERROR"
    default_message: str = "An unexpected error occurred in the laboratory system."

    def __init__(
        self,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
    ):
        self.message = message or self.default_message
        self.error_code = error_code or self.default_code
        self.context = context or {}
        self.original_exception = original_exception
        self.alert_sent: bool = False
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context,
        }
        if self.original_exception:
            data["original_error"] = {
                "type": type(self.original_exception).__name__,
                "message": str(self.original_exception),
            }
        return data

    def get_full_traceback(self) -> str:
        if self.original_exception:
            return "".join(
                traceback.format_exception(
                    type(self.original_exception),
                    self.original_exception,
                    self.original_exception.__traceback__,
                )
            )
        return traceback.format_exc()

    def __str__(self) -> str:
        ctx_str = f" | Context: {self.context}" if self.context else ""
        orig_str = f" | Caused by: {repr(self.original_exception)}" if self.original_exception else ""
        return f"[{self.error_code}] {self.message}{ctx_str}{orig_str}"


# ==============================================================================
# 1. Database & Persistence Exceptions
# ==============================================================================

class DatabaseException(LabSystemException):
    """Base exception for database transaction or query failures."""
    default_code = "DB_ERROR"
    default_message = "A database operation failed."


class DatabaseCommitException(DatabaseException):
    """Raised when committing a session to the database fails."""
    default_code = "DB_COMMIT_ERROR"
    default_message = "Failed to commit database transaction."


class DatabaseQueryException(DatabaseException):
    """Raised when executing a query or retrieval fails."""
    default_code = "DB_QUERY_ERROR"
    default_message = "Database query execution failed."


class DatabaseIntegrityException(DatabaseException):
    """Raised on unique constraint or foreign key violations."""
    default_code = "DB_INTEGRITY_ERROR"
    default_message = "Database integrity constraint violation."


class EntityNotFoundException(DatabaseException):
    """Raised when a requested database entity does not exist."""
    default_code = "ENTITY_NOT_FOUND"
    default_message = "Requested database entity was not found."


# ==============================================================================
# 2. LLM & AI Exceptions
# ==============================================================================

class LLMException(LabSystemException):
    """Base exception for LLM-related errors."""
    default_code = "LLM_ERROR"
    default_message = "LLM invocation failed."


class LLMAuthenticationException(LLMException):
    """Raised when API key is missing or unauthorized."""
    default_code = "LLM_AUTH_ERROR"
    default_message = "LLM API authentication failed (missing or invalid API key)."


class LLMQuotaException(LLMException):
    """Raised when LLM API quota is exceeded or rate-limited."""
    default_code = "LLM_QUOTA_ERROR"
    default_message = "LLM API quota exceeded or rate limit hit."


class LLMTimeoutException(LLMException):
    """Raised when LLM API call times out."""
    default_code = "LLM_TIMEOUT"
    default_message = "LLM API request timed out."


class LLMStructuredOutputException(LLMException):
    """Raised when structured JSON parsing/validation from LLM fails."""
    default_code = "LLM_STRUCTURED_OUTPUT_ERROR"
    default_message = "Failed to parse structured output from LLM."


# ==============================================================================
# 3. OCR & Vision Exceptions
# ==============================================================================

class OCRException(LabSystemException):
    """Base exception for prescription OCR processing errors."""
    default_code = "OCR_ERROR"
    default_message = "Prescription OCR processing failed."


class OCRVisionAPIException(OCRException):
    """Raised when multimodal Gemini vision API call fails."""
    default_code = "OCR_VISION_API_ERROR"
    default_message = "Gemini multimodal vision call failed during OCR."


class OCRImageProcessingException(OCRException):
    """Raised when an image file cannot be opened, decoded, or saved."""
    default_code = "OCR_IMAGE_PROCESSING_ERROR"
    default_message = "Failed to load or process image for OCR."


class OCRClassificationException(OCRException):
    """Raised when OCR classification logic encounters an unexpected state."""
    default_code = "OCR_CLASSIFICATION_ERROR"
    default_message = "OCR classification logic failed."


# ==============================================================================
# 4. Platform & Webhook Exceptions
# ==============================================================================

class PlatformException(LabSystemException):
    """Base exception for messaging platform errors (Facebook, WhatsApp/WAHA)."""
    default_code = "PLATFORM_ERROR"
    default_message = "Messaging platform communication failed."


class FacebookAPIException(PlatformException):
    """Raised when Facebook Graph API call fails or token is expired."""
    default_code = "FB_API_ERROR"
    default_message = "Facebook Graph API request failed."


class WahaAPIException(PlatformException):
    """Raised when WAHA (WhatsApp HTTP API) request fails or container is unreachable."""
    default_code = "WAHA_API_ERROR"
    default_message = "WAHA WhatsApp API request failed or container unreachable."


class MediaDownloadException(PlatformException):
    """Raised when media download (image/voice/file) from platform CDN fails."""
    default_code = "MEDIA_DOWNLOAD_ERROR"
    default_message = "Failed to download media file from messaging platform."


class WebhookPayloadException(PlatformException):
    """Raised when an incoming webhook payload is malformed or invalid."""
    default_code = "WEBHOOK_PAYLOAD_ERROR"
    default_message = "Incoming webhook payload was malformed or missing required keys."


# ==============================================================================
# 5. Agent & Workflow Node Exceptions
# ==============================================================================

class AgentExecutionException(LabSystemException):
    """Base exception for LangGraph workflow and state machine execution failures."""
    default_code = "AGENT_EXECUTION_ERROR"
    default_message = "Agent execution failed."


class IntentClassificationException(AgentExecutionException):
    """Raised when intent node fails to route or extract search queries."""
    default_code = "INTENT_NODE_ERROR"
    default_message = "Intent classification node failed."


class BookingException(AgentExecutionException):
    """Raised when booking/home visit flow encounters a critical error."""
    default_code = "BOOKING_ERROR"
    default_message = "Home visit booking flow failed."


class ComplaintException(AgentExecutionException):
    """Raised when customer complaint registration flow fails."""
    default_code = "COMPLAINT_ERROR"
    default_message = "Complaint registration flow failed."


class InquiryException(AgentExecutionException):
    """Raised when lab test inquiry response generation fails."""
    default_code = "INQUIRY_ERROR"
    default_message = "Lab inquiry response generation failed."


class TicketGenerationException(AgentExecutionException):
    """Raised when generating booking PDF or PNG ticket image fails."""
    default_code = "TICKET_GENERATION_ERROR"
    default_message = "Failed to generate appointment ticket PDF or image."


# ==============================================================================
# 6. Search & Knowledge Pipeline Exceptions
# ==============================================================================

class SearchRAGException(LabSystemException):
    """Base exception for RAG and search operations."""
    default_code = "SEARCH_RAG_ERROR"
    default_message = "Search or RAG operation failed."


class VectorStoreIndexException(SearchRAGException):
    """Raised when FAISS index loading, saving, search, or upsert fails."""
    default_code = "VECTOR_STORE_ERROR"
    default_message = "FAISS vector store index operation failed."


class EmbeddingGenerationException(SearchRAGException):
    """Raised when generating text embedding vectors fails."""
    default_code = "EMBEDDING_GENERATION_ERROR"
    default_message = "Failed to generate embedding vector via Gemini."


class KnowledgePipelineException(SearchRAGException):
    """Raised when knowledge generation, regeneration, or approval pipeline fails."""
    default_code = "KNOWLEDGE_PIPELINE_ERROR"
    default_message = "Knowledge pipeline processing failed."


# ==============================================================================
# 7. Subscription & Billing Exceptions
# ==============================================================================

class SubscriptionException(LabSystemException):
    """Base exception for subscription, quota, and billing issues."""
    default_code = "SUBSCRIPTION_ERROR"
    default_message = "Subscription check or quota operation failed."


class SubscriptionLimitExceededException(SubscriptionException):
    """Raised when account message limit and grace limit are both exceeded."""
    default_code = "SUBSCRIPTION_LIMIT_EXCEEDED"
    default_message = "Subscription message quota and grace limit exceeded."


class SubscriptionSuspendedException(SubscriptionException):
    """Raised when AI service is suspended for this laboratory."""
    default_code = "SUBSCRIPTION_SUSPENDED"
    default_message = "Laboratory subscription is suspended."


class SubscriptionExpiredException(SubscriptionException):
    """Raised when subscription has passed its expiration date."""
    default_code = "SUBSCRIPTION_EXPIRED"
    default_message = "Laboratory subscription has expired."


# ==============================================================================
# 8. Validation & Business Logic Exceptions
# ==============================================================================

class ValidationException(LabSystemException):
    """Raised when input validation fails for any user request or API payload."""
    default_code = "VALIDATION_ERROR"
    default_message = "Validation failed for the requested operation."
