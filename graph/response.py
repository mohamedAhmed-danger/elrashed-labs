from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentResponse:
    response: str
    intent: Optional[str]
    usage: dict

    @staticmethod
    def from_result(result: dict) -> "AgentResponse":
        usage = {
            "intent": result.get("intent_usage") or {},
            "retrieval": result.get("retrieval_usage") or {},
            "booking": result.get("booking_usage") or {},
            "complaint": result.get("complaint_usage") or {},
            "direct": result.get("direct_usage") or {},
            "inquiry": result.get("inquiry_usage") or {},
        }

        return AgentResponse(
            response=result.get("response") or "",
            intent=result.get("intent"),
            usage=usage,
        )

    def to_dict(self) -> dict:
        return {
            "response": self.response,
            "intent": self.intent,
            "usage": self.usage,
        }
