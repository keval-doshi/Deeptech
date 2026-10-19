import os
import sys
from datetime import timedelta
from functools import partial

import pytest
from flask import g

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import models.user  # noqa: E402
from app import create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import (BiddingRules, Category, FundingProfile, InvestorProfile, Payment, Startup,  # noqa: E402
                    StartupMember, User, utcnow)
from models.bid import BID_ACTIVE, Bid  # noqa: E402
from services import ranking_service  # noqa: E402

PASSWORD = "Correct-horse-9"

# Fast hashing in tests only; production uses Werkzeug's scrypt default.
models.user.generate_password_hash = partial(models.user.generate_password_hash, method="pbkdf2:sha256:1000")


@pytest.fixture
def app(tmp_path):
    app = create_app("testing", {"UPLOAD_FOLDER": str(tmp_path / "uploads")})

    # The fixture keeps one app context open, so `g` (where Flask-Login caches
    # the user) would leak between test clients. Real requests get a fresh g.
    @app.before_request
    def _fresh_login_cache():
        g.pop("_login_user", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_user(email, role="startup_owner", verified=True, active=True):
    user = User(email=email, name=email.split("@")[0].title(), role=role, active=active,
                email_verified_at=utcnow() if verified else None)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def make_startup(name, category, owner=None, status="published"):
    startup = Startup(slug=name.lower().replace(" ", "-"), name=name, tagline=f"{name} builds deep tech.",
                      description="x" * 100, category_id=category.id, city="Bengaluru", state="Karnataka",
                      founded_year=2020, team_size="11-50", contact_email=f"hello@{name.lower().replace(' ', '')}.in",
                      status=status, published_at=utcnow() if status == "published" else None)
    db.session.add(startup)
    db.session.flush()
    db.session.add(FundingProfile(startup_id=startup.id, is_raising=True, stage="Seed"))
    if owner:
        db.session.add(StartupMember(startup_id=startup.id, user_id=owner.id, role="owner"))
    db.session.flush()
    return startup


def paid_bid(startup, amount_rupees, days_ago=1):
    """Create a confirmed bid directly (bypassing payment) and rebuild the ranking."""
    paid_at = utcnow() - timedelta(days=days_ago)
    bid = Bid(startup_id=startup.id, target_position=1, amount_paise=amount_rupees * 100, status=BID_ACTIVE,
              idempotency_key=f"fixture-{startup.id}-{amount_rupees}-{days_ago}", paid_at=paid_at,
              expires_at=paid_at + timedelta(days=30))
    db.session.add(bid)
    db.session.flush()
    ranking_service.recompute_rankings(ranking_service.get_rules())
    db.session.commit()
    return bid


class World:
    pass


@pytest.fixture
def world(app):
    w = World()
    db.session.add(BiddingRules(id=1))
    w.category = Category(name="SpaceTech", slug="spacetech", icon="rocket", color="#5b3df5")
    db.session.add(w.category)
    db.session.flush()
    w.owner_a = make_user("owner.a@example.com")
    w.owner_b = make_user("owner.b@example.com")
    w.unverified = make_user("new.owner@example.com", verified=False)
    w.investor = make_user("investor@example.com", role="investor")
    db.session.add(InvestorProfile(user_id=w.investor.id, firm_name="Test Ventures"))
    w.admin = make_user("admin@example.com", role="admin")
    w.a = make_startup("Alpha Space", w.category, w.owner_a)
    w.b = make_startup("Beta Orbit", w.category, w.owner_b)
    w.c = make_startup("Gamma Labs", w.category)
    w.d = make_startup("Delta Rockets", w.category)
    w.unverified_startup = make_startup("Fresh Co", w.category, w.unverified)
    w.hidden = make_startup("Hidden Co", w.category, status="pending")
    db.session.commit()
    # Ranking: C #1 (₹1,500), D #2 (₹800), A #3 (₹500)
    paid_bid(w.c, 1500, 6)
    paid_bid(w.d, 800, 5)
    paid_bid(w.a, 500, 4)
    return w


def login(app, user):
    client = app.test_client()
    response = client.post("/login", data={"email": user.email, "password": PASSWORD})
    assert response.status_code == 302, response.data[:300]
    return client


def payments_for(bid_id):
    return db.session.scalars(db.select(Payment).where(Payment.bid_id == bid_id)).all()
