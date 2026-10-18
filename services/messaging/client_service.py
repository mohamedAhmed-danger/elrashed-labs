import logging
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from models.models import db, Client
from utils.trace_logger import trace_logger

logger = logging.getLogger(__name__)


class ClientService:
    def __init__(self, platform_id=None, page_id=None, sender_id=None, client=None):
        """
        Wrap a client by its composite key (platform_id, page_id, sender_id),
        or by a pre-loaded Client instance.

        page_id and sender_id are always handled as str.
        """
        self.platform_id = platform_id
        self.page_id = str(page_id) if page_id is not None else None
        self.sender_id = str(sender_id) if sender_id is not None else None
        self._client = client

    @property
    def client(self):
        """The client for this instance's keys, lazily loaded."""
        if self._client is None and self.platform_id is not None and self.page_id and self.sender_id:
            self._client = self.get_client()
        return self._client

    def get_client(self, platform_id=None, page_id=None, sender_id=None):
        """
        Get a client by (platform_id, page_id, sender_id), defaulting to this instance's values.

        Returns None if not found. The result is cached on the instance only
        when all three keys match the instance's own.
        """
        resolved_platform_id = platform_id if platform_id is not None else self.platform_id
        resolved_page_id = str(page_id) if page_id is not None else self.page_id
        resolved_sender_id = str(sender_id) if sender_id is not None else self.sender_id

        matches_instance = (
            resolved_platform_id == self.platform_id
            and resolved_page_id == self.page_id
            and resolved_sender_id == self.sender_id
        )

        if self._client and matches_instance:
            return self._client

        client = Client.query.filter_by(
            platform_id=resolved_platform_id,
            page_id=resolved_page_id,
            sender_id=resolved_sender_id
        ).first()

        if client and matches_instance:
            self._client = client
        return client

    def get_or_create_client(self, platform_id=None, page_id=None, sender_id=None):
        """
        Get the client, or create it with an empty summary and chat history.

        If a concurrent request creates the same client first, the existing one is returned.
        """
        resolved_platform_id = platform_id if platform_id is not None else self.platform_id
        resolved_page_id = str(page_id) if page_id is not None else self.page_id
        resolved_sender_id = str(sender_id) if sender_id is not None else self.sender_id

        client = self.get_client(resolved_platform_id, resolved_page_id, resolved_sender_id)
        if client:
            return client

        client = Client(
            sender_id=resolved_sender_id,
            page_id=resolved_page_id,
            platform_id=resolved_platform_id,
            summary="",
            last_bot_reply="",
            chat_history=[]
        )

        try:
            db.session.add(client)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing_client = self.get_client(resolved_platform_id, resolved_page_id, resolved_sender_id)
            if existing_client:
                return existing_client
            raise
        except Exception:
            db.session.rollback()
            logger.exception("[ClientService.get_or_create_client] failed")
            raise

        self._client = client
        self.platform_id = resolved_platform_id
        self.page_id = resolved_page_id
        self.sender_id = resolved_sender_id
        return client

    def save_chat_exchange(
        self,
        user_message,
        bot_reply,
        summary=None,
        max_history=6,
        platform_id=None,
        page_id=None,
        sender_id=None,
    ):
        """
        Append a user/bot exchange to the client's history and update last_bot_reply.

        The history is trimmed to the last max_history exchanges, and the summary
        is replaced only when one is given. Creates the client if missing.
        Returns the Client.
        """
        platform_id = (
            platform_id if platform_id is not None else self.platform_id
        )
        page_id = str(page_id) if page_id is not None else self.page_id
        sender_id = str(sender_id) if sender_id is not None else self.sender_id

        client = self.get_or_create_client(platform_id, page_id, sender_id)

        history = list(client.chat_history or [])
        history.append({
            "user": user_message,
            "bot": bot_reply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        client.chat_history = history[-max_history:]
        client.last_bot_reply = bot_reply

        if summary is not None:
            client.summary = summary

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[ClientService.save_chat_exchange] failed")
            raise

        trace_logger.log_db_operation(
            "save_chat_exchange",
            "clients",
            success=True,
            extra={
                "sender_id": trace_logger.sanitize_phone(sender_id or ""),
                "has_summary": bool(summary),
                "history_len": len(client.chat_history or []),
            },
        )
        return client

    def get_chat_history(
        self,
        limit=6,
        platform_id=None,
        page_id=None,
        sender_id=None
    ):
        """
        Return the client's last `limit` exchanges in chronological order.

        Each item has 'user', 'bot' and 'timestamp'. Returns [] if the client is not found.
        """
        resolved_platform_id = platform_id if platform_id is not None else self.platform_id
        resolved_page_id = str(page_id) if page_id is not None else self.page_id
        resolved_sender_id = str(sender_id) if sender_id is not None else self.sender_id

        client = self.get_client(resolved_platform_id, resolved_page_id, resolved_sender_id)
        if not client:
            return []

        history = list(client.chat_history or [])
        history = sorted(
            history,
            key=lambda item: item.get("timestamp", "")
        )
        recent_history = history[-limit:]
        trace_logger.log_db_operation(
            "get_chat_history",
            "clients",
            success=True,
            extra={
                "sender_id": trace_logger.sanitize_phone(resolved_sender_id or ""),
                "returned_exchanges": len(recent_history),
            },
        )
        return recent_history

    @staticmethod
    def get_total_clients_count() -> int:
        """Fetch total count of registered clients (0 on error)."""
        try:
            return Client.query.count()
        except Exception:
            logger.exception("[ClientService.get_total_clients_count] failed")
            return 0