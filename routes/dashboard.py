"""Startup owner dashboard: overview, company profile, payments, account settings."""
from datetime import date, timedelta

import json

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy import func, select

from extensions import db, limiter
from models import Category, IntroductionRequest, Notification, Payment, StartupView, utcnow
from models.funding import FUNDING_STAGES
from models.startup import TEAM_SIZES
from services import account_service, bidding_service
from services.audit_service import audit
from utils.validation import ValidationError, Validator

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def view_stats(startup_id, days=30):
    today = date.today()
    start = today - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    rows = dict(db.session.execute(
        select(StartupView.day, StartupView.views)
        .where(StartupView.startup_id == startup_id, StartupView.day >= prev_start)).all())
    current = sum(v for d, v in rows.items() if d >= start)
    previous = sum(v for d, v in rows.items() if d < start)
    change = round((current - previous) * 100 / previous) if previous else (100 if current else 0)
    series = [{"day": (start + timedelta(days=i)).isoformat(), "views": rows.get(start + timedelta(days=i), 0)}
              for i in range(days)]
    return {"views": current, "previous": previous, "change_pct": change, "series": series}


def completeness(startup):
    checks = [
        ("Logo", bool(startup.logo_path)),
        ("Cover image", bool(startup.cover_path)),
        ("Description", len(startup.description or "") >= 200),
        ("Website", bool(startup.website)),
        ("Founders", bool(startup.founders)),
        ("Products", bool(startup.products)),
        ("Gallery", len(startup.gallery) >= 3),
        ("Funding details", bool(startup.funding and startup.funding.stage)),
    ]
    done = sum(1 for _, ok in checks if ok)
    return {"percent": round(done * 100 / len(checks)), "missing": [label for label, ok in checks if not ok]}


def _dashboard_startup():
    """Startup for the signed-in owner, or a redirect for other account types."""
    if current_user.is_admin:
        return None, redirect(url_for("admin.console"))
    if current_user.is_investor:
        return None, redirect(url_for("investors.workspace"))
    startup = current_user.primary_startup
    if startup is None:
        return None, redirect(url_for("startups.new_startup"))
    return startup, None


@bp.route("")
@login_required
def overview():
    startup, redirect_response = _dashboard_startup()
    if redirect_response:
        return redirect_response
    position, amount = bidding_service.current_position(startup.id)
    intros = db.session.scalars(
        select(IntroductionRequest).where(IntroductionRequest.startup_id == startup.id)
        .order_by(IntroductionRequest.created_at.desc()).limit(10)).all()
    notifications = db.session.scalars(
        select(Notification).where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc()).limit(6)).all()
    return render_template("dashboard.html", startup=startup, position=position,
                           current_bid=amount // 100 if amount else None, stats=view_stats(startup.id),
                           completeness=completeness(startup), intros=intros, notifications=notifications,
                           active="dashboard")


@bp.route("/profile")
@login_required
def company_profile():
    startup, redirect_response = _dashboard_startup()
    if redirect_response:
        return redirect_response
    categories = db.session.scalars(select(Category).order_by(Category.sort_order)).all()
    return render_template("profile_edit.html", startup=startup, categories=categories, team_sizes=TEAM_SIZES,
                           stages=FUNDING_STAGES, completeness=completeness(startup), active="profile")


@bp.route("/payments")
@login_required
def payments():
    startup, redirect_response = _dashboard_startup()
    if redirect_response:
        return redirect_response
    if not current_user.is_startup_owner_member:
        abort(403)  # payment records are visible to owners only
    rows = db.session.scalars(select(Payment).where(Payment.startup_id == startup.id)
                              .order_by(Payment.created_at.desc()).limit(100)).all()
    total_paid = db.session.scalar(select(func.coalesce(func.sum(Payment.amount_paise), 0))
                                   .where(Payment.startup_id == startup.id, Payment.status == "paid"))
    return render_template("payments.html", startup=startup, payments=rows, total_paid=total_paid,
                           active="payments")


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per hour", methods=["POST"])
def settings():
    errors = {}
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            try:
                data = Validator(request.form).text("name", "Full name", min_len=2, max_len=120).check()
            except ValidationError as exc:
                errors = exc.errors
            else:
                current_user.name = data["name"]
                db.session.commit()
                flash("Profile updated.", "success")
                return redirect(url_for("dashboard.settings"))
        elif action == "password":
            if not current_user.check_password(request.form.get("current_password") or ""):
                errors["current_password"] = "Current password is incorrect."
            else:
                try:
                    data = Validator(request.form).password("password", "confirm_password").check()
                except ValidationError as exc:
                    errors = exc.errors
                else:
                    current_user.set_password(data["password"])
                    audit("user.password_changed", "user", current_user.id, actor=current_user)
                    db.session.commit()
                    flash("Password changed.", "success")
                    return redirect(url_for("dashboard.settings"))
    return render_template("settings.html", errors=errors, active="settings",
                           startup=current_user.primary_startup), (400 if errors else 200)


@bp.get("/settings/export")
@login_required
@limiter.limit("5 per hour")
def export_data():
    """Download everything we hold about the signed-in person (DPDP Act)."""
    data = account_service.export_user_data(current_user)
    audit("user.data_exported", "user", current_user.id, actor=current_user)
    db.session.commit()
    response = current_app.response_class(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                                          mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="deeptechindia-my-data.json"'
    return response


@bp.post("/settings/delete")
@login_required
@limiter.limit("5 per hour")
def delete_account():
    errors = {}
    if not current_user.check_password(request.form.get("delete_password") or ""):
        errors["delete_password"] = "Password is incorrect."
    if (request.form.get("delete_confirm") or "").strip() != "DELETE":
        errors["delete_confirm"] = "Type DELETE (in capitals) to confirm."
    if not errors:
        try:
            account_service.delete_account(current_user)
        except account_service.AccountError as exc:
            errors["delete_form"] = str(exc)
    if errors:
        db.session.rollback()
        return render_template("settings.html", errors=errors, active="settings",
                               startup=current_user.primary_startup), 400
    db.session.commit()
    logout_user()
    flash("Your account and personal data have been deleted. We're sorry to see you go.", "info")
    return redirect(url_for("startups.index"))


# ---- Notifications API ----------------------------------------------------

api = Blueprint("notifications", __name__)


@api.get("/api/notifications")
@login_required
def api_notifications():
    items = db.session.scalars(select(Notification).where(Notification.user_id == current_user.id)
                               .order_by(Notification.created_at.desc()).limit(20)).all()
    unread = sum(1 for n in items if n.read_at is None)
    return jsonify({"ok": True, "items": [n.to_dict() for n in items], "unread": unread})


@api.post("/api/notifications/read")
@login_required
def api_notifications_read():
    db.session.execute(
        Notification.__table__.update()
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow()))
    db.session.commit()
    return jsonify({"ok": True})
