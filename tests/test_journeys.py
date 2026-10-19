"""End-to-end user journeys through the real routes (founder, investor, admin, public)."""
import hashlib
import hmac
import io
import json

from itsdangerous import URLSafeTimedSerializer
from PIL import Image

from extensions import db
from models import (BiddingRules, Founder, GalleryImage, IntroductionRequest, Notification, PlatformSetting,
                    Product, Startup, StartupUpdate, StartupView, User)
from models.bid import BID_ACTIVE, Bid
from routes.auth import VERIFY_SALT
from services import payment_service
from tests.conftest import PASSWORD, login, make_user, payments_for

STRONG = "Str0ng-pass-word"


def png_bytes(color="purple", size=(600, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def listing_form(name="Orbit Forge", **extra):
    data = {"name": name, "tagline": "Reusable upper stages for small launchers", "description": "d" * 120,
            "category_id": "1", "city": "Pune", "state": "Maharashtra", "founded_year": "2022", "team_size": "11-50",
            "contact_email": "team@orbitforge.in", "website": "orbitforge.in", "is_raising": "on", "stage": "Seed",
            "raising_target_inr": "50000000", "confirm_accuracy": "on", "logo": (io.BytesIO(png_bytes()), "logo.png")}
    data.update(extra)
    return data


def verify(app, client, user):
    token = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=VERIFY_SALT).dumps({"uid": user.id, "email": user.email})
    client.get(f"/verify-email/{token}")


def by_email(email):
    return db.session.scalars(db.select(User).where(User.email == email)).first()


def mock_pay(client, bid_id):
    checkout = client.post("/api/payments/checkout", json={"bid_id": bid_id}).get_json()["checkout"]
    assert client.post(checkout["redirect_url"], data={"outcome": "success"}).status_code == 302
    return checkout


# ---------------------------------------------------------------------------
# Founder: sign up → list → review → bid → pay → ranked
# ---------------------------------------------------------------------------

def test_founder_journey_from_signup_to_ranked(app, world):
    founder = app.test_client()
    response = founder.post("/register", data={"role": "startup_owner", "name": "Nisha Rao", "email": "nisha@orbitforge.in",
                                               "password": STRONG, "confirm_password": STRONG, "terms": "1"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/startup/new")
    user = by_email("nisha@orbitforge.in")
    verify(app, founder, user)
    assert by_email("nisha@orbitforge.in").is_verified

    created = founder.post("/api/startups", data=listing_form(), content_type="multipart/form-data")
    assert created.status_code == 201, created.get_json()
    startup = db.session.get(Startup, created.get_json()["id"])
    assert startup.status == "pending" and startup.logo_path and startup.website == "https://orbitforge.in"
    assert startup.funding.is_raising and startup.funding.stage == "Seed"
    assert founder.post("/api/startups", data=listing_form("Second Co"), content_type="multipart/form-data").status_code == 409

    # Pending listings are hidden and can't bid, and the board says why.
    assert app.test_client().get(f"/startups/{startup.slug}").status_code == 404
    board = founder.get("/api/dashboard/bids").get_json()["board"]
    assert board["blocked_reason"] == "pending_review" and "under review" in board["blocked_message"]
    first = board["positions"][0]
    assert first["higher"] and not first["eligible"] and first["minimum_next_bid"] == 1600
    refused = founder.post("/api/bids", json={"position": 1, "amount": 1600, "idempotency_key": "p" * 32})
    assert refused.status_code == 403 and "under review" in refused.get_json()["error"]

    # Admin approves → founder notified → bidding unlocked.
    admin = login(app, world.admin)
    assert admin.post(f"/admin/startups/{startup.id}/action", data={"action": "approve"}).status_code == 302
    assert db.session.get(Startup, startup.id).status == "published"
    assert db.session.scalar(db.select(Notification).where(Notification.user_id == user.id,
                                                           Notification.title.like("%live%")))
    board = founder.get("/api/dashboard/bids").get_json()["board"]
    assert board["blocked_reason"] is None and board["positions"][0]["eligible"]

    # Review page, bid, sandbox payment → ranked #1.
    assert founder.get("/dashboard/bids/review?position=1&amount=1600").status_code == 200
    bid = founder.post("/api/bids", json={"position": 1, "amount": 1600, "idempotency_key": "q" * 32}).get_json()["bid"]
    mock_pay(founder, bid["id"])
    assert db.session.get(Bid, bid["id"]).status == BID_ACTIVE
    top = app.test_client().get("/api/startups?sort=promoted").get_json()["items"][0]
    assert top["slug"] == startup.slug and top["promoted_rank"] == 1
    assert "amount" not in json.dumps(top)
    assert founder.get(f"/dashboard/bids/result/{bid['id']}").status_code == 200
    assert payments_for(bid["id"])[0].receipt.encode() in founder.get("/dashboard/payments").data
    history = founder.get("/api/bids/history").get_json()
    assert history["total"] == 1 and history["paid_total"] == 1600
    # The startup that was #1 got an outbid notification (no amounts in it).
    notes = founder.get("/api/notifications").get_json()["items"]
    assert any("ranked #1" in n["title"] for n in notes)


def test_rejected_listing_is_resubmitted_on_edit(app, world):
    owner = make_user("reject.me@example.com")
    db.session.commit()
    client = login(app, owner)
    created = client.post("/api/startups", data=listing_form("Rework Labs"), content_type="multipart/form-data").get_json()
    login(app, world.admin).post(f"/admin/startups/{created['id']}/action",
                                 data={"action": "reject", "reason": "Please add a real website."})
    board = client.get("/api/dashboard/bids").get_json()["board"]
    assert board["blocked_reason"] == "rejected" and board["rejection_reason"] == "Please add a real website."
    updated = client.put(f"/api/startups/{created['id']}", json={"website": "https://reworklabs.in"}).get_json()
    assert updated["resubmitted"] is True
    assert db.session.get(Startup, created["id"]).status == "pending"
    assert db.session.scalar(db.select(Notification).where(Notification.user_id == world.admin.id,
                                                           Notification.title.like("%resubmitted%")))


def test_listing_validation_and_bad_uploads(app, world):
    client = login(app, make_user("bad.upload@example.com"))
    db.session.commit()
    missing = client.post("/api/startups", data={"name": "X"}, content_type="multipart/form-data")
    assert missing.status_code == 400 and {"tagline", "description", "city"} <= set(missing.get_json()["errors"])
    fake = client.post("/api/startups", data=listing_form(cover=(io.BytesIO(b"<?php ?>"), "c.jpg")),
                       content_type="multipart/form-data")
    assert fake.status_code == 400 and "cover" in fake.get_json()["errors"]
    assert not db.session.scalars(db.select(Startup).where(Startup.name == "Orbit Forge")).first()


# ---------------------------------------------------------------------------
# Investor: save → request intro → founder accepts → contact revealed
# ---------------------------------------------------------------------------

def test_investor_introduction_journey(app, world):
    investor = login(app, world.investor)
    assert investor.post(f"/api/startups/{world.a.id}/save").get_json()["saved"] is True
    me = investor.get("/api/investors/me").get_json()
    assert [s["slug"] for s in me["saved"]] == [world.a.slug]

    message = "We back early space companies and would love to learn about your roadmap."
    sent = investor.post("/api/introduction-requests", json={"startup_id": world.a.id, "message": message})
    assert sent.status_code == 201 and "email" not in sent.get_json()["introduction"]["startup"]
    again = investor.post("/api/introduction-requests", json={"startup_id": world.a.id, "message": message})
    assert again.status_code == 409
    intro_id = sent.get_json()["introduction"]["id"]

    assert login(app, world.owner_b).put(f"/api/introduction-requests/{intro_id}", json={"status": "accepted"}).status_code == 404
    owner = login(app, world.owner_a)
    assert b"Test Ventures" in owner.get("/dashboard").data
    accepted = owner.put(f"/api/introduction-requests/{intro_id}", json={"status": "accepted"})
    assert accepted.status_code == 200 and accepted.get_json()["introduction"]["investor"]["email"] == world.investor.email
    assert owner.put(f"/api/introduction-requests/{intro_id}", json={"status": "declined"}).status_code == 409
    intro = investor.get("/api/investors/me").get_json()["introductions"][0]
    assert intro["status"] == "accepted" and intro["startup"]["email"] == world.a.contact_email

    # Fund profile editing
    updated = investor.put("/api/investors/me", json={"firm_name": "Test Ventures II", "investor_type": "VC",
                                                      "thesis": "Space", "check_min_inr": "1000000", "category_ids": [1]})
    assert updated.status_code == 200 and updated.get_json()["profile"]["categories"] == ["SpaceTech"]


def test_unverified_investor_cannot_request_intro(app, world):
    lurker = make_user("lurker@fund.in", role="investor", verified=False)
    from models import InvestorProfile
    db.session.add(InvestorProfile(user_id=lurker.id, firm_name="Lurker Capital"))
    db.session.commit()
    response = login(app, lurker).post("/api/introduction-requests", json={"startup_id": world.a.id, "message": "x" * 30})
    assert response.status_code == 403
    assert not db.session.scalars(db.select(IntroductionRequest)).first()


# ---------------------------------------------------------------------------
# Company profile editor (CRUD + ownership)
# ---------------------------------------------------------------------------

def test_profile_editor_crud_and_ownership(app, world):
    owner = login(app, world.owner_a)
    base = f"/api/startups/{world.a.id}"
    founder = owner.post(f"{base}/founders", data={"name": "Asha Iyer", "title": "CEO", "linkedin_url": "linkedin.com/in/asha",
                                                   "photo": (io.BytesIO(png_bytes()), "a.png")},
                         content_type="multipart/form-data")
    assert founder.status_code == 201 and founder.get_json()["founder"]["photo_url"]
    bad_li = owner.post(f"{base}/founders", data={"name": "Bob", "title": "CTO", "linkedin_url": "https://evil.example"},
                        content_type="multipart/form-data")
    assert bad_li.status_code == 400
    product = owner.post(f"{base}/products", data={"name": "Orbiter", "summary": "Kick stage"}, content_type="multipart/form-data")
    image = owner.post(f"{base}/gallery", data={"caption": "Test", "image": (io.BytesIO(png_bytes()), "g.png")},
                       content_type="multipart/form-data")
    update = owner.post(f"{base}/updates", json={"title": "We launched", "body": "First orbital test complete."})
    funding = owner.put(f"{base}/funding", json={"is_raising": True, "stage": "Series A", "raising_target_inr": "100000000"})
    assert all(r.status_code in (200, 201) for r in (product, image, update, funding))
    profile = app.test_client().get(f"/api/startups/{world.a.slug}").get_json()["startup"]
    assert profile["founders"][0]["name"] == "Asha Iyer" and profile["funding"]["stage"] == "Series A"
    assert profile["products"][0]["name"] == "Orbiter" and profile["updates"][0]["title"] == "We launched"

    fid = founder.get_json()["founder"]["id"]
    other = login(app, world.owner_b)
    assert other.delete(f"{base}/founders/{fid}").status_code == 404
    assert other.delete(f"/api/startups/{world.b.id}/founders/{fid}").status_code == 404
    assert db.session.get(Founder, fid) is not None

    for path in (f"{base}/founders/{fid}", f"{base}/products/{product.get_json()['product']['id']}",
                 f"{base}/gallery/{image.get_json()['image']['id']}", f"{base}/updates/{update.get_json()['update']['id']}"):
        assert owner.delete(path).status_code == 200
    assert not db.session.scalars(db.select(Founder)).first()
    assert not db.session.scalars(db.select(Product)).first()
    assert not db.session.scalars(db.select(GalleryImage)).first()
    assert not db.session.scalars(db.select(StartupUpdate)).first()

    for page in ("/dashboard", "/dashboard/profile", "/dashboard/payments", "/dashboard/settings",
                 "/dashboard/bids", "/dashboard/bids/history"):
        assert owner.get(page).status_code == 200, page


# ---------------------------------------------------------------------------
# Admin controls
# ---------------------------------------------------------------------------

def test_admin_rules_settings_and_users(app, world):
    admin = login(app, world.admin)
    form = {"opening_bid": "200", "increment": "250", "max_bid": "500000", "max_positions": "8",
            "ranking_period_days": "15", "checkout_ttl_minutes": "10", "bidding_enabled": "on"}
    assert admin.post("/admin/rules", data=form).status_code == 302
    rules = db.session.get(BiddingRules, 1)
    assert (rules.increment_paise, rules.max_positions, rules.ranking_period_days) == (25_000, 8, 15)
    rows = {r["position"]: r for r in login(app, world.owner_a).get("/api/dashboard/bids").get_json()["board"]["positions"]}
    assert rows[1]["minimum_next_bid"] == 1750
    assert admin.post("/admin/rules", data={**form, "increment": "0"}).status_code == 302
    assert db.session.get(BiddingRules, 1).increment_paise == 25_000  # invalid change rejected

    # Pause bidding
    admin.post("/admin/rules", data={k: v for k, v in form.items() if k != "bidding_enabled"})
    assert login(app, world.owner_a).get("/api/dashboard/bids").get_json()["board"]["blocked_reason"] == "paused"

    # Auto-publish new listings
    admin.post("/admin/settings", data={"allow_new_registrations": "on"})
    assert PlatformSetting.get_bool("listings_require_approval") is False
    quick = make_user("quick@example.com")
    db.session.commit()
    created = login(app, quick).post("/api/startups", data=listing_form("Quick Launch"), content_type="multipart/form-data")
    assert created.get_json()["status"] == "published"

    # Close registrations
    admin.post("/admin/settings", data={})
    app.test_client().post("/register", data={"role": "startup_owner", "name": "Late", "email": "late@x.in",
                                              "password": STRONG, "confirm_password": STRONG, "terms": "1"})
    assert by_email("late@x.in") is None

    # Deactivate a user; admins can't change themselves
    admin.post(f"/admin/users/{world.owner_b.id}/update", data={"action": "toggle_active"})
    assert app.test_client().post("/login", data={"email": world.owner_b.email, "password": PASSWORD}).status_code == 400
    admin.post(f"/admin/users/{world.admin.id}/update", data={"action": "set_role", "role": "investor"})
    assert db.session.get(User, world.admin.id).role == "admin"

    # Verify / pick / unpublish affect the public site
    admin.post(f"/admin/startups/{world.c.id}/action", data={"action": "pick"})
    assert world.c.slug in [s["slug"] for s in app.test_client().get("/api/startups?tab=picks").get_json()["items"]]
    admin.post(f"/admin/startups/{world.c.id}/action", data={"action": "unpublish"})
    assert app.test_client().get(f"/startups/{world.c.slug}").status_code == 404
    assert admin.get("/admin").status_code == 200


# ---------------------------------------------------------------------------
# Public site
# ---------------------------------------------------------------------------

def test_public_homepage_listing_and_redirects(app, client, world):
    home = client.get("/").data.decode()
    assert "Today&#39;s ranking" in home or "Today's ranking" in home
    assert "Gamma Labs" in home  # #1 in the sidebar
    page1 = client.get("/api/startups?per_page=2&page=1").get_json()
    page2 = client.get("/api/startups?per_page=2&page=2").get_json()
    assert page1["pages"] >= 2 and {s["id"] for s in page1["items"]}.isdisjoint({s["id"] for s in page2["items"]})
    assert all(s["category"]["slug"] == "spacetech" for s in client.get("/api/startups?category=spacetech").get_json()["items"])
    assert client.get("/api/startups?q=Gamma").get_json()["items"][0]["slug"] == world.c.slug
    assert client.get("/api/startups?funding=raising").get_json()["total"] == 5
    assert client.get("/api/funding?stage=Seed").status_code == 200

    redirect = client.get("/categories/spacetech")
    assert redirect.status_code == 301 and "category=spacetech" in redirect.headers["Location"]
    assert client.get("/categories/nope").status_code == 404
    assert client.get("/startups?q=x").status_code == 301
    for page in ("/funding", "/investors", "/credits", "/login", "/register", "/forgot-password"):
        assert client.get(page).status_code == 200, page


def test_profile_views_counted_once_per_session(app, world):
    visitor = app.test_client()
    for _ in range(3):
        assert visitor.get(f"/startups/{world.b.slug}").status_code == 200
    login(app, world.owner_b).get(f"/startups/{world.b.slug}")  # owners don't count
    total = db.session.scalar(db.select(db.func.sum(StartupView.views)).where(StartupView.startup_id == world.b.id))
    assert total == 1


def test_save_requires_login(client, world):
    assert client.post(f"/api/startups/{world.a.id}/save").status_code == 401
    assert client.post(f"/api/startups/{world.hidden.id}/save").status_code == 401


def test_account_settings_and_notifications(app, world):
    owner = login(app, world.owner_a)
    assert owner.post("/dashboard/settings", data={"action": "password", "current_password": "wrong",
                                                   "password": STRONG, "confirm_password": STRONG}).status_code == 400
    assert owner.post("/dashboard/settings", data={"action": "password", "current_password": PASSWORD,
                                                   "password": STRONG, "confirm_password": STRONG}).status_code == 302
    assert db.session.get(User, world.owner_a.id).check_password(STRONG)
    owner.post("/dashboard/settings", data={"action": "profile", "name": "Owner Renamed"})
    assert db.session.get(User, world.owner_a.id).name == "Owner Renamed"
    db.session.add(Notification(user_id=world.owner_a.id, title="Hello"))
    db.session.commit()
    assert owner.get("/api/notifications").get_json()["unread"] == 1
    owner.post("/api/notifications/read")
    assert owner.get("/api/notifications").get_json()["unread"] == 0


# ---------------------------------------------------------------------------
# Razorpay integration (network mocked) and maintenance commands
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_razorpay_order_and_signed_webhook(app, world, monkeypatch):
    app.config.update(PAYMENT_PROVIDER="razorpay", RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET="secret",
                      RAZORPAY_WEBHOOK_SECRET="whsec")
    calls = []

    def fake_post(url, auth=None, json=None, timeout=None):
        calls.append((url, auth, json))
        return FakeResponse({"id": "order_TEST123", "amount": json["amount"]})

    monkeypatch.setattr(payment_service.requests, "post", fake_post)
    owner = login(app, world.owner_a)
    bid = owner.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": "r" * 32}).get_json()["bid"]
    checkout = owner.post("/api/payments/checkout", json={"bid_id": bid["id"]}).get_json()["checkout"]
    assert checkout["provider"] == "razorpay" and checkout["key"] == "rzp_test_key" and checkout["order_id"] == "order_TEST123"
    assert calls[0][1] == ("rzp_test_key", "secret") and calls[0][2]["amount"] == 90_000
    assert owner.get(f"/payments/mock-checkout/{payments_for(bid['id'])[0].receipt}").status_code == 404

    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_TEST1", "order_id": "order_TEST123", "amount": 90_000, "currency": "INR", "method": "upi"}}}}).encode()
    signature = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    bad = app.test_client().post("/api/payments/webhook", data=body, headers={"X-Razorpay-Signature": "0" * 64})
    assert bad.status_code == 400
    good = app.test_client().post("/api/payments/webhook", data=body,
                                  headers={"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": "evt_1"})
    assert good.status_code == 200 and good.get_json()["result"] == "processed"
    assert db.session.get(Bid, bid["id"]).achieved_position == 2


def test_razorpay_misconfiguration_fails_safely(app, world):
    app.config.update(PAYMENT_PROVIDER="razorpay", RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="", RAZORPAY_WEBHOOK_SECRET="")
    owner = login(app, world.owner_a)
    bid = owner.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": "s" * 32}).get_json()["bid"]
    response = owner.post("/api/payments/checkout", json={"bid_id": bid["id"]})
    assert response.status_code == 503 and response.get_json()["ok"] is False


def test_maintenance_commands(app, world):
    runner = app.test_cli_runner()
    assert "ranking changes" in runner.invoke(args=["bids", "maintain"]).output
    assert "Checked" in runner.invoke(args=["payments", "reconcile"]).output
