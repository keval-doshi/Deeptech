"""Personal-data rights (India's DPDP Act 2023): export and account deletion.

Deletion erases personal data and disables sign-in. Records that the law
requires us to keep (payments, and the bids they paid for) are retained but
detached from the person: the user row is anonymised rather than removed so
foreign keys in financial and audit records stay valid.
"""
import secrets

from sqlalchemy import func, select

from extensions import db
from models import (AuditLog, Bid, IntroductionRequest, Notification, Payment,
                    RankingEvent, RankingPosition, SavedStartup, Startup, StartupInvite, StartupView, User, utcnow)
from models.bid import BID_ACTIVE, BID_CANCELLED, BID_EXPIRED, BID_PENDING
from models.payment import PAY_CANCELLED, PAY_CREATED
from models.startup import STATUS_DRAFT
from models.user import ROLE_ADMIN
from services import ranking_service
from services.audit_service import audit
from services.notification_service import notify
from utils.uploads import delete_image


class AccountError(Exception):
    pass


def _iso(dt):
    return dt.isoformat() if dt else None


def export_user_data(user):
    """Everything we hold about this person, as a JSON-serialisable dict."""
    data = {
        "generated_at": _iso(utcnow()),
        "account": {"name": user.name, "email": user.email, "role": user.role, "created_at": _iso(user.created_at),
                    "email_verified_at": _iso(user.email_verified_at), "last_login_at": _iso(user.last_login_at)},
        "startups": [],
        "saved_startups": [s.startup.name for s in db.session.scalars(
            select(SavedStartup).where(SavedStartup.user_id == user.id))],
        "notifications": [n.to_dict() for n in db.session.scalars(
            select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at))],
        "activity_log": [{"action": a.action, "at": _iso(a.created_at), "ip_address": a.ip_address}
                         for a in db.session.scalars(select(AuditLog).where(AuditLog.actor_id == user.id)
                                                     .order_by(AuditLog.created_at))],
    }
    for membership in user.memberships:
        startup = membership.startup
        entry = {"role": membership.role, "profile": startup.to_profile(), "status": startup.status,
                 "introduction_requests": [i.to_dict(for_startup=True) for i in db.session.scalars(
                     select(IntroductionRequest).where(IntroductionRequest.startup_id == startup.id))]}
        if membership.role == "owner":
            entry["bids"] = [{"id": b.id, "target_position": b.target_position, "amount_inr": b.amount_rupees,
                              "status": b.status, "created_at": _iso(b.created_at), "paid_at": _iso(b.paid_at)}
                             for b in db.session.scalars(select(Bid).where(Bid.startup_id == startup.id))]
            entry["payments"] = [p.to_dict() for p in db.session.scalars(
                select(Payment).where(Payment.startup_id == startup.id))]
        data["startups"].append(entry)
    if user.investor_profile:
        profile = user.investor_profile
        data["investor_profile"] = {**profile.to_public(), "check_min_inr": profile.check_min_inr,
                                    "check_max_inr": profile.check_max_inr}
        data["introduction_requests_sent"] = [i.to_dict() for i in db.session.scalars(
            select(IntroductionRequest).where(IntroductionRequest.investor_id == profile.id))]
    return data


def _retire_startup(startup, actor):
    """Take a startup down when its last team member leaves."""
    for bid in db.session.scalars(select(Bid).where(Bid.startup_id == startup.id, Bid.status == BID_PENDING)):
        bid.status = BID_CANCELLED
        for payment in bid.payments:
            if payment.status == PAY_CREATED:
                payment.status = PAY_CANCELLED
    has_payments = db.session.scalar(select(func.count(Payment.id)).where(Payment.startup_id == startup.id)) > 0
    if has_payments:
        # Payment records must be kept: unlist the company instead of deleting it.
        startup.status = STATUS_DRAFT
        startup.is_verified = False
        startup.investor_pick = False
        for bid in db.session.scalars(select(Bid).where(Bid.startup_id == startup.id, Bid.status == BID_ACTIVE)):
            bid.status = BID_EXPIRED
        audit("startup.unlisted_on_account_deletion", "startup", startup.id, actor=actor)
        return "unlisted"
    for path in [startup.logo_path, startup.cover_path] + \
            [f.photo_path for f in startup.founders] + [p.image_path for p in startup.products] + \
            [g.image_path for g in startup.gallery]:
        delete_image(path)
    for model in (RankingPosition, RankingEvent, Bid, SavedStartup, StartupView, IntroductionRequest, StartupInvite):
        db.session.execute(model.__table__.delete().where(model.__table__.c.startup_id == startup.id))
    audit("startup.deleted_on_account_deletion", "startup", startup.id, actor=actor, name=startup.name)
    db.session.delete(startup)
    return "deleted"


def delete_account(user):
    """Erase a user's personal data and disable the account. Caller commits."""
    if user.is_admin:
        admins = db.session.scalar(select(func.count(User.id)).where(User.role == ROLE_ADMIN, User.active.is_(True)))
        if admins <= 1:
            raise AccountError("You're the only administrator. Make someone else an admin before deleting your account.")

    rules = ranking_service.get_rules(lock=True)
    outcome = {"startups": {}}
    for membership in list(user.memberships):
        startup = membership.startup
        others = [m for m in startup.members if m.user_id != user.id]
        if others:
            if membership.role == "owner" and not any(m.role == "owner" for m in others):
                heir = sorted(others, key=lambda m: m.created_at)[0]
                heir.role = "owner"
                notify(heir.user_id, f"You're now an owner of {startup.name}",
                       "The previous owner deleted their account.", "/dashboard/team", "team")
            db.session.delete(membership)
            outcome["startups"][startup.name] = "kept by team"
        else:
            name = startup.name
            result = _retire_startup(startup, user)  # a deleted startup takes its memberships with it
            if result == "unlisted":
                db.session.delete(membership)
            outcome["startups"][name] = result

    if user.investor_profile:
        profile = user.investor_profile
        db.session.execute(IntroductionRequest.__table__.delete().where(IntroductionRequest.investor_id == profile.id))
        db.session.delete(profile)
    db.session.execute(SavedStartup.__table__.delete().where(SavedStartup.user_id == user.id))
    db.session.execute(Notification.__table__.delete().where(Notification.user_id == user.id))
    for invite in db.session.scalars(select(StartupInvite).where(StartupInvite.email == user.email,
                                                                  StartupInvite.accepted_at.is_(None))):
        invite.revoked_at = utcnow()

    original_email = user.email
    user.email = f"deleted-{user.id}-{secrets.token_hex(4)}@deleted.invalid"
    user.name = "Deleted user"
    user.set_password(secrets.token_urlsafe(32))
    user.active = False
    user.email_verified_at = None
    audit("user.deleted", "user", user.id, actor=None, startups=outcome["startups"],
          email_domain=original_email.split("@")[-1])
    db.session.flush()
    ranking_service.recompute_rankings(rules)
    return outcome

