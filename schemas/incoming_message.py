import time
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncomingMessage(BaseModel):
    """
    A single incoming message from any platform (Facebook, WhatsApp, ...), normalized
    into one shape before it enters the dispatch/agent pipeline.

    Construction API is unchanged from the plain-class version: pass `msg_type=`,
    read back via `.type` (kept via alias, since other code in the project already
    calls it this way).
    """

    model_config = ConfigDict(populate_by_name=True)

    sender_id: str
    page_id: str
    platform_id: int
    platform_name: Optional[str] = None
    type: str = Field(alias="msg_type")
    text: Optional[str] = None
    media: Optional[Any] = None
    received_at: float = Field(default_factory=time.time)

    @field_validator("received_at", mode="before")
    @classmethod
    def _default_received_at(cls, v):
        # Preserve old behavior: an explicit None still falls back to "now",
        # not just an omitted field.
        return v if v is not None else time.time()