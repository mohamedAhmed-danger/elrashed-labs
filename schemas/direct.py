from pydantic import BaseModel, Field


class DirectResponse(BaseModel):
    reply: str = Field(
        description="The final response that should be sent to the user."
    )

    summary: str = Field(
        description="Updated concise summary of the conversation."
    )

    internal_reasoning: str = Field(
        description="Internal reasoning used to determine the response."
    )
