"""Investor verification, team members/invites, data export and account deletion."""
import json
import re

from extensions import db
from models import (InvestorProfile, IntroductionRequest, Notification, Payment, RankingPosition, SavedStartup, Startup,
                    StartupInvite, StartupMember, User)
from models.bid import Bid
from tests.conftest import PASSWORD, login, make_user

STRONG = "Str0ng-pass-word"


def invite(client, email, role="editor"):
    response = client.post("/api/team/invites", json={"email": email, "role": role})
    return response


def latest_invite_token(caplog_text=None):
    """Create a fresh token for the latest invite (tests can't read the email)."""
    import hashlib
    import secrets
    inv = db.session.scalars(db.select(StartupInvite).order_by(StartupInvite.id.desc())).first()
    token = secrets.token_urlsafe(32)
    inv.token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.session.commit()
    return token


# ---------------------------------------------------------------------------
# Investor verification
# ---------------------------------------------------------------------------

def test_admin_verifies_investor(app, world):
    profile = world.investor.investor_profile
    assert not profile.is_verified
    assert login(app, world.owner_a).post(f"/admin/investors/{profile.id}/action", data={"action": "verify"}).status_code == 403
    admin = login(app, world.admin)
    assert b"Test Ventures" in admin.get("/admin").data
    assert admin.post(f"/admin/investors/{profile.id}/action", data={"action": "verify"}).status_code == 302
    assert db.session.get(InvestorProfile, profile.id).is_verified
    assert db.session.scalar(db.select(Notification).where(Notification.user_id == world.investor.id,
                                                           Notification.title.like("%verified%")))
    listed = app.test_client().get("/api/investors").get_json()["items"]
    assert any(i["firm_name"] == "Test Ventures" and i["is_verified"] for i in listed)
    # Founders see the badge on introduction requests
    login(app, world.investor).post("/api/introduction-requests",
                                    json={"startup_id": world.a.id, "message": "We would love to learn more about you."})
    assert b"Verified investor" in login(app, world.owner_a).get("/dashboard").data
    admin.post(f"/admin/investors/{profile.id}/action", data={"action": "unverify"})
    assert not db.session.get(InvestorProfile, profile.id).is_verified


# ---------------------------------------------------------------------------
# Team members
# ---------------------------------------------------------------------------

def test_owner_invites_new_person_who_joins_as_editor(app, world):
    owner = login(app, world.owner_a)
    assert owner.get("/dashboard/team").status_code == 200
    response = invite(owner, "cofounder@alpha.in")
    assert response.status_code == 201 and response.get_json()["invite"]["role"] == "editor"
    token = latest_invite_token()

    visitor = app.test_client()
    page = visitor.get(f"/invite/{token}")
    assert page.status_code == 200 and b"Create an account to join" in page.data
    register = visitor.post(f"/register?next=/invite/{token}", data={
        "role": "startup_owner", "name": "Co Founder", "email": "cofounder@alpha.in",
        "password": STRONG, "confirm_password": STRONG, "terms": "1"})
    assert register.headers["Location"].endswith(f"/invite/{token}")
    assert visitor.post(f"/invite/{token}").status_code == 302
    editor = db.session.scalars(db.select(User).where(User.email == "cofounder@alpha.in")).first()
    membership = db.session.scalars(db.select(StartupMember).where(StartupMember.user_id == editor.id)).first()
    assert membership.startup_id == world.a.id and membership.role == "editor"
    assert editor.is_verified  # followed the emailed link
    assert visitor.post(f"/invite/{token}").status_code == 410  # single use

    # Editors can edit the profile but not bids, payments or team management
    assert visitor.put(f"/api/startups/{world.a.id}", json={"tagline": "Edited by the editor!"}).status_code == 200
    assert visitor.get("/dashboard/bids").status_code == 403
    assert visitor.get("/api/dashboard/bids").status_code == 403
    assert visitor.post("/api/bids", json={"position": 1, "amount": 5000, "idempotency_key": "e" * 32}).status_code == 403
    assert visitor.get("/dashboard/payments").status_code == 403
    assert invite(visitor, "someone@else.in").status_code == 403
    assert visitor.get("/dashboard/team").status_code == 200
    # The inviter was notified
    assert db.session.scalar(db.select(Notification).where(Notification.user_id == world.owner_a.id,
                                                           Notification.title.like("%joined%")))


def test_roles_can_change_but_a_startup_keeps_an_owner(app, world):
    owner = login(app, world.owner_a)
    me = db.session.scalars(db.select(StartupMember).where(StartupMember.user_id == world.owner_a.id)).first()
    # Sole owner can't demote or remove themselves
    assert owner.put(f"/api/team/members/{me.id}", json={"role": "editor"}).status_code == 409
    assert owner.delete(f"/api/team/members/{me.id}").status_code == 409

    colleague = make_user("colleague@alpha.in")
    db.session.add(StartupMember(startup_id=world.a.id, user_id=colleague.id, role="editor"))
    db.session.commit()
    member = db.session.scalars(db.select(StartupMember).where(StartupMember.user_id == colleague.id)).first()
    assert owner.put(f"/api/team/members/{member.id}", json={"role": "owner"}).status_code == 200
    assert login(app, colleague).get("/api/dashboard/bids").status_code == 200  # owners can bid now
    # With a second owner, the first can step down and leave
    assert owner.put(f"/api/team/members/{me.id}", json={"role": "editor"}).status_code == 200
    left = owner.delete(f"/api/team/members/{me.id}")
    assert left.status_code == 200 and left.get_json()["left"] is True
    assert db.session.get(StartupMember, me.id) is None


def test_invite_rules(app, world):
    owner = login(app, world.owner_a)
    assert invite(owner, world.owner_b.email).status_code == 409          # already manages another startup
    assert invite(owner, world.investor.email).status_code == 409         # investor account
    assert invite(owner, world.owner_a.email).status_code == 409          # already on the team
    assert invite(owner, "not-an-email").status_code == 400
    assert invite(owner, "x@y.in", role="admin").status_code == 400
    # Re-inviting the same email revokes the earlier link
    invite(owner, "dup@alpha.in")
    invite(owner, "dup@alpha.in")
    open_invites = [i for i in db.session.scalars(db.select(StartupInvite).where(StartupInvite.email == "dup@alpha.in")) if i.is_open]
    assert len(open_invites) == 1
    # Revoke
    assert owner.delete(f"/api/team/invites/{open_invites[0].id}").status_code == 200
    assert not db.session.get(StartupInvite, open_invites[0].id).is_open
    # Another startup's owner can't touch these
    assert login(app, world.owner_b).delete(f"/api/team/invites/{open_invites[0].id}").status_code == 404


def test_invite_requires_matching_account(app, world):
    owner = login(app, world.owner_a)
    invite(owner, "right@alpha.in")
    token = latest_invite_token()
    wrong = login(app, world.owner_b)
    page = wrong.get(f"/invite/{token}")
    assert b"was sent to right@alpha.in" in page.data
    wrong.post(f"/invite/{token}")
    assert not db.session.scalars(db.select(StartupMember).where(StartupMember.user_id == world.owner_b.id,
                                                                 StartupMember.startup_id == world.a.id)).first()
    assert app.test_client().get("/invite/not-a-real-token").status_code == 404


# ---------------------------------------------------------------------------
# Data export
# ---------------------------------------------------------------------------

def test_data_export_contains_only_own_data(app, world):
    response = login(app, world.owner_a).get("/dashboard/settings/export")
    assert response.status_code == 200 and "attachment" in response.headers["Content-Disposition"]
    data = json.loads(response.data)
    assert data["account"]["email"] == world.owner_a.email
    assert data["startups"][0]["profile"]["name"] == "Alpha Space"
    assert data["startups"][0]["bids"][0]["amount_inr"] == 500
    text = response.data.decode()
    assert "Beta Orbit" not in text and world.owner_b.email not in text

    investor = json.loads(login(app, world.investor).get("/dashboard/settings/export").data)
    assert investor["investor_profile"]["firm_name"] == "Test Ventures"


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------

def delete(client, password=PASSWORD, confirm="DELETE"):
    return client.post("/dashboard/settings/delete", data={"delete_password": password, "delete_confirm": confirm})


def test_delete_requires_password_and_confirmation(app, world):
    client = login(app, world.owner_b)
    assert delete(client, password="wrong").status_code == 400
    assert delete(client, confirm="delete").status_code == 400
    assert db.session.get(User, world.owner_b.id).active


def test_sole_founder_without_payments_removes_startup(app, world):
    client = login(app, world.owner_b)
    email = world.owner_b.email
    response = delete(client)
    assert response.status_code == 302
    user = db.session.get(User, world.owner_b.id)
    assert not user.active and user.email != email and user.name == "Deleted user"
    assert db.session.get(Startup, world.b.id) is None
    assert app.test_client().post("/login", data={"email": email, "password": PASSWORD}).status_code == 400
    assert client.get("/dashboard").status_code == 302  # signed out


def test_sole_founder_with_payments_is_unlisted_and_records_kept(app, world):
    bid = db.session.scalars(db.select(Bid).where(Bid.startup_id == world.a.id)).first()
    db.session.add(Payment(bid_id=bid.id, startup_id=world.a.id, provider="mock", provider_order_id="order_keep",
                           receipt="DTIKEEP1", amount_paise=bid.amount_paise, status="paid"))
    db.session.commit()
    assert db.session.scalar(db.select(RankingPosition.position).where(RankingPosition.startup_id == world.a.id)) == 3
    delete(login(app, world.owner_a))
    startup = db.session.get(Startup, world.a.id)
    assert startup is not None and startup.status == "draft"
    assert db.session.scalars(db.select(Payment).where(Payment.receipt == "DTIKEEP1")).first() is not None
    assert db.session.scalar(db.select(RankingPosition.position).where(RankingPosition.startup_id == world.a.id)) is None
    assert app.test_client().get(f"/startups/{world.a.slug}").status_code == 404


def test_founder_with_teammate_hands_over_startup(app, world):
    teammate = make_user("teammate@alpha.in")
    db.session.add(StartupMember(startup_id=world.a.id, user_id=teammate.id, role="editor"))
    db.session.commit()
    delete(login(app, world.owner_a))
    membership = db.session.scalars(db.select(StartupMember).where(StartupMember.startup_id == world.a.id)).all()
    assert [(m.user_id, m.role) for m in membership] == [(teammate.id, "owner")]
    assert db.session.get(Startup, world.a.id).status == "published"


def test_investor_deletion_removes_profile_and_intros(app, world):
    investor = login(app, world.investor)
    investor.post("/api/introduction-requests", json={"startup_id": world.a.id, "message": "Keen to learn more about Alpha Space."})
    investor.post(f"/api/startups/{world.a.id}/save")
    delete(investor)
    assert db.session.scalars(db.select(InvestorProfile).where(InvestorProfile.user_id == world.investor.id)).first() is None
    assert not db.session.scalars(db.select(IntroductionRequest)).first()
    assert not db.session.scalars(db.select(SavedStartup)).first()


def test_last_admin_cannot_delete_account(app, world):
    response = delete(login(app, world.admin))
    assert response.status_code == 400 and b"only administrator" in response.data
    assert db.session.get(User, world.admin.id).active
