# graph/utils/llm_utils.py

from typing import Any


def extract_token_usage(message: Any) -> dict[str, int] | None:
    """Safely extract token usage from an LLM response message."""

    if not message:
        return None

    usage = getattr(message, "usage_metadata", None)

    if not usage:
        return None

    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }

def serialize_pydantic_list(items: list[Any] | None) -> list[Any]:
    """Convert Pydantic models to dictionaries when needed."""

    if not items:
        return []

    return [
        item.model_dump() if hasattr(item, "model_dump") else item
        for item in items
    ]