"""Admin console. Every state-changing action is audit-logged."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from extensions import db, limiter
from models import (AuditLog, Bid, InvestorProfile, IntroductionRequest, Payment, PlatformSetting, RankingPosition, Startup,
                    User, WebhookEvent, utcnow)
from models.startup import STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED
from models.user import ROLE_ADMIN, ROLES
from services import payment_service, ranking_service
from services.audit_service import audit
from services.notification_service import notify, notify_startup
from utils.security import roles_required
from utils.validation import ValidationError, Validator

bp = Blueprint("admin", __name__, url_prefix="/admin")

admin_only = roles_required(ROLE_ADMIN)


@bp.route("")
@login_required
@admin_only
def console():
    def count(model, *where):
        return db.session.scalar(select(func.count()).select_from(model).where(*where))

    stats = {
        "users": count(User),
        "startups": count(Startup, Startup.status == STATUS_PUBLISHED),
        "pending": count(Startup, Startup.status == STATUS_PENDING),
        "intros": count(IntroductionRequest),
        "revenue": db.session.scalar(select(func.coalesce(func.sum(Payment.amount_paise), 0))
                                     .where(Payment.status == "paid")) // 100,
        "active_bids": count(Bid, Bid.status == "active"),
    }
    pending = db.session.scalars(select(Startup).where(Startup.status == STATUS_PENDING)
                                 .order_by(Startup.created_at)).all()
    startups = db.session.scalars(select(Startup).where(Startup.status != STATUS_PENDING)
                                  .order_by(Startup.name).limit(200)).all()
    ranking = db.session.scalars(select(RankingPosition).order_by(RankingPosition.position)).all()
    payments = db.session.scalars(select(Payment).order_by(Payment.created_at.desc()).limit(50)).all()
    webhooks = db.session.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(30)).all()
    users = db.session.scalars(select(User).order_by(User.created_at.desc()).limit(50)).all()
    logs = db.session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(60)).all()
    settings = {key: PlatformSetting.get_bool(key) for key in PlatformSetting.DEFAULTS}
    investors = db.session.scalars(select(InvestorProfile).join(User, User.id == InvestorProfile.user_id)
                                   .where(User.active.is_(True))
                                   .order_by(InvestorProfile.is_verified, InvestorProfile.created_at.desc())).all()
    stats["unverified_investors"] = sum(1 for i in investors if not i.is_verified)
    return render_template("admin.html", stats=stats, pending=pending, startups=startups, ranking=ranking,
                           payments=payments, webhooks=webhooks, users=users, logs=logs,
                           rules=ranking_service.get_rules(), settings=settings, roles=ROLES, investors=investors)


@bp.post("/startups/<int:startup_id>/action")
@login_required
@admin_only
@limiter.limit("120 per hour")
def startup_action(startup_id):
    startup = db.session.get(Startup, startup_id) or abort(404)
    action = request.form.get("action")
    affects_ranking = False
    if action == "approve":
        startup.status = STATUS_PUBLISHED
        startup.published_at = startup.published_at or utcnow()
        startup.rejection_reason = None
        notify_startup(startup.id, "Your startup is live!", f"{startup.name} is now listed publicly.",
                       f"/startups/{startup.slug}", "review")
        affects_ranking = True
    elif action == "reject":
        reason = (request.form.get("reason") or "").strip()[:300] or "Listing does not meet our guidelines."
        startup.status = STATUS_REJECTED
        startup.rejection_reason = reason
        notify_startup(startup.id, "Listing needs changes", reason, "/dashboard/profile", "review")
        affects_ranking = True
    elif action == "unpublish":
        startup.status = STATUS_PENDING
        affects_ranking = True
    elif action in ("verify", "unverify"):
        startup.is_verified = action == "verify"
    elif action in ("pick", "unpick"):
        startup.investor_pick = action == "pick"
    else:
        abort(400)
    audit(f"admin.startup.{action}", "startup", startup.id, actor=current_user)
    if affects_ranking:
        ranking_service.recompute_rankings(ranking_service.get_rules(lock=True))
    db.session.commit()
    flash(f"{startup.name}: {action} done.", "success")
    return redirect(request.referrer or url_for("admin.console"))


@bp.post("/investors/<int:investor_id>/action")
@login_required
@admin_only
@limiter.limit("120 per hour")
def investor_action(investor_id):
    profile = db.session.get(InvestorProfile, investor_id) or abort(404)
    action = request.form.get("action")
    if action not in ("verify", "unverify"):
        abort(400)
    profile.is_verified = action == "verify"
    if profile.is_verified:
        notify(profile.user_id, "Your investor profile is verified",
               "Founders now see a Verified investor badge on your introduction requests.", "/investors", "review")
    audit(f"admin.investor.{action}", "investor_profile", profile.id, actor=current_user, firm=profile.firm_name)
    db.session.commit()
    flash(f"{profile.firm_name}: {'verified' if profile.is_verified else 'verification removed'}.", "success")
    return redirect(url_for("admin.console") + "#investors")


@bp.post("/rules")
@login_required
@admin_only
def update_rules():
    v = Validator(request.form)
    v.integer("opening_bid", "Opening bid", required=True, min_value=1, max_value=10_00_000)
    v.integer("increment", "Increment", required=True, min_value=1, max_value=10_00_000)
    v.integer("max_bid", "Maximum bid", required=True, min_value=1, max_value=1_00_00_000)
    v.integer("max_positions", "Paid positions", required=True, min_value=1, max_value=50)
    v.integer("ranking_period_days", "Ranking period", required=True, min_value=1, max_value=365)
    v.integer("checkout_ttl_minutes", "Checkout window", required=True, min_value=5, max_value=120)
    v.boolean("bidding_enabled")
    try:
        data = v.check()
    except ValidationError as exc:
        flash("Rules not saved: " + "; ".join(exc.errors.values()), "error")
        return redirect(url_for("admin.console") + "#rules")
    rules = ranking_service.get_rules(lock=True)
    before = rules.to_dict()
    rules.opening_bid_paise = data["opening_bid"] * 100
    rules.increment_paise = data["increment"] * 100
    rules.max_bid_paise = data["max_bid"] * 100
    rules.max_positions = data["max_positions"]
    rules.ranking_period_days = data["ranking_period_days"]
    rules.checkout_ttl_minutes = data["checkout_ttl_minutes"]
    rules.bidding_enabled = data["bidding_enabled"]
    rules.updated_by_id = current_user.id
    ranking_service.recompute_rankings(rules)
    audit("admin.bidding_rules.updated", "bidding_rules", 1, actor=current_user, before=before, after=rules.to_dict())
    db.session.commit()
    flash("Bidding rules updated.", "success")
    return redirect(url_for("admin.console") + "#rules")


@bp.post("/settings")
@login_required
@admin_only
def update_settings():
    changes = {}
    for key in PlatformSetting.DEFAULTS:
        value = "true" if request.form.get(key) else "false"
        PlatformSetting.set(key, value)
        changes[key] = value
    audit("admin.settings.updated", "platform_settings", None, actor=current_user, **changes)
    db.session.commit()
    flash("Platform settings saved.", "success")
    return redirect(url_for("admin.console") + "#settings")


@bp.post("/users/<int:user_id>/update")
@login_required
@admin_only
def update_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't change your own account here.", "error")
        return redirect(url_for("admin.console") + "#users")
    action = request.form.get("action")
    if action == "toggle_active":
        user.active = not user.active
    elif action == "set_role" and request.form.get("role") in ROLES:
        user.role = request.form["role"]
    else:
        abort(400)
    audit(f"admin.user.{action}", "user", user.id, actor=current_user, active=user.active, role=user.role)
    db.session.commit()
    flash(f"Updated {user.email}.", "success")
    return redirect(url_for("admin.console") + "#users")


@bp.post("/rankings/recompute")
@login_required
@admin_only
def recompute():
    changes = ranking_service.recompute_rankings(ranking_service.get_rules(lock=True))
    audit("admin.rankings.recomputed", "ranking", None, actor=current_user, changes=len(changes))
    db.session.commit()
    flash(f"Rankings rebuilt ({len(changes)} changes).", "success")
    return redirect(url_for("admin.console") + "#ranking")


@bp.post("/payments/<int:payment_id>/reconcile")
@login_required
@admin_only
def reconcile(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    status = payment_service.reconcile(payment)
    audit("admin.payment.reconciled", "payment", payment.id, actor=current_user, status=status)
    db.session.commit()
    flash(f"Payment {payment.receipt}: {status}.", "info")
    return redirect(url_for("admin.console") + "#payments")
