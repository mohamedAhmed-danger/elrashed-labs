from pydantic import BaseModel, Field


class ComplaintResponse(BaseModel):

    reply: str = Field(
        description="The response to send to the user."
    )

    summary: str = Field(
        description="Updated conversation summary."
    )
