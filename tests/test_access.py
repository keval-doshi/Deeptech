"""Access control, IDOR protection and public data exposure."""
from extensions import db
from models import Startup
from tests.conftest import login

PRIVATE_KEYS = {"amount", "amount_paise", "bid", "bids", "qualifying_bid", "minimum_next_bid", "current_bid"}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_public_apis_never_expose_bid_amounts(client, world):
    for url in ("/api/startups", "/api/startups?sort=promoted", f"/api/startups/{world.c.slug}",
                "/api/funding", "/api/categories", "/api/stats"):
        data = client.get(url).get_json()
        leaked = PRIVATE_KEYS & set(_walk_keys(data))
        assert not leaked, f"{url} leaked {leaked}"
    listing = client.get("/api/startups?sort=promoted").get_json()["items"]
    assert [s["promoted_rank"] for s in listing[:3]] == [1, 2, 3]


def test_public_pages_do_not_render_amounts(client, world):
    html = client.get("/").data.decode() + client.get(f"/startups/{world.c.slug}").data.decode()
    assert "1,500" not in html and "₹1500" not in html


def test_anonymous_users_are_redirected_or_401(client, world):
    assert client.get("/dashboard/bids").status_code == 302
    response = client.get("/api/dashboard/bids")
    assert response.status_code == 401 and response.get_json()["ok"] is False
    assert client.post("/api/bids", json={}).status_code == 401


def test_investor_cannot_use_bidding(app, world):
    client = login(app, world.investor)
    assert client.get("/api/dashboard/bids").status_code == 403
    assert client.post("/api/bids", json={"position": 1, "amount": 5000}).status_code == 403


def test_non_admin_cannot_open_admin(app, world):
    assert login(app, world.owner_a).get("/admin").status_code == 403
    assert login(app, world.admin).get("/admin").status_code == 200


def test_owner_cannot_edit_another_startup(app, world):
    client = login(app, world.owner_a)
    response = client.put(f"/api/startups/{world.b.id}", json={"tagline": "Hijacked tagline here"})
    assert response.status_code == 404
    assert db.session.get(Startup, world.b.id).tagline != "Hijacked tagline here"
    assert client.post(f"/api/startups/{world.b.id}/founders", data={"name": "X", "title": "Y"}).status_code == 404


def test_owner_can_edit_own_startup(app, world):
    client = login(app, world.owner_a)
    response = client.put(f"/api/startups/{world.a.id}", json={"tagline": "A brand new tagline"})
    assert response.status_code == 200
    assert db.session.get(Startup, world.a.id).tagline == "A brand new tagline"


def test_owner_cannot_read_other_startups_bids(app, world):
    from models.bid import Bid
    other_bid = db.session.scalars(db.select(Bid).where(Bid.startup_id == world.c.id)).first()
    client = login(app, world.owner_a)
    assert client.get(f"/api/bids/{other_bid.id}").status_code == 404
    assert client.post(f"/api/bids/{other_bid.id}/cancel").status_code == 404
    assert client.post("/api/payments/checkout", json={"bid_id": other_bid.id}).status_code == 404


def test_owner_board_hides_competitor_identities(app, world):
    data = login(app, world.owner_a).get("/api/dashboard/bids").get_json()
    text = str(data)
    assert world.c.name not in text and world.d.name not in text
    history = login(app, world.owner_a).get("/api/bids/history").get_json()
    assert all(item["amount"] == 500 for item in history["items"])  # only A's own bid


def test_unpublished_startup_is_hidden(client, world):
    assert client.get(f"/startups/{world.hidden.slug}").status_code == 404
    assert client.get(f"/api/startups/{world.hidden.slug}").status_code == 404


def test_security_headers_present(client, world):
    response = client.get("/")
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_search_input_is_escaped_not_injected(client, world):
    response = client.get("/api/startups?q=%25' OR 1=1 --")
    assert response.status_code == 200
    assert response.get_json()["total"] == 0
