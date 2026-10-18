import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from models.models import Page, Subscription
from schemas.incoming_message import IncomingMessage
from schemas.prepare_result import PrepareResult
from services.shared.subscription_service import SubscriptionService
from services.messaging.webhook_service import (
    build_post_booking_feedback_message,
    dispatch_incoming_message,
    process_facebook_payload,
    process_waha_payload,
)
from services.messaging.redis_worker import process_conversation
from config import Config


class TestWebhookSuite(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    # ── Facebook Tests ────────────────────────────────────────────────────────

    @patch("routes.webhook_routes.VERIFY_TOKEN", "test_secret_token_123")
    def test_facebook_get_valid_verification(self):
        """GET /webhook/facebook with valid verify_token returns challenge with 200."""
        response = self.client.get(
            "/webhook/facebook?hub.mode=subscribe&hub.verify_token=test_secret_token_123&hub.challenge=1158201444"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "1158201444")

    @patch("routes.webhook_routes.VERIFY_TOKEN", "test_secret_token_123")
    def test_facebook_get_invalid_verification(self):
        """GET /webhook/facebook with invalid token returns 403 Forbidden."""
        response = self.client.get(
            "/webhook/facebook?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=1158201444"
        )
        self.assertEqual(response.status_code, 403)

    @patch("routes.webhook_routes.process_facebook_payload")
    def test_facebook_post_acknowledges_fast(self, mock_process):
        """POST /webhook/facebook returns EVENT_RECEIVED 200 immediately and starts worker thread."""
        payload = {
            "object": "page",
            "entry": [{"id": "page_123", "messaging": [{"message": {"text": "hello"}}]}]
        }
        response = self.client.post("/webhook/facebook", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "EVENT_RECEIVED")

    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform", return_value=None)
    def test_facebook_unknown_page_handled_gracefully(self, mock_get_page):
        """Facebook worker ignores unknown page without crashing."""
        payload = {"entry": [{"id": "unknown_page_999", "messaging": [{"message": {"text": "hi"}}]}]}

        # Should complete without error
        process_facebook_payload(payload, self.app)
        mock_get_page.assert_called_with(page_id="unknown_page_999", platform_id=1)

    @patch("services.messaging.webhook_service.dispatch_incoming_message")
    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_facebook_tenant_routing_and_messaging(self, mock_get_page, mock_get_handler, mock_dispatch):
        """Verifies entry.id resolves exact Page and laboratory_id for Facebook messaging."""
        mock_page = MagicMock(page_id="1001", laboratory_id=5, token="token_abc")
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock(platform_name="Facebook")
        mock_get_handler.return_value = mock_handler

        payload = {
            "entry": [{
                "id": "1001",
                "messaging": [{
                    "sender": {"id": "user_555"},
                    "message": {"text": "أريد حجز تحليل"}
                }]
            }]
        }

        process_facebook_payload(payload, self.app)

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kwargs["page_id"], "1001")
        self.assertEqual(call_kwargs["platform_id"], 1)
        self.assertEqual(call_kwargs["laboratory_id"], 5)
        self.assertEqual(call_kwargs["message"].text, "أريد حجز تحليل")
        self.assertEqual(call_kwargs["message"].sender_id, "user_555")

    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_facebook_comments_handling(self, mock_get_page, mock_get_handler):
        """Verifies feed change comments are routed to handler.handle_comment."""
        mock_page = MagicMock(page_id="1001", laboratory_id=5)
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        payload = {
            "entry": [{
                "id": "1001",
                "changes": [{
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "comment_id": "comment_999",
                        "post_id": "1001_post_111"
                    }
                }]
            }]
        }

        process_facebook_payload(payload, self.app)
        mock_handler.handle_comment.assert_called_once_with(comment_id="comment_999", page_id="1001")

    # ── WAHA Tests ───────────────────────────────────────────────────────────

    @patch("routes.webhook_routes.process_waha_payload")
    def test_waha_post_acknowledges_fast(self, mock_process):
        """POST /webhook/waha returns OK 200 immediately."""
        payload = {"event": "message", "session": "default", "payload": {"from": "123@c.us", "body": "hi"}}
        response = self.client.post("/webhook/waha", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), "OK")

    @patch("services.messaging.webhook_service.dispatch_incoming_message")
    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_waha_me_lid_tenant_routing(self, mock_get_page, mock_get_handler, mock_dispatch):
        """Verifies data.me.lid is used authoritatively to route to the correct Page."""
        mock_page = MagicMock(page_id="20000000001@lid", laboratory_id=12)
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock(platform_name="WhatsApp")
        mock_get_handler.return_value = mock_handler

        payload_data = {
            "event": "message",
            "session": "default",
            "me": {"id": "phone_1", "lid": "20000000001@lid"},
            "payload": {
                "from": "patient_777@c.us",
                "body": "سعر صورة الدم الكاملة كام؟",
                "fromMe": False
            }
        }

        process_waha_payload(payload_data, self.app)

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kwargs["page_id"], "20000000001@lid")
        self.assertEqual(call_kwargs["platform_id"], 2)
        self.assertEqual(call_kwargs["laboratory_id"], 12)
        self.assertEqual(call_kwargs["message"].sender_id, "patient_777@c.us")

    @patch("services.messaging.webhook_service.send_production_alert")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_worker_exception_triggers_alert_and_cleanup(self, mock_get_page, mock_alert):
        """Exceptions in webhook workers trigger production alerts and clean up session."""
        mock_get_page.side_effect = RuntimeError("Database connection lost")
        payload = {"entry": [{"id": "page_error", "messaging": [{"message": {"text": "hi"}}]}]}

        process_facebook_payload(payload, self.app)
        mock_alert.assert_called_once()

    @patch("services.messaging.webhook_service.dispatch_incoming_message")
    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_waha_multi_tenant_isolation_rejects_unknown_lid(self, mock_get_page, mock_get_handler, mock_dispatch):
        """
        Verify tenant isolation:
        Page A (Lab A) and Page B (Lab B) exist in database.
        Incoming WAHA payload has an unknown me.lid.
        Must NOT route to Page A, must NOT route to Page B, must NOT call dispatch or agent.
        """
        page_a = MagicMock(page_id="11111111@lid", laboratory_id=1)
        page_b = MagicMock(page_id="22222222@lid", laboratory_id=2)
        mock_handler = MagicMock(platform_name="WhatsApp")
        mock_get_handler.return_value = mock_handler

        def mock_get_page_by_id(page_id=None, platform_id=None):
            if page_id in ("11111111@lid", "11111111"):
                return page_a
            elif page_id in ("22222222@lid", "22222222"):
                return page_b
            return None

        mock_get_page.side_effect = mock_get_page_by_id

        unknown_payload = {
            "event": "message",
            "session": "default",
            "me": {"id": "unknown_phone", "lid": "99999999@lid"},
            "payload": {
                "from": "patient_888@c.us",
                "body": "تحليل سرعة الترسيب",
                "fromMe": False
            }
        }

        process_waha_payload(unknown_payload, self.app)

        # Neither handler nor dispatch should be invoked for unknown LID
        mock_get_handler.assert_not_called()
        mock_dispatch.assert_not_called()

        # Conversely, valid LID for Page A routes strictly to Page A (Lab 1)
        valid_payload_a = {
            "event": "message",
            "session": "default",
            "me": {"id": "phone_a", "lid": "11111111@lid"},
            "payload": {
                "from": "patient_888@c.us",
                "body": "تحليل سرعة الترسيب",
                "fromMe": False
            }
        }
        process_waha_payload(valid_payload_a, self.app)
        mock_dispatch.assert_called_once()
        self.assertEqual(mock_dispatch.call_args.kwargs["laboratory_id"], 1)
        self.assertEqual(mock_dispatch.call_args.kwargs["page_id"], "11111111@lid")

    # ── Shared Behavior Tests ─────────────────────────────────────────────────

    @patch("services.messaging.webhook_service.SubscriptionService.can_use_ai", return_value=(False, "Message limit exceeded."))
    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_subscription_exhaustion_blocks_processing(self, mock_get_page, mock_get_handler, mock_can_use_ai):
        """When laboratory subscription quota is exhausted, drops silently without sending anything to user."""
        mock_page = MagicMock(page_id="page_1", laboratory_id=3)
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock()
        mock_get_handler.return_value = mock_handler

        msg = IncomingMessage(
            sender_id="u_1",
            page_id="page_1",
            platform_id=1,
            platform_name="Facebook",
            msg_type="text",
            text="hello",
        )

        dispatch_incoming_message(msg, page_id="page_1", platform_id=1, laboratory_id=3, app=self.app)

        # Nothing should be sent to the user when quota is exhausted
        mock_handler.send.assert_not_called()

    @patch("services.messaging.webhook_service.enqueue_message")
    @patch("services.messaging.webhook_service.get_redis_client")
    @patch("services.messaging.webhook_service.SubscriptionService.can_use_ai", return_value=(True, "OK"))
    @patch("services.messaging.webhook_service.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_agent_message_is_debounced(
        self, mock_get_page, mock_get_handler, mock_can_use_ai, mock_redis, mock_enqueue
    ):
        """Messages with mode agent_text are enqueued into Redis queue with arrival time."""
        mock_page = MagicMock(page_id="page_1", laboratory_id=3)
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock()
        mock_handler.prepare.return_value = PrepareResult("agent_text", "سعر التحليل كام؟", None)
        mock_handler.platform_name = "Facebook"
        mock_get_handler.return_value = mock_handler

        msg = IncomingMessage(
            sender_id="u_1",
            page_id="page_1",
            platform_id=1,
            platform_name="Facebook",
            msg_type="text",
            text="سعر التحليل كام؟",
        )

        dispatch_incoming_message(msg, page_id="page_1", platform_id=1, laboratory_id=3, app=self.app)

        mock_enqueue.assert_called_once()
        call_kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(call_kwargs["sender_id"], "u_1")
        self.assertEqual(call_kwargs["text"], "سعر التحليل كام؟")

    @patch("services.messaging.redis_worker._finish_processing", return_value=True)
    @patch("services.messaging.redis_worker._require_ownership")
    @patch("services.messaging.redis_worker._send_reply")
    @patch("services.messaging.redis_worker.run_agent")
    @patch("services.messaging.redis_worker.get_handler")
    @patch("services.domain.page_service.PageService.get_page_by_page_and_platform")
    def test_redis_worker_processes_conversation(
        self, mock_get_page, mock_get_handler, mock_run_agent, mock_send_reply, mock_ownership, mock_finish
    ):
        """Worker reads queued text items, invokes run_agent, and calls _send_reply."""
        mock_page = MagicMock(page_id="page_1", laboratory_id=3)
        mock_get_page.return_value = mock_page
        mock_handler = MagicMock(platform_name="Facebook")
        mock_get_handler.return_value = mock_handler

        fake_ticket = b"fake_png_ticket_bytes"
        mock_run_agent.return_value = ("تم تأكيد حجزك بنجاح!", fake_ticket, "REF-998877")

        mock_redis = MagicMock()
        queued_items = [
            '{"text": "أريد حجز موعد", "received_at": 100.0}',
        ]
        mock_redis.lrange.return_value = queued_items

        process_conversation(
            mock_redis,
            conversation_key="1:page_1:u_1",
            owner_token="owner_123",
            heartbeat_script=MagicMock(),
            finish_script=MagicMock(),
            app=self.app,
        )

        mock_run_agent.assert_called_once()
        mock_send_reply.assert_called_once_with(
            mock_handler, "u_1", "تم تأكيد حجزك بنجاح!", fake_ticket, "REF-998877"
        )

    def test_build_post_booking_feedback_message(self):
        """Verifies feedback message builder with and without reference ID."""
        msg_with_ref = build_post_booking_feedback_message("REF-12345")
        self.assertIn("/feedback/REF-12345", msg_with_ref)

        msg_without_ref = build_post_booking_feedback_message(None)
        self.assertIn("يسعدنا تقييم تجربتك", msg_without_ref)

    def test_build_post_booking_feedback_message_default_url(self):
        """Verifies FEEDBACK_BASE_URL defaults to https://elbedawy-agent.revyai.tech."""
        with patch.object(Config, "FEEDBACK_BASE_URL", None):
            msg = build_post_booking_feedback_message("REF-ABC")
            self.assertIn("https://elbedawy-agent.revyai.tech/feedback/REF-ABC", msg)

    def test_subscription_service_can_use_ai_contract(self):
        """Verifies can_use_ai returns (bool, str) tuple across models, IDs, and instances."""
        active_sub = MagicMock(spec=Subscription)
        active_sub.is_active = True
        active_sub.end_date = None
        active_sub.message_used = 10
        active_sub.message_limit = 100
        active_sub.grace_limit = 10

        allowed, reason = SubscriptionService.can_use_ai(active_sub)
        self.assertTrue(allowed)
        self.assertEqual(reason, "OK")

        # Quota exceeded
        exceeded_sub = MagicMock(spec=Subscription)
        exceeded_sub.is_active = True
        exceeded_sub.end_date = None
        exceeded_sub.message_used = 110
        exceeded_sub.message_limit = 100
        exceeded_sub.grace_limit = 10

        allowed, reason = SubscriptionService.can_use_ai(exceeded_sub)
        self.assertFalse(allowed)
        self.assertEqual(reason, "Message limit exceeded.")

        # Demonstrate Python truthy-tuple caveat: bool((False, reason)) is True!
        tuple_result = (False, "Message limit exceeded.")
        self.assertTrue(bool(tuple_result), "Non-empty tuple is always truthy in Python")
        # Direct unpacking guarantees correct boolean evaluation
        unpacked_allowed, _ = tuple_result
        self.assertFalse(unpacked_allowed)

        # Suspended
        suspended_sub = MagicMock(spec=Subscription)
        suspended_sub.is_active = False
        allowed, reason = SubscriptionService.can_use_ai(suspended_sub)
        self.assertFalse(allowed)
        self.assertEqual(reason, "Subscription suspended.")

        # None / Missing
        allowed, reason = SubscriptionService.can_use_ai(None)
        self.assertFalse(allowed)
        self.assertEqual(reason, "No subscription.")


if __name__ == "__main__":
    unittest.main()

