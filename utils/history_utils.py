import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def get_chat_history(
    state,
    client_service,
    limit: int = 6,
) -> tuple[list[dict[str, Any]], str]:
    """Get chat history from state or client service and format it."""

    history = state.get("chat_history")

    if history is None:
        try:
            history = client_service.get_chat_history(limit=limit)
        except Exception as exc:
            logger.warning("Failed to load chat history: %s", exc)
            history = []

    return history, format_chat_history(history)


def format_chat_history(
    history_exchanges: list[dict[str, Any]],
) -> str:
    """Format chat history into a compact LLM-readable string."""

    if not history_exchanges:
        return ""

    history_lines = []

    for turn in history_exchanges:
        user_message = turn.get("user", "")
        bot_message = turn.get("bot", "")

        timestamp = turn.get("timestamp", "")
        time_prefix = ""

        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_timestamp = dt.strftime("%Y-%m-%d %H:%M")
                time_prefix = f"[{formatted_timestamp}] "
            except (ValueError, TypeError):
                pass

        history_lines.append(
            f"{time_prefix}User: {user_message}\n"
            f"{time_prefix}Bot: {bot_message}"
        )

    return "\n---\n".join(history_lines)