import os, sys, types, unittest
from unittest.mock import patch

for key, val in dict(MAX_BUNDLES='10', VECTOR_SIZE='768', GEMINI_API_KEY='test',
                     GOOGLE_API_KEY='test', OPENAI_API_KEY='test',
                     DATABASE_URL='sqlite://', GENERAL_SUBSCRIPTION_LAB_ID='1').items():
    os.environ.setdefault(key, val)

_stub = types.ModuleType('utils.embedding_utils')
_stub.build_embedding_text = lambda *a, **k: ''
_stub.create_embedding = lambda *a, **k: []
sys.modules.setdefault('utils.embedding_utils', _stub)

from flask import Flask
from models.models import db, Laboratory, Subscription
from services.shared.subscription_service import BillingError, SubscriptionService
from config import Config


def _make_app():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SECRET_KEY='t', TESTING=True)
    db.init_app(app)
    return app


class Base(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.lab_general = Laboratory(name='General', location='x')
        self.lab_own     = Laboratory(name='OwnSub',  location='x')
        self.lab_no_sub  = Laboratory(name='NoSub',   location='x')
        self.billing_lab = Laboratory(name='BillingLab', location='x')
        db.session.add_all([self.lab_general, self.lab_own, self.lab_no_sub, self.billing_lab])
        db.session.flush()

        self.billing_child = Laboratory(name='Child', location='x',
                                        billing_laboratory_id=self.billing_lab.id)
        db.session.add(self.billing_child)
        db.session.flush()

        self.sub_general = Subscription(laboratory_id=self.lab_general.id,
                                        message_limit=1000, message_used=0,  grace_limit=50)
        self.sub_own     = Subscription(laboratory_id=self.lab_own.id,
                                        message_limit=500,  message_used=10, grace_limit=20)
        self.sub_billing = Subscription(laboratory_id=self.billing_lab.id,
                                        message_limit=2000, message_used=100, grace_limit=50)
        db.session.add_all([self.sub_general, self.sub_own, self.sub_billing])
        db.session.commit()

        self._p = patch.object(Config, 'GENERAL_SUBSCRIPTION_LAB_ID', self.lab_general.id)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()


# 1 - own row is used when it exists
class TestOwnRow(Base):
    def test_own_row_used(self):
        sub = SubscriptionService.get_subscription_by_laboratory_id(self.lab_own.id)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.laboratory_id, self.lab_own.id)
        self.assertEqual(sub.message_limit, 500)


# 2 - billing_laboratory_id redirect
class TestBillingRedirect(Base):
    def test_billing_lab_redirect(self):
        sub = SubscriptionService.get_subscription_by_laboratory_id(self.billing_child.id)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.laboratory_id, self.billing_lab.id)
        self.assertEqual(sub.message_limit, 2000)


# 3 - no own row, no billing redirect -> falls back to general
class TestGeneralFallback(Base):
    def test_falls_back_to_general(self):
        sub = SubscriptionService.get_subscription_by_laboratory_id(self.lab_no_sub.id)
        self.assertIsNotNone(sub)
        self.assertEqual(sub.laboratory_id, self.lab_general.id)
        self.assertEqual(sub.message_limit, 1000)


# 4 - general row also missing -> None
class TestGeneralMissing(Base):
    def test_general_also_missing(self):
        db.session.delete(self.sub_general)
        db.session.commit()
        self.assertIsNone(
            SubscriptionService.get_subscription_by_laboratory_id(self.lab_no_sub.id)
        )


# 5 - billing redirect whose target has no row -> None, no general fallback
class TestBillingTargetMissing(Base):
    def test_billing_id_set_but_billing_lab_has_no_row(self):
        db.session.delete(self.sub_billing)
        db.session.commit()
        self.assertIsNone(
            SubscriptionService.get_subscription_by_laboratory_id(self.billing_child.id)
        )

    def test_can_use_ai_says_no_subscription_not_billing_error(self):
        '''Regression: missing billing row must produce No subscription., not Billing error.'''
        db.session.delete(self.sub_billing)
        db.session.commit()
        allowed, reason = SubscriptionService.can_use_ai(self.billing_child.id)
        self.assertFalse(allowed)
        self.assertEqual(reason, 'No subscription.')


# 6 - DB error -> BillingError raised; can_use_ai returns (False, 'Billing error.')
class TestDbError(Base):
    _TARGET = 'services.shared.subscription_service.db.session.get'

    def test_db_error_raises_billing_error(self):
        from sqlalchemy.exc import OperationalError
        with patch(self._TARGET, side_effect=OperationalError('boom', None, None)):
            with self.assertRaises(BillingError):
                SubscriptionService.get_subscription_by_laboratory_id(self.lab_no_sub.id)

    def test_can_use_ai_catches_billing_error(self):
        from sqlalchemy.exc import OperationalError
        with patch(self._TARGET, side_effect=OperationalError('boom', None, None)):
            allowed, reason = SubscriptionService.can_use_ai(self.lab_no_sub.id)
        self.assertFalse(allowed)
        self.assertEqual(reason, 'Billing error.')


if __name__ == '__main__':
    unittest.main()
