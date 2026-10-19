"""Startup team management: invite co-founders/colleagues by email.

Roles: owner (everything, incl. bids, payments and team) and editor (company
profile and introductions). A startup always keeps at least one owner.
"""
import hashlib
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import db, limiter
from models import StartupInvite, StartupMember, User, utcnow
from models.startup import INVITE_ROLES
from models.user import ROLE_STARTUP_OWNER
from services.audit_service import audit
from services.notification_service import notify, send_email
from utils.security import json_error, require_owned_startup, roles_required
from utils.validation import ValidationError, Validator

bp = Blueprint("team", __name__)

INVITE_DAYS = 7


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _invite_by_token(token):
    if not token or len(token) > 100:
        return None
    return db.session.scalars(select(StartupInvite).where(StartupInvite.token_hash == _hash(token))).first()


def _owner_count(startup):
    return sum(1 for m in startup.members if m.role == "owner")


def _member_dict(member, me):
    return {"id": member.id, "name": member.user.name, "email": member.user.email, "role": member.role,
            "joined_at": member.created_at.isoformat(), "is_me": member.user_id == me.id}


# ---- Pages ----------------------------------------------------------------

@bp.route("/dashboard/team")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def team_page():
    startup = require_owned_startup()
    membership = current_user.primary_membership
    invites = db.session.scalars(select(StartupInvite).where(StartupInvite.startup_id == startup.id)
                                 .order_by(StartupInvite.created_at.desc())).all()
    return render_template("team.html", startup=startup, membership=membership,
                           members=sorted(startup.members, key=lambda m: (m.role != "owner", m.created_at)),
                           invites=[i for i in invites if i.is_open], active="team",
                           is_owner=membership.role == "owner")


@bp.route("/invite/<token>", methods=["GET", "POST"])
@limiter.limit("30 per hour", methods=["POST"])
def accept(token):
    invite = _invite_by_token(token)
    if invite is None or not invite.is_open:
        reason = "expired" if invite and invite.accepted_at is None and invite.revoked_at is None else "invalid"
        return render_template("invite.html", invite=None, reason=reason), 410 if invite else 404
    problem = None
    if current_user.is_authenticated:
        if current_user.email.lower() != invite.email.lower():
            problem = f"This invitation was sent to {invite.email}, but you're signed in as {current_user.email}."
        elif current_user.role != ROLE_STARTUP_OWNER:
            problem = "Invitations are for startup accounts. This email is registered as an investor or admin account."
        elif current_user.primary_startup and current_user.primary_startup.id != invite.startup_id:
            problem = f"Your account already manages {current_user.primary_startup.name}. Each account can manage one startup."
        elif current_user.can_manage(invite.startup):
            problem = "You're already on this team."
    if request.method == "POST" and current_user.is_authenticated and not problem:
        db.session.add(StartupMember(startup_id=invite.startup_id, user_id=current_user.id, role=invite.role))
        invite.accepted_at = utcnow()
        if not current_user.is_verified:
            current_user.email_verified_at = utcnow()  # they followed a link sent to this address
        if invite.invited_by_id:
            notify(invite.invited_by_id, f"{current_user.name} joined {invite.startup.name}",
                   f"They joined as {invite.role}.", "/dashboard/team", "team")
        audit("team.invite_accepted", "startup", invite.startup_id, actor=current_user, role=invite.role)
        db.session.commit()
        flash(f"Welcome to the {invite.startup.name} team!", "success")
        return redirect(url_for("dashboard.overview"))
    return render_template("invite.html", invite=invite, problem=problem, token=token)


# ---- API --------------------------------------------------------------------

@bp.post("/api/team/invites")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
@limiter.limit("20 per hour")
def api_invite():
    startup = require_owned_startup(owner=True)
    v = Validator(request.get_json(silent=True) or {})
    v.email("email").choice("role", "Role", INVITE_ROLES)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    email = data["email"]
    if any(m.user.email.lower() == email for m in startup.members):
        return json_error("That person is already on your team.", 409, errors={"email": "Already a team member."})
    existing = db.session.scalars(select(User).where(User.email == email)).first()
    if existing is not None:
        if existing.role != ROLE_STARTUP_OWNER:
            return json_error("That email belongs to an investor or admin account, which can't join a startup team.", 409,
                              errors={"email": "Not a startup account."})
        if existing.primary_startup is not None:
            return json_error("That person already manages another startup on DeeptechIndia.", 409,
                              errors={"email": "Already manages another startup."})

    # One open invitation per email: re-inviting refreshes the link.
    for old in db.session.scalars(select(StartupInvite).where(StartupInvite.startup_id == startup.id,
                                                              StartupInvite.email == email)):
        if old.is_open:
            old.revoked_at = utcnow()
    token = secrets.token_urlsafe(32)
    invite = StartupInvite(startup_id=startup.id, email=email, role=data["role"], token_hash=_hash(token),
                           invited_by_id=current_user.id, expires_at=utcnow() + timedelta(days=INVITE_DAYS))
    db.session.add(invite)
    db.session.flush()
    link = url_for("team.accept", token=token, _external=True)
    if existing is not None:
        notify(existing.id, f"You're invited to join {startup.name}", f"{current_user.name} invited you as {data['role']}.",
               url_for("team.accept", token=token), "team")
    audit("team.invited", "startup", startup.id, actor=current_user, role=data["role"], email_domain=email.split("@")[-1])
    db.session.commit()
    sent = send_email(email, f"Join {startup.name} on DeeptechIndia.in",
                      f"{current_user.name} invited you to help manage {startup.name} on DeeptechIndia.in as {data['role']}.\n\n"
                      f"Accept the invitation (valid for {INVITE_DAYS} days):\n{link}\n\n— DeeptechIndia.in")
    payload = {"ok": True, "invite": invite.to_dict(), "emailed": sent}
    if not sent and current_app.debug:
        payload["dev_link"] = link  # development convenience when SMTP isn't configured
    return jsonify(payload), 201


@bp.delete("/api/team/invites/<int:invite_id>")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def api_revoke(invite_id):
    startup = require_owned_startup(owner=True)
    invite = db.session.get(StartupInvite, invite_id)
    if invite is None or invite.startup_id != startup.id:
        abort(404)
    invite.revoked_at = utcnow()
    audit("team.invite_revoked", "startup", startup.id, actor=current_user)
    db.session.commit()
    return jsonify({"ok": True})


@bp.put("/api/team/members/<int:member_id>")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def api_change_role(member_id):
    startup = require_owned_startup(owner=True)
    member = db.session.get(StartupMember, member_id)
    if member is None or member.startup_id != startup.id:
        abort(404)
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in INVITE_ROLES:
        return json_error("Choose owner or editor.", 400)
    if member.role == "owner" and role != "owner" and _owner_count(startup) <= 1:
        return json_error("A startup needs at least one owner. Make someone else an owner first.", 409)
    member.role = role
    notify(member.user_id, f"Your role at {startup.name} is now {role}", "", "/dashboard/team", "team")
    audit("team.role_changed", "startup", startup.id, actor=current_user, member_user_id=member.user_id, role=role)
    db.session.commit()
    return jsonify({"ok": True, "member": _member_dict(member, current_user)})


@bp.delete("/api/team/members/<int:member_id>")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def api_remove(member_id):
    membership = current_user.primary_membership
    if membership is None:
        abort(404)
    startup = membership.startup
    member = db.session.get(StartupMember, member_id)
    if member is None or member.startup_id != startup.id:
        abort(404)
    leaving_self = member.user_id == current_user.id
    if not leaving_self and membership.role != "owner":
        abort(403)
    if member.role == "owner" and _owner_count(startup) <= 1:
        msg = ("You're the only owner. Make someone else an owner before leaving."
               if leaving_self and len(startup.members) > 1 else
               "A startup needs at least one owner." if not leaving_self else
               "You're the only member. To remove the startup, delete your account from Settings.")
        return json_error(msg, 409)
    db.session.delete(member)
    if not leaving_self:
        notify(member.user_id, f"You were removed from {startup.name}", "", "/", "team")
    audit("team.member_left" if leaving_self else "team.member_removed", "startup", startup.id,
          actor=current_user, member_user_id=member.user_id)
    db.session.commit()
    return jsonify({"ok": True, "left": leaving_self, "redirect": url_for("startups.new_startup") if leaving_self else None})
