"""Application configuration.

All secrets and environment-specific values come from environment variables
(see .env.example). Nothing secret is hard-coded here.
"""
import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _database_url():
    url = os.environ.get("DATABASE_URL", "")
    # Some hosts still hand out the legacy "postgres://" scheme.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url or "sqlite:///" + os.path.join(BASE_DIR, "instance", "deeptechindia.db")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")
    SITE_NAME = "DeeptechIndia.in"
    SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:5000")

    # Database
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Sessions & cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)

    # CSRF
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8
    WTF_CSRF_HEADERS = ["X-CSRFToken", "X-CSRF-Token"]

    # Uploads
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # whole request
    MAX_IMAGE_BYTES = 5 * 1024 * 1024  # single image
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # Rate limiting (use Redis in production: redis://host:6379/0)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    RATELIMIT_HEADERS_ENABLED = True

    # Email (SMTP). When MAIL_SERVER is empty, emails are written to the log.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", True)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "DeeptechIndia <no-reply@deeptechindia.in>")

    # Payments: "mock" (local sandbox simulator) or "razorpay"
    PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "mock")
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    MOCK_WEBHOOK_SECRET = os.environ.get("MOCK_WEBHOOK_SECRET", "mock-webhook-secret")

    # Monitoring
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")



class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    PAYMENT_PROVIDER = "mock"
    MAIL_SERVER = ""


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        problems = []
        if cls.SECRET_KEY.startswith("dev-only") or len(cls.SECRET_KEY) < 32:
            problems.append("SECRET_KEY must be set to a long random value")
        if cls.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
            problems.append("DATABASE_URL must point to PostgreSQL in production")
        if cls.PAYMENT_PROVIDER == "mock":
            problems.append("PAYMENT_PROVIDER=mock is not allowed in production")
        if cls.PAYMENT_PROVIDER == "razorpay" and not (
            cls.RAZORPAY_KEY_ID and cls.RAZORPAY_KEY_SECRET and cls.RAZORPAY_WEBHOOK_SECRET
        ):
            problems.append("Razorpay keys and webhook secret are required")
        if cls.RATELIMIT_STORAGE_URI.startswith("memory"):
            problems.append("RATELIMIT_STORAGE_URI should use Redis when running multiple workers")
        return problems


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
