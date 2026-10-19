import hashlib
import hmac
from urllib.parse import urlsplit

from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, limiter
from models import InvestorProfile, PlatformSetting, User, utcnow
from models.user import PUBLIC_SIGNUP_ROLES, ROLE_INVESTOR
from services.audit_service import audit
from services.notification_service import send_email
from utils.validation import ValidationError, Validator

bp = Blueprint("auth", __name__)

VERIFY_SALT = "email-verify"
RESET_SALT = "password-reset"
VERIFY_MAX_AGE = 60 * 60 * 72
RESET_MAX_AGE = 60 * 60


def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


_DUMMY = {}


def _dummy_password_check(password):
    if "hash" not in _DUMMY:
        _DUMMY["hash"] = generate_password_hash("not-a-real-password")
    check_password_hash(_DUMMY["hash"], password)


def password_fingerprint(user):
    """Changes whenever the password changes, so reset links are single-use."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:20]


def _safe_next(target):
    """Only allow same-site relative redirects (prevents open redirects)."""
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def home_for(user):
    if user.is_admin:
        return url_for("admin.console")
    if user.is_investor:
        return url_for("investors.workspace")
    if user.primary_startup is None:
        return url_for("startups.new_startup")
    return url_for("dashboard.overview")


def _deliver(user, subject, intro, link):
    sent = send_email(user.email, subject, f"Hi {user.name},\n\n{intro}\n\n{link}\n\n— DeeptechIndia.in")
    if not sent and current_app.debug:
        # Development convenience only: SMTP isn't configured, show the link.
        flash(f"Development mode: email not sent. Use this link: {link}", "dev")


def send_verification(user):
    token = _serializer(VERIFY_SALT).dumps({"uid": user.id, "email": user.email})
    link = url_for("auth.verify_email", token=token, _external=True)
    _deliver(user, "Verify your DeeptechIndia.in email", "Confirm your email address to finish setting up:", link)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    errors, values = {}, {}
    if request.method == "POST":
        values = {"email": (request.form.get("email") or "").strip().lower()}
        password = request.form.get("password") or ""
        user = db.session.scalars(select(User).where(User.email == values["email"])).first()
        if user is None:
            _dummy_password_check(password)  # equalise timing for unknown emails
        if user is None or not user.check_password(password) or not user.is_active:
            errors["form"] = "Incorrect email or password."
            current_app.logger.info("Failed login for %s from %s", values["email"], request.remote_addr)
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login_at = utcnow()
            db.session.commit()
            flash(f"Welcome back, {user.name.split()[0]}!", "success")
            return redirect(_safe_next(request.args.get("next")) or home_for(user))
    return render_template("login.html", errors=errors, values=values), (400 if errors else 200)


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    allowed = PlatformSetting.get_bool("allow_new_registrations")
    errors, values = {}, {"role": request.args.get("role", "startup_owner"),
                          "email": (request.args.get("email") or "")[:255]}
    if request.method == "POST" and allowed:
        values = request.form.to_dict()
        v = Validator(request.form)
        v.text("name", "Full name", min_len=2, max_len=120).email("email")
        v.choice("role", "Account type", PUBLIC_SIGNUP_ROLES).password("password", "confirm_password")
        if request.form.get("role") == ROLE_INVESTOR:
            v.text("firm_name", "Firm or investor name", min_len=2, max_len=120)
        if not request.form.get("terms"):
            v.errors["terms"] = "Please accept the terms to continue."
        try:
            data = v.check()
            if db.session.scalars(select(User).where(User.email == data["email"])).first():
                raise ValidationError({"email": "An account with this email already exists. Try signing in."})
        except ValidationError as exc:
            errors = exc.errors
        else:
            user = User(name=data["name"], email=data["email"], role=data["role"])
            user.set_password(data["password"])
            db.session.add(user)
            db.session.flush()
            if user.is_investor:
                db.session.add(InvestorProfile(user_id=user.id, firm_name=data["firm_name"]))
            audit("user.registered", "user", user.id, actor=user, role=user.role)
            db.session.commit()
            send_verification(user)
            login_user(user)
            flash("Account created. Check your inbox to verify your email.", "success")
            return redirect(_safe_next(request.args.get("next")) or home_for(user))
    return render_template("register.html", errors=errors, values=values,
                           registrations_open=allowed), (400 if errors else 200)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("startups.index"))


@bp.route("/verify-email/<token>")
def verify_email(token):
    try:
        data = _serializer(VERIFY_SALT).loads(token, max_age=VERIFY_MAX_AGE)
    except SignatureExpired:
        flash("That verification link has expired. Request a new one below.", "error")
        return redirect(url_for("dashboard.settings") if current_user.is_authenticated else url_for("auth.login"))
    except BadSignature:
        flash("That verification link is invalid.", "error")
        return redirect(url_for("startups.index"))
    user = db.session.get(User, data.get("uid"))
    if user is None or user.email != data.get("email"):
        flash("That verification link is invalid.", "error")
        return redirect(url_for("startups.index"))
    if not user.is_verified:
        user.email_verified_at = utcnow()
        db.session.commit()
    flash("Email verified. Thank you!", "success")
    return redirect(home_for(user) if current_user.is_authenticated else url_for("auth.login"))


@bp.route("/resend-verification", methods=["POST"])
@login_required
@limiter.limit("3 per minute; 10 per day")
def resend_verification():
    if current_user.is_verified:
        flash("Your email is already verified.", "info")
    else:
        send_verification(current_user)
        flash("Verification email sent.", "success")
    return redirect(_safe_next(request.form.get("next")) or url_for("dashboard.settings"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    sent = False
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = db.session.scalars(select(User).where(User.email == email)).first()
        if user and user.is_active:
            token = _serializer(RESET_SALT).dumps({"uid": user.id, "pf": password_fingerprint(user)})
            link = url_for("auth.reset_password", token=token, _external=True)
            _deliver(user, "Reset your DeeptechIndia.in password",
                     "Use this link within one hour to choose a new password:", link)
        # Same response whether or not the account exists (no enumeration).
        sent = True
    return render_template("forgot_password.html", sent=sent)


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def reset_password(token):
    try:
        data = _serializer(RESET_SALT).loads(token, max_age=RESET_MAX_AGE)
    except (SignatureExpired, BadSignature):
        flash("That reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    user = db.session.get(User, data.get("uid"))
    if user is None or not hmac.compare_digest(password_fingerprint(user), str(data.get("pf", ""))):
        flash("That reset link has already been used.", "error")
        return redirect(url_for("auth.forgot_password"))

    errors = {}
    if request.method == "POST":
        try:
            password = Validator(request.form).password("password", "confirm_password").check()["password"]
        except ValidationError as exc:
            errors = exc.errors
        else:
            user.set_password(password)
            audit("user.password_reset", "user", user.id, actor=user)
            db.session.commit()
            flash("Password updated. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("reset_password.html", errors=errors), (400 if errors else 200)
