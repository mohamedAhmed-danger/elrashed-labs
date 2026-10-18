from pydantic import BaseModel, Field


class InquiryResponse(BaseModel):
    internal_reasoning: str = Field(
        description=(
            "Think here first: identify the user's intent, review the test prices "
            "from the retrieved knowledge, and add up the numbers precisely step "
            "by step before writing the final reply."
        )
    )
    reply: str = Field(
        description=(
            "The final reply sent to the patient in Arabic (clear, friendly, "
            "and well-formatted). If the question is about prices, write the "
            "full breakdown and total here directly."
        )
    )
    summary: str = Field(
        description=(
            "The updated conversation summary, in English (preserve the prior "
            "context and add the details of the current turn)."
        )
    )
