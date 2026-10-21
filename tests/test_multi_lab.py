"""Multi-lab isolation, shared-quota dashboard, 80% alert, branding. Runs on in-memory SQLite."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

# config.py reads these at import time; harmless defaults so the tests run without a .env
os.environ.setdefault("MAX_BUNDLES", "10")
os.environ.setdefault("VECTOR_SIZE", "768")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("GOOGLE_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")

import sys
import types

# utils.embedding_utils builds a real embedding client at import time; stub it so tests need no API access
_stub = types.ModuleType("utils.embedding_utils")
_stub.build_embedding_text = lambda *a, **k: ""
_stub.create_embedding = lambda *a, **k: []
sys.modules.setdefault("utils.embedding_utils", _stub)

from flask import Flask
from flask_login import LoginManager, login_user

from models.models import db, Laboratory, User, Booking, Feedback, Subscription


def make_app():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SECRET_KEY="t", TESTING=True)
    db.init_app(app)
    lm = LoginManager(app)
    lm.user_loader(lambda uid: db.session.get(User, int(uid)))
    return app


class MultiLabBase(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.a = Laboratory(name="Lab A", location="x")
        self.b = Laboratory(name="Lab B", location="x")
        db.session.add_all([self.a, self.b])
        db.session.flush()
        self.c = Laboratory(name="Lab C", location="x", billing_laboratory_id=self.a.id)  # shares A's subscription
        db.session.add(self.c)
        db.session.flush()
        db.session.add_all([
            User(name="admin", password="x", role="admin"),
            User(name="ua", password="x", role="lab_user", laboratory_id=self.a.id),
            User(name="ub", password="x", role="lab_user", laboratory_id=self.b.id),
            User(name="orphan", password="x", role="lab_user", laboratory_id=None),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def as_user(self, name):
        user = User.query.filter_by(name=name).first()
        req = self.app.test_request_context("/")
        req.push()
        self.addCleanup(req.pop)
        login_user(user)


class FeedbackIsolationTest(MultiLabBase):
    def setUp(self):
        super().setUp()
        for ref, lab in (("A1", self.a), ("A2", self.a), ("B1", self.b)):
            db.session.add(Booking(reference_id=ref, name="n", address="x", laboratory_id=lab.id))
            db.session.add(Feedback(reference_id=ref, name="n", phone_number="1",
                                    overall_rating=1 if ref == "A1" else 5, ease_of_use=4))
        db.session.add(Feedback(reference_id="GHOST", name="n", phone_number="1", overall_rating=5, ease_of_use=5))
        db.session.commit()

    def refs(self):
        from services.domain.feedback_service import FeedbackService
        pagination, stats = FeedbackService().get_feedbacks_with_stats()
        return sorted(f.reference_id for f in pagination.items), stats

    def test_lab_user_sees_only_own_lab(self):
        self.as_user("ua")
        refs, stats = self.refs()
        self.assertEqual(refs, ["A1", "A2"])
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["low_ratings"], 1)

    def test_other_lab_cannot_see_it(self):
        self.as_user("ub")
        refs, stats = self.refs()
        self.assertEqual(refs, ["B1"])
        self.assertEqual(stats["total"], 1)

    def test_admin_sees_everything(self):
        self.as_user("admin")
        refs, stats = self.refs()
        self.assertEqual(refs, ["A1", "A2", "B1", "GHOST"])
        self.assertEqual(stats["total"], 4)

    def test_user_without_lab_sees_nothing(self):
        self.as_user("orphan")
        refs, stats = self.refs()
        self.assertEqual(refs, [])
        self.assertEqual(stats["total"], 0)

    def test_direct_lookup_of_other_labs_feedback_is_blocked(self):
        from services.domain.feedback_service import FeedbackService
        self.as_user("ub")
        self.assertIsNone(FeedbackService(reference_id="A1").feedback)
        self.assertIsNotNone(FeedbackService(reference_id="B1").feedback)


class DashboardSubscriptionTest(MultiLabBase):
    def setUp(self):
        super().setUp()
        db.session.add_all([
            Subscription(laboratory_id=self.a.id, message_limit=1000, message_used=300, grace_limit=50),
            Subscription(laboratory_id=self.b.id, message_limit=2000, message_used=500, grace_limit=100),
            # C draws from A, so this idle row must not inflate the total
            Subscription(laboratory_id=self.c.id, message_limit=5000, message_used=0, grace_limit=50),
        ])
        db.session.commit()

    def data(self):
        from services.domain.dashboard_service import DashboardService
        return DashboardService().get_summary_data()

    def test_admin_gets_combined_total_without_idle_shared_row(self):
        self.as_user("admin")
        d = self.data()
        self.assertTrue(d["subscription_is_aggregate"])
        self.assertEqual(d["subscription"].message_limit, 3000)
        self.assertEqual(d["subscription"].message_used, 800)
        self.assertEqual(d["remaining_messages"], 2200)
        self.assertEqual(d["usage_percentage"], 26.7)
        self.assertEqual(d["subscription_status"]["text"], "Active")

    def test_lab_user_sees_own_subscription_not_the_total(self):
        self.as_user("ub")
        d = self.data()
        self.assertNotIn("subscription_is_aggregate", d)
        self.assertEqual(d["subscription"].message_limit, 2000)

    def test_user_without_lab_gets_nothing(self):
        self.as_user("orphan")
        d = self.data()
        self.assertIsNone(d["subscription"])
        self.assertEqual(d["booking_stats"]["total"], 0)

    def test_one_suspended_lab_does_not_mark_the_total_as_down(self):
        Subscription.query.filter_by(laboratory_id=self.b.id).update({"is_active": False})
        db.session.commit()
        self.as_user("admin")
        d = self.data()
        self.assertEqual(d["subscription_status"]["text"], "Active")
        self.assertIn("Lab B", d["aggregate_notice"])
        self.assertNotIn("Lab A", d["aggregate_notice"])

    def test_all_suspended_marks_the_total_as_suspended(self):
        Subscription.query.update({"is_active": False})
        db.session.commit()
        self.as_user("admin")
        d = self.data()
        self.assertEqual(d["subscription_status"]["text"], "Suspended")
        self.assertEqual(d["aggregate_notice"], "")


class UsageAlertTest(MultiLabBase):
    def setUp(self):
        super().setUp()
        self.sub = Subscription(laboratory_id=self.a.id, message_limit=100, message_used=0, grace_limit=10)
        db.session.add(self.sub)
        db.session.commit()

    def bump(self, to):
        from services.shared.subscription_service import SubscriptionService
        self.sub.message_used = to
        db.session.commit()
        with patch("notification_center.send_production_alert") as alert:
            SubscriptionService._maybe_send_usage_alert(self.sub)
        return alert

    def test_no_alert_below_80(self):
        self.assertFalse(self.bump(79).called)

    def test_alert_once_at_80_and_not_again(self):
        first = self.bump(80)
        self.assertEqual(first.call_count, 1)
        context = first.call_args.kwargs["context"]
        self.assertIn("Lab A", context["labs_using_it"])
        self.assertIn("Lab C", context["labs_using_it"])  # lab sharing the subscription is named
        self.assertFalse(self.bump(85).called)
        self.assertFalse(self.bump(100).called)

    def test_reset_rearms_the_alert(self):
        from services.shared.subscription_service import SubscriptionService
        self.bump(90)
        SubscriptionService(subscription=self.sub).reset_usage()
        self.assertFalse(Subscription.query.get(self.sub.id).usage_alert_sent)
        self.assertEqual(self.bump(80).call_count, 1)

    def test_raising_limit_rearms_only_when_below_threshold(self):
        from services.shared.subscription_service import SubscriptionService
        self.bump(90)
        SubscriptionService(subscription=self.sub).update_limit(500)  # 90/500 = 18%
        self.assertFalse(Subscription.query.get(self.sub.id).usage_alert_sent)

    def test_alert_failure_never_raises(self):
        from services.shared.subscription_service import SubscriptionService
        self.sub.message_used = 95
        db.session.commit()
        with patch("notification_center.send_production_alert", side_effect=RuntimeError("smtp down")):
            SubscriptionService._maybe_send_usage_alert(self.sub)  # must not raise


class BrandingTest(unittest.TestCase):
    def test_comment_replies_use_lab_name(self):
        from platforms.facebook import comments
        self.assertIn("Lab B", comments.public_reply("Lab B"))
        self.assertIn("Lab B", comments.private_reply("Lab B"))
        self.assertNotIn("الصدارة", comments.public_reply())
        self.assertIn("المعمل", comments.private_reply(None))

    def test_no_hardcoded_sadara_in_templates_or_code(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in list(root.glob("templates/**/*.html")) + list(root.glob("platforms/**/*.py")) + \
                list(root.glob("routes/*.py")) + list(root.glob("graph/**/*.py")):
            text = path.read_text(encoding="utf-8")
            if "صدارة" in text or "الصدارة" in text or "01006446508" in text:
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [])

    def test_templates_parse(self):
        import pathlib
        from jinja2 import Environment, FileSystemLoader
        root = pathlib.Path(__file__).resolve().parent.parent / "templates"
        env = Environment(loader=FileSystemLoader(str(root)))
        env.globals.update(url_for=lambda *a, **k: "/", current_user=None, get_flashed_messages=lambda **k: [])
        for path in root.glob("**/*.html"):
            env.get_template(str(path.relative_to(root)))  # raises TemplateSyntaxError


if __name__ == "__main__":
    unittest.main()
