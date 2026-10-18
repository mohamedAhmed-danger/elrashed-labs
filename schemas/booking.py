from pydantic import BaseModel, Field


class VisitReply(BaseModel):
    """
    Structured conversational output for the visit (home visit booking) node.
    The LLM MUST return this when it is NOT invoking `save_visit_tool` this turn
    (i.e. it's still asking for missing fields, answering a question, or the
    user hasn't confirmed yet).
    """

    reply: str = Field(
        ...,
       description=(
        "The natural language reply to send back to the patient. "
        "Egyptian Arabic by default, matching the patient's language/tone. "
        "Ask for missing booking fields one at a time. "
        "NEVER invent or assume missing booking data."
          ),
    )
    summary: str = Field(
        ...,
        description=(
        "The updated cumulative booking summary. Preserve all previously "
        "known patient and booking information, apply any new updates, "
        "and never invent missing values. Follow the SUMMARY GUIDELINES "
        "section of the system prompt exactly."
         )
    )
