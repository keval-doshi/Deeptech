"""Launch readiness: legal pages, SEO endpoints, production settings, base data and email."""
import smtplib

from conftest import make_startup, make_user
from config import ProductionConfig
from extensions import db
from models import BiddingRules, Category, InvestorProfile
from seed import CATEGORIES, ensure_base_data
from services.notification_service import send_email


def _category():
    category = Category(name="Quantum", slug="quantum", icon="atom", color="#000000")
    db.session.add(category)
    db.session.flush()
    return category


def test_legal_and_contact_pages_render(client):
    for path, text in (("/terms", "Terms of Use"), ("/privacy", "Privacy Policy"), ("/refunds", "Refund Policy"),
                       ("/promoted-listing-terms", "Promoted Listing Terms"), ("/contact", "Grievance Officer")):
        response = client.get(path)
        assert response.status_code == 200, path
        assert text in response.get_data(as_text=True)


def test_legal_pages_are_marked_draft_until_reviewed(app, client):
    assert "Draft pending legal review" in client.get("/terms").get_data(as_text=True)
    app.config["LEGAL_REVIEWED"] = True
    assert "Draft pending legal review" not in client.get("/terms").get_data(as_text=True)


def test_legal_pages_use_configured_business_details(app, client):
    assert "[Company legal name]" in client.get("/terms").get_data(as_text=True)
    app.config["LEGAL_ENTITY_NAME"] = "Example Deeptech Pvt Ltd"
    page = client.get("/terms").get_data(as_text=True)
    assert "Example Deeptech Pvt Ltd" in page and "[Company legal name]" not in page


def test_signup_links_to_the_terms_it_asks_people_to_accept(client):
    page = client.get("/register").get_data(as_text=True)
    assert 'href="/terms"' in page and 'href="/privacy"' in page


def test_footer_links_to_legal_pages(client):
    page = client.get("/contact").get_data(as_text=True)
    for path in ("/terms", "/privacy", "/refunds", "/promoted-listing-terms"):
        assert f'href="{path}"' in page


def test_health_reports_database_state(client, monkeypatch):
    assert client.get("/health").get_json() == {"status": "ok"}

    def broken(*args, **kwargs):
        raise RuntimeError("database down")
    monkeypatch.setattr(db.session, "execute", broken)
    assert client.get("/health").status_code == 503


def test_robots_blocks_private_areas_and_names_the_sitemap(app, client):
    app.config["SITE_URL"] = "https://deeptechindia.in"
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "Disallow: /admin" in body and "Disallow: /dashboard" in body and "Disallow: /api/" in body
    assert "Sitemap: https://deeptechindia.in/sitemap.xml" in body


def test_sitemap_lists_only_published_startups(app, client):
    app.config["SITE_URL"] = "https://deeptechindia.in"
    category = _category()
    make_startup("Live Co", category)
    make_startup("Hidden Co", category, status="pending")
    db.session.commit()
    response = client.get("/sitemap.xml")
    body = response.get_data(as_text=True)
    assert response.mimetype == "application/xml"
    assert "https://deeptechindia.in/startups/live-co" in body
    assert "hidden-co" not in body


def test_pages_have_canonical_and_absolute_share_image(app, client):
    app.config["SITE_URL"] = "https://deeptechindia.in"
    category = _category()
    make_startup("Live Co", category)
    db.session.commit()
    page = client.get("/startups/live-co?utm_source=x").get_data(as_text=True)
    assert '<link rel="canonical" href="https://deeptechindia.in/startups/live-co">' in page
    assert '<meta property="og:image" content="https://deeptechindia.in/static/' in page
    assert "application/ld+json" in page


def test_error_pages_are_not_indexed(client):
    assert 'content="noindex"' in client.get("/no-such-page").get_data(as_text=True)


def test_static_urls_carry_a_version(client):
    assert "css/style.css?v=" in client.get("/contact").get_data(as_text=True)


def test_database_url_uses_the_installed_postgres_driver(monkeypatch):
    from config import _database_url
    for url in ("postgres://u:p@db/x", "postgresql://u:p@db/x"):
        monkeypatch.setenv("DATABASE_URL", url)
        assert _database_url() == "postgresql+psycopg2://u:p@db/x"


def _safe_production_settings(monkeypatch):
    for name, value in {
        "SECRET_KEY": "x" * 40, "SQLALCHEMY_DATABASE_URI": "postgresql://u:p@db/x", "PAYMENT_PROVIDER": "razorpay",
        "RAZORPAY_KEY_ID": "k", "RAZORPAY_KEY_SECRET": "s", "RAZORPAY_WEBHOOK_SECRET": "w",
        "RATELIMIT_STORAGE_URI": "redis://redis:6379/0", "MAIL_SERVER": "smtp.example.com",
        "SITE_URL": "https://deeptechindia.in", "LEGAL_ENTITY_NAME": "Example Pvt Ltd", "LEGAL_ADDRESS": "Bengaluru",
        "LEGAL_JURISDICTION": "Bengaluru", "GRIEVANCE_OFFICER_NAME": "A Person", "GRIEVANCE_OFFICER_EMAIL": "g@example.com",
    }.items():
        monkeypatch.setattr(ProductionConfig, name, value)


def test_production_accepts_complete_settings(monkeypatch):
    _safe_production_settings(monkeypatch)
    assert ProductionConfig.validate() == []


def test_production_refuses_to_start_without_email(monkeypatch):
    _safe_production_settings(monkeypatch)
    monkeypatch.setattr(ProductionConfig, "MAIL_SERVER", "")
    assert any("MAIL_SERVER" in problem for problem in ProductionConfig.validate())


def test_production_refuses_non_https_site_url(monkeypatch):
    _safe_production_settings(monkeypatch)
    monkeypatch.setattr(ProductionConfig, "SITE_URL", "http://127.0.0.1:5000")
    assert any("SITE_URL" in problem for problem in ProductionConfig.validate())


def test_production_refuses_missing_legal_details(monkeypatch):
    _safe_production_settings(monkeypatch)
    monkeypatch.setattr(ProductionConfig, "LEGAL_ENTITY_NAME", "")
    assert any("LEGAL_ENTITY_NAME" in problem for problem in ProductionConfig.validate())


def test_base_data_is_complete_and_safe_to_rerun(app):
    assert ensure_base_data() == len(CATEGORIES)
    db.session.commit()
    existing = db.session.scalars(db.select(Category).filter_by(slug="quantum")).one()
    existing.description = "Edited by an admin"
    db.session.commit()

    assert ensure_base_data() == 0
    db.session.commit()
    assert db.session.scalar(db.select(db.func.count(Category.id))) == len(CATEGORIES)
    assert db.session.get(BiddingRules, 1) is not None
    assert existing.description == "Edited by an admin"


def test_setup_command_adds_no_sample_people(app):
    result = app.test_cli_runner().invoke(args=["setup"])
    assert result.exit_code == 0, result.output
    assert db.session.scalar(db.select(db.func.count(Category.id))) == len(CATEGORIES)
    from models import Startup, User
    assert db.session.scalar(db.select(db.func.count(User.id))) == 0
    assert db.session.scalar(db.select(db.func.count(Startup.id))) == 0


def test_registration_records_accepted_terms_version(app, client):
    from models import AuditLog
    response = client.post("/register", data={
        "name": "Asha Rao", "email": "asha@example.com", "role": "startup_owner",
        "password": "Correct-horse-9", "confirm_password": "Correct-horse-9", "terms": "1"})
    assert response.status_code == 302
    entry = db.session.scalars(db.select(AuditLog).filter_by(action="user.registered")).one()
    assert app.config["LEGAL_VERSION"] in str(entry.data)


class _FakeSMTP:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


def test_email_has_plain_text_and_safe_html_versions(app, monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    app.config["MAIL_SERVER"] = "smtp.example.com"
    assert send_email("a@example.com", "Verify <you>", "Hi <b>Asha</b>,\n\nhttps://deeptechindia.in/verify-email/abc?x=1&y=2\n\nThanks")
    message = _FakeSMTP.sent[0]
    plain = message.get_body(("plain",)).get_content()
    rich = message.get_body(("html",)).get_content()
    assert "Hi <b>Asha</b>" in plain
    assert "&lt;b&gt;Asha&lt;/b&gt;" in rich and "<b>Asha</b>" not in rich
    assert 'href="https://deeptechindia.in/verify-email/abc?x=1&amp;y=2"' in rich
    assert "Verify &lt;you&gt;" in rich


def test_reconcile_keeps_going_after_one_failure(app, monkeypatch):
    from datetime import timedelta

    from models import Payment, utcnow
    from models.bid import Bid
    from services import payment_service
    owner = make_user("owner@example.com")
    category = _category()
    for receipt in ("r-1", "r-2"):
        startup = make_startup(f"Co {receipt}", category, owner)
        bid = Bid(startup_id=startup.id, user_id=owner.id, amount_paise=10_000, target_position=1,
                  idempotency_key=receipt, status="pending_payment")
        db.session.add(bid)
        db.session.flush()
        db.session.add(Payment(bid_id=bid.id, user_id=owner.id, startup_id=startup.id, provider="mock", receipt=receipt,
                               provider_order_id=f"order-{receipt}", amount_paise=10_000, status="created",
                               created_at=utcnow() - timedelta(hours=1)))
    db.session.commit()

    def flaky(payment):
        if payment.receipt == "r-1":
            raise RuntimeError("provider timeout")
        return "created"
    monkeypatch.setattr(payment_service, "reconcile", flaky)
    result = app.test_cli_runner().invoke(args=["payments", "reconcile"])
    assert result.exit_code == 0, result.output
    assert "r-1: error" in result.output and "r-2: created" in result.output


def test_back_link_on_every_kind_of_page(app, client):
    category = _category()
    make_startup("Live Co", category)
    db.session.commit()
    for path in ("/funding", "/investors", "/contact", "/terms", "/privacy", "/refunds", "/promoted-listing-terms",
                 "/credits", "/login", "/register", "/startups/live-co", "/no-such-page"):
        assert "data-back" in client.get(path).get_data(as_text=True), path
    assert "data-back" not in client.get("/").get_data(as_text=True)


def test_back_link_falls_back_to_the_parent_page(app):
    from conftest import login
    owner = make_user("owner@example.com")
    make_startup("Live Co", _category(), owner)
    db.session.commit()
    founder = login(app, owner)
    for path, parent in (("/dashboard", "/"), ("/dashboard/bids", "/dashboard"), ("/dashboard/bids/history", "/dashboard/bids"),
                         ("/dashboard/profile", "/dashboard"), ("/dashboard/team", "/dashboard"),
                         ("/dashboard/payments", "/dashboard"), ("/dashboard/settings", "/dashboard")):
        page = founder.get(path).get_data(as_text=True)
        assert f'<a class="back-link" href="{parent}" data-back>' in page, path


def test_investor_settings_back_link_avoids_the_founder_dashboard(app):
    from conftest import login
    investor = make_user("investor@example.com", role="investor")
    db.session.add(InvestorProfile(user_id=investor.id, firm_name="Fund"))
    db.session.commit()
    page = login(app, investor).get("/dashboard/settings").get_data(as_text=True)
    assert '<a class="back-link" href="/investors" data-back>' in page
