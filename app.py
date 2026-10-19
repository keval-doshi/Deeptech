"""DeeptechIndia.in Flask application factory.

Development:  flask --app app run --debug
Production:   gunicorn -c gunicorn.conf.py "app:create_app()"
"""
import logging
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # must run before config reads the environment

from flask import Flask, render_template, request  # noqa: E402
from flask_login import current_user  # noqa: E402
from flask_wtf.csrf import CSRFError  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from config import CONFIGS  # noqa: E402
from extensions import csrf, db, limiter, login_manager, migrate  # noqa: E402
from utils.formatting import register_filters  # noqa: E402
from utils.security import apply_security_headers, json_error, wants_json  # noqa: E402


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("APP_ENV", "development")
    config_class = CONFIGS[config_name]
    if config_name == "production":
        problems = config_class.validate()
        if problems:
            raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(problems))

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.config.update(overrides or {})
    app.config["ENV_NAME"] = config_name
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    if config_name == "production":
        # Trust one reverse proxy (nginx / load balancer) for scheme and client IP.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configure_logging(app)
    _init_monitoring(app)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "basic"

    import models  # noqa: F401  (registers every table)
    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id)) if str(user_id).isdigit() else None
        return user if user and user.is_active else None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import flash, redirect, url_for
        if wants_json():
            return json_error("Sign in required.", 401)
        flash(login_manager.login_message, "info")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    _register_blueprints(app)
    register_filters(app)
    _register_context(app)
    _register_error_handlers(app)

    @app.after_request
    def security_headers(response):
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return apply_security_headers(response, https=config_name == "production")

    from commands import register_commands
    register_commands(app)
    return app


def _register_blueprints(app):
    from routes.admin import bp as admin_bp
    from routes.auth import bp as auth_bp
    from routes.bidding import bp as bidding_bp
    from routes.categories import bp as categories_bp
    from routes.dashboard import api as notifications_bp
    from routes.dashboard import bp as dashboard_bp
    from routes.funding import bp as funding_bp
    from routes.investors import bp as investors_bp
    from routes.payments import bp as payments_bp
    from routes.startups import bp as startups_bp
    from routes.team import bp as team_bp

    for blueprint in (startups_bp, auth_bp, categories_bp, funding_bp, investors_bp,
                      dashboard_bp, notifications_bp, team_bp, bidding_bp, payments_bp, admin_bp):
        app.register_blueprint(blueprint)


def _register_context(app):
    from sqlalchemy import func, select

    from models import Category, Notification

    @app.context_processor
    def inject_globals():
        unread = 0
        if current_user.is_authenticated:
            unread = db.session.scalar(
                select(func.count(Notification.id)).where(Notification.user_id == current_user.id,
                                                          Notification.read_at.is_(None))
            ) or 0
        nav_categories = db.session.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
        return {
            "site_name": app.config["SITE_NAME"],
            "nav_categories": nav_categories,
            "unread_notifications": unread,
            "payment_provider": app.config["PAYMENT_PROVIDER"],
            "current_year": date.today().year,
        }


def _register_error_handlers(app):
    def render_error(status, title, message):
        if wants_json():
            return json_error(message, status)
        return render_template("error.html", status=status, title=title, message=message), status

    @app.errorhandler(400)
    def bad_request(e):
        return render_error(400, "Bad request", getattr(e, "description", "The request could not be understood."))

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_error(400, "Session expired", "Your form expired. Reload the page and try again.")

    @app.errorhandler(403)
    def forbidden(e):
        return render_error(403, "Access denied", "You don't have permission to view this page.")

    @app.errorhandler(404)
    def not_found(e):
        return render_error(404, "Page not found", "We couldn't find what you were looking for.")

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_error(405, "Not allowed", "That action isn't supported here.")

    @app.errorhandler(413)
    def too_large(e):
        return render_error(413, "Upload too large", "Files must be smaller than 8 MB in total.")

    @app.errorhandler(429)
    def rate_limited(e):
        return render_error(429, "Slow down", "Too many attempts. Please wait a minute and try again.")

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_error(500, "Something went wrong", "Our team has been notified. Please try again shortly.")


def _configure_logging(app):
    level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _init_monitoring(app):
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return
    sentry_sdk.init(dsn=dsn, integrations=[FlaskIntegration()], traces_sample_rate=0.1, send_default_pii=False)
