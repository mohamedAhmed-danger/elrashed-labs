from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate

from config import Config
from models.models import db, User
from routes.login_routes import main_bp
from routes.user_routes import users_bp
from routes.platform_routes import platforms_bp
from routes.subscription_routes import subscription_bp
from routes.test_routes import test_bp
from routes.laboratory_routes import laboratory_bp
from routes.booking_routes import bookings_bp
from routes.complaint_routes import complaints_bp
from routes.feedback_routes import feedbacks_bp
from routes.inquiry_routes import inquiries_bp
from routes.page_routes import pages_bp
from routes.gmail_routes import gmail_auth_bp
from routes.webhook_routes import webhook_bp
from routes.bundle_routes import bundle_bp
from routes.health_routes import health_bp
from routes.public_routes import public_bp
from routes.results import bp as results_bp


import logging
from logging.handlers import RotatingFileHandler
import os

def setup_app_logging(app):
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "DEBUG").upper(), logging.DEBUG)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True
    )
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "elrashed.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        app.logger.addHandler(file_handler)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    setup_app_logging(app)

    # تأكيد وجود secret_key للـ Sessions (لو مش محدد في Config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "elrashed_super_secret_key_2026"

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)  

    login_manager = LoginManager()
    login_manager.login_view = "main.login"
    login_manager.login_message = "يرجى تسجيل الدخول للوصول إلى هذه الصفحة"
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(platforms_bp)
    app.register_blueprint(subscription_bp)
    app.register_blueprint(test_bp)
    app.register_blueprint(laboratory_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(feedbacks_bp)
    app.register_blueprint(inquiries_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(gmail_auth_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(bundle_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(results_bp)

    # Operational blueprints handled strictly by individual lab accounts
    OPERATIONAL_BLUEPRINTS = {"bookings", "inquiries", "complaints", "results"}

    # Blueprints accessible by lab users (their operational routes + shared catalogs)
    LAB_USER_BLUEPRINTS = {
        "main", "bookings", "complaints", "feedbacks", "inquiries",
        "public", "webhook", "results", "test", "bundle"
    }

    @app.before_request
    def enforce_role_access():
        from flask import request, abort
        from flask_login import current_user
        if not current_user.is_authenticated:
            return None
        if request.endpoint is None or request.endpoint == "static":
            return None

        # Admin is not allowed to access lab operational routes (bookings, inquiries, complaints, results)
        if current_user.is_admin:
            if request.blueprint in OPERATIONAL_BLUEPRINTS:
                abort(403)
            return None

        # Lab user may only access their operational routes and shared catalogs
        if request.blueprint not in LAB_USER_BLUEPRINTS:
            abort(403)
        return None

    # Context processor for sidebar badges and layout counters
    @app.context_processor
    def inject_global_counts():
        from flask_login import current_user
        # Admins do not handle lab operations; suppress operational badges for admin
        if not current_user.is_authenticated or current_user.is_admin:
            return dict(
                pending_inquiries_count=0,
                pending_results_count=0,
                lab_brand={"name": None, "logo": None},
            )

        try:
            from services.domain.inquiry_service import InquiryService
            count = InquiryService.get_pending_inquiries_count()
        except Exception:
            count = 0
        try:
            from services.domain.result_service import ResultService
            res_count = ResultService.count_pending()
        except Exception:
            res_count = 0
        brand = {"name": None, "logo": None}
        try:
            lab = getattr(current_user, "laboratory", None)
            if lab:
                brand["name"] = lab.name
                if lab.logo_path:
                    brand["logo"] = lab.logo_path.lstrip("/")
        except Exception:
            pass
        return dict(
            pending_inquiries_count=count,
            pending_results_count=res_count,
            lab_brand=brand,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)