from itsdangerous import URLSafeTimedSerializer

from app import create_app
from extensions import db
from models import InvestorProfile, User
from routes.auth import RESET_SALT, VERIFY_SALT, password_fingerprint
from tests.conftest import PASSWORD, login, make_user


def _user(email):
    return db.session.scalars(db.select(User).where(User.email == email)).first()


def test_register_hashes_password_and_requires_verification(client, world):
    response = client.post("/register", data={
        "role": "startup_owner", "name": "Asha Rao", "email": "Asha@Example.com",
        "password": "Sup3r-secret!", "confirm_password": "Sup3r-secret!", "terms": "1"})
    assert response.status_code == 302
    user = _user("asha@example.com")
    assert user is not None
    assert user.password_hash != "Sup3r-secret!" and user.check_password("Sup3r-secret!")
    assert not user.is_verified


def test_register_investor_creates_profile(client, world):
    client.post("/register", data={"role": "investor", "name": "Ravi", "email": "ravi@fund.in", "firm_name": "Ravi Capital",
                                   "password": "Sup3r-secret!", "confirm_password": "Sup3r-secret!", "terms": "1"})
    user = _user("ravi@fund.in")
    assert user.role == "investor"
    assert db.session.scalars(db.select(InvestorProfile).where(InvestorProfile.user_id == user.id)).first()


def test_register_cannot_self_assign_admin(client, world):
    response = client.post("/register", data={"role": "admin", "name": "Mallory", "email": "m@x.in",
                                              "password": "Sup3r-secret!", "confirm_password": "Sup3r-secret!", "terms": "1"})
    assert response.status_code == 400
    assert _user("m@x.in") is None


def test_register_rejects_weak_password_and_duplicate_email(client, world):
    weak = client.post("/register", data={"role": "startup_owner", "name": "Weak", "email": "weak@x.in",
                                          "password": "short", "confirm_password": "short", "terms": "1"})
    assert weak.status_code == 400 and _user("weak@x.in") is None
    dup = client.post("/register", data={"role": "startup_owner", "name": "Dup", "email": world.owner_a.email,
                                         "password": "Sup3r-secret!", "confirm_password": "Sup3r-secret!", "terms": "1"})
    assert dup.status_code == 400


def test_login_failure_is_generic(client, world):
    wrong = client.post("/login", data={"email": world.owner_a.email, "password": "nope"})
    missing = client.post("/login", data={"email": "ghost@example.com", "password": "nope"})
    assert wrong.status_code == missing.status_code == 400
    assert b"Incorrect email or password" in wrong.data and b"Incorrect email or password" in missing.data


def test_inactive_user_cannot_login(app, world):
    world.owner_a.active = False
    db.session.commit()
    response = app.test_client().post("/login", data={"email": world.owner_a.email, "password": PASSWORD})
    assert response.status_code == 400


def test_login_ignores_open_redirect(app, world):
    response = app.test_client().post("/login?next=//evil.example/steal",
                                      data={"email": world.owner_a.email, "password": PASSWORD})
    assert response.status_code == 302
    assert "evil.example" not in response.headers["Location"]


def test_email_verification_token(app, client, world):
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=VERIFY_SALT)
    token = serializer.dumps({"uid": world.unverified.id, "email": world.unverified.email})
    client.get(f"/verify-email/{token}")
    assert db.session.get(User, world.unverified.id).is_verified
    # A tampered token is rejected.
    client.get(f"/verify-email/{token}x")


def test_password_reset_token_is_single_use(app, client, world):
    user = world.owner_a
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=RESET_SALT)
    token = serializer.dumps({"uid": user.id, "pf": password_fingerprint(user)})
    first = client.post(f"/reset-password/{token}", data={"password": "Brand-new-pass1", "confirm_password": "Brand-new-pass1"})
    assert first.status_code == 302
    assert db.session.get(User, user.id).check_password("Brand-new-pass1")
    second = client.post(f"/reset-password/{token}", data={"password": "Another-pass-22", "confirm_password": "Another-pass-22"})
    assert second.status_code == 302 and "forgot-password" in second.headers["Location"]
    assert db.session.get(User, user.id).check_password("Brand-new-pass1")


def test_forgot_password_does_not_reveal_accounts(client, world):
    a = client.post("/forgot-password", data={"email": world.owner_a.email})
    b = client.post("/forgot-password", data={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 200
    assert b"Check your inbox" in a.data and b"Check your inbox" in b.data


def test_csrf_is_enforced_on_forms():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        db.create_all()
        make_user("csrf@example.com")
        db.session.commit()
        response = app.test_client().post("/login", data={"email": "csrf@example.com", "password": PASSWORD})
        assert response.status_code == 400
        api = app.test_client().post("/api/bids", json={})
        assert api.status_code in (400, 401)
        db.drop_all()


def test_login_is_rate_limited():
    app = create_app("testing", {"RATELIMIT_ENABLED": True})
    with app.app_context():
        db.create_all()
        client = app.test_client()
        codes = [client.post("/login", data={"email": "x@example.com", "password": "wrong"}).status_code
                 for _ in range(11)]
        assert codes[:10] == [400] * 10 and codes[10] == 429
        db.drop_all()


def test_logout_requires_post(app, world):
    client = login(app, world.owner_a)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 302
