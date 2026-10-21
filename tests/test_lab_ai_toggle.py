"""Per-lab AI stop/activate on the laboratories page (admin only, shared subscriptions)."""
import os
import sys
import types
import unittest

for key, value in dict(MAX_BUNDLES="10", VECTOR_SIZE="768", GEMINI_API_KEY="t", GOOGLE_API_KEY="t",
                       OPENAI_API_KEY="t", DATABASE_URL="sqlite://").items():
    os.environ.setdefault(key, value)
_stub = types.ModuleType("utils.embedding_utils")
_stub.build_embedding_text = lambda *a, **k: ""
_stub.create_embedding = lambda *a, **k: []
sys.modules.setdefault("utils.embedding_utils", _stub)

from app import create_app
from models.models import db, Laboratory, User, Subscription


class LabAiToggleTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            a = Laboratory(name="Lab A", location="x")
            b = Laboratory(name="Lab B", location="x")
            db.session.add_all([a, b])
            db.session.flush()
            c = Laboratory(name="Lab C", location="x", billing_laboratory_id=a.id)
            db.session.add(c)
            db.session.flush()
            db.session.add_all([
                Subscription(laboratory_id=a.id, message_limit=100, message_used=10),
                Subscription(laboratory_id=b.id, message_limit=100, message_used=10),
                User(name="admin", password="x", role="admin"),
                User(name="ua", password="x", role="lab_user", laboratory_id=a.id),
            ])
            db.session.commit()
            self.ids = {"a": a.id, "b": b.id, "c": c.id}
            self.uid = {u.name: u.id for u in User.query.all()}

    def client(self, name):
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["_user_id"] = str(self.uid[name])
            s["_fresh"] = True
        return c

    def active(self, key):
        with self.app.app_context():
            return Subscription.query.filter_by(laboratory_id=self.ids[key]).first().is_active

    def test_suspending_a_lab_stops_only_its_own_subscription(self):
        r = self.client("admin").post(f"/laboratories/{self.ids['b']}/ai/suspend")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(self.active("b"))
        self.assertTrue(self.active("a"))

    def test_lab_that_bills_to_another_stops_the_shared_subscription(self):
        self.client("admin").post(f"/laboratories/{self.ids['c']}/ai/suspend")
        self.assertFalse(self.active("a"))  # C pays through A's subscription
        self.assertTrue(self.active("b"))

    def test_activate_restores_it(self):
        admin = self.client("admin")
        admin.post(f"/laboratories/{self.ids['b']}/ai/suspend")
        admin.post(f"/laboratories/{self.ids['b']}/ai/activate")
        self.assertTrue(self.active("b"))

    def test_lab_user_is_forbidden(self):
        r = self.client("ua").post(f"/laboratories/{self.ids['b']}/ai/suspend")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(self.active("b"))

    def test_list_page_renders_status_for_every_lab(self):
        html = self.client("admin").get("/laboratories/").get_data(as_text=True)
        self.assertIn("يعمل", html)
        self.assertIn("بيسحب من اشتراك Lab A", html)
        self.assertIn("اشتراكه مشترك مع: Lab C", html)


if __name__ == "__main__":
    unittest.main()
