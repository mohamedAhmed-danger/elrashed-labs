import logging
from dataclasses import dataclass
from typing import Annotated, Optional, Any

from langchain_core.tools import InjectedToolArg, tool

from services.domain.booking_service import BookingService


logger = logging.getLogger(__name__)


@dataclass
class SaveVisitResult:
    success: bool
    visit: Any = None
    message: Optional[str] = None


@tool
def save_visit_tool(
    name: str,
    phone_number: str,
    address: str,
    details: str,
    date: str,
    time: str,
    comes_from: str = "WhatsApp",
    laboratory_id: Annotated[Optional[int], InjectedToolArg] = None,
) -> SaveVisitResult:
    """Saves a confirmed home visit medical laboratory booking."""

    # laboratory_id is injected by the node from the page the patient wrote to.
    # InjectedToolArg keeps it out of the schema the LLM sees.
    if laboratory_id is None:
        return SaveVisitResult(success=False, message="Missing laboratory context.")

    try:
        # 1. Save booking
        booking_service = BookingService()

        result = booking_service.save_booking(
            name=name,
            phone=phone_number,
            date=date,
            details=details,
            comes_from=comes_from,
            time=time,
            address=address,
            laboratory_id=laboratory_id,
        )

        # 2. Make sure booking was saved successfully
        if not result or not result.reference_id:
            return SaveVisitResult(
                success=False,
                message="Failed to generate booking reference.",
            )

        # 3. Return booking result
        return SaveVisitResult(
            success=True,
            visit=result,
            message="Booking saved successfully.",
        )

    except Exception as e:
        logger.exception(
            "Error inside save_visit_tool"
        )

        return SaveVisitResult(
            success=False,
            message=str(e),
        )