import logging
from dataclasses import dataclass
from typing import Optional

from langchain_core.tools import tool
from services.domain.complaint_service import ComplaintService

logger = logging.getLogger(__name__)


@dataclass
class SaveComplaintResult:
    success: bool
    message: Optional[str] = None


@tool
def save_complaint_tool(
    phone_number: str,
    complaint_text: str,
    comes_from: str = "unknown",
) -> SaveComplaintResult:
    """
    Saves a customer complaint directly to the database once both the contact
    phone number and the complaint details are fully collected from the user.

    Args:
        phone_number: Contact phone number of the complainant.
        complaint_text: Detailed explanation of the issue or complaint.
        comes_from: Channel or platform originating the complaint.
    """
    try:
        service = ComplaintService()
        save_result = service.save_complaint(
            phone_number=phone_number,
            complaint_text=complaint_text,
            comes_from=comes_from,
        )

        if save_result.success:
            logger.info("[COMPLAINT TOOL] Complaint saved successfully via ComplaintService.")
            return SaveComplaintResult(
                success=True,
                message=save_result.message,
            )

        logger.error("[COMPLAINT TOOL] Service save returned error: %s", save_result.message)
        return SaveComplaintResult(
            success=False,
            message=save_result.message,
        )

    except Exception:
        logger.exception("[COMPLAINT TOOL] Unexpected error while saving complaint")
        return SaveComplaintResult(
            success=False,
            message="حدث خطأ أثناء حفظ الشكوى، حاول مرة أخرى.",
        )