"""Server-side bid rules: minimums, eligibility, idempotency and duplicates."""
from extensions import db
from models import BiddingRules
from models.bid import BID_CANCELLED, BID_PENDING, Bid
from tests.conftest import login

KEY = "k" * 32


def _board(client):
    return client.get("/api/dashboard/bids").get_json()["board"]


def test_board_computes_minimums_on_server(app, world):
    board = _board(login(app, world.owner_a))
    assert board["current_position"] == 3 and board["current_bid"] == 500
    rows = {r["position"]: r for r in board["positions"]}
    assert rows[1]["qualifying_bid"] == 1500 and rows[1]["minimum_next_bid"] == 1600
    assert rows[2]["minimum_next_bid"] == 900
    assert rows[3]["is_mine"] and not rows[3]["eligible"]


def test_unranked_startup_sees_open_position(app, world):
    board = _board(login(app, world.owner_b))
    rows = {r["position"]: r for r in board["positions"]}
    assert rows[4]["is_open"] and rows[4]["minimum_next_bid"] == 100  # opening bid
    assert rows[3]["minimum_next_bid"] == 600


def test_bid_below_minimum_is_rejected(app, world):
    response = login(app, world.owner_a).post("/api/bids", json={"position": 2, "amount": 850, "idempotency_key": KEY})
    assert response.status_code == 409
    assert response.get_json()["minimum_next_bid"] == 900
    assert not db.session.scalars(db.select(Bid).where(Bid.status == BID_PENDING)).first()


def test_cannot_bid_for_own_or_lower_position(app, world):
    client = login(app, world.owner_a)
    assert client.post("/api/bids", json={"position": 3, "amount": 5000, "idempotency_key": KEY}).status_code == 400
    assert client.post("/api/bids", json={"position": 4, "amount": 5000, "idempotency_key": KEY}).status_code == 400


def test_invalid_amounts_rejected(app, world):
    client = login(app, world.owner_a)
    for amount in ("900.50", -900, "abc", True, None):
        response = client.post("/api/bids", json={"position": 2, "amount": amount, "idempotency_key": KEY})
        assert response.status_code == 400, amount


def test_valid_bid_creates_pending_record(app, world):
    response = login(app, world.owner_a).post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": KEY})
    assert response.status_code == 201
    bid = db.session.get(Bid, response.get_json()["bid"]["id"])
    assert bid.status == BID_PENDING and bid.amount_paise == 90_000 and bid.target_position == 2


def test_idempotent_replay_returns_same_bid(app, world):
    client = login(app, world.owner_a)
    first = client.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": KEY})
    second = client.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": KEY})
    assert first.status_code == 201 and second.status_code == 200
    assert first.get_json()["bid"]["id"] == second.get_json()["bid"]["id"]
    assert db.session.scalar(db.select(db.func.count(Bid.id)).where(Bid.status == BID_PENDING)) == 1
    conflict = client.post("/api/bids", json={"position": 2, "amount": 1000, "idempotency_key": KEY})
    assert conflict.status_code == 409


def test_new_bid_replaces_abandoned_checkout(app, world):
    client = login(app, world.owner_a)
    first = client.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": "a" * 32}).get_json()["bid"]
    second = client.post("/api/bids", json={"position": 1, "amount": 1600, "idempotency_key": "b" * 32}).get_json()["bid"]
    assert db.session.get(Bid, first["id"]).status == BID_CANCELLED
    assert db.session.get(Bid, second["id"]).status == BID_PENDING


def test_unverified_owner_cannot_bid(app, world):
    response = login(app, world.unverified).post("/api/bids", json={"position": 1, "amount": 5000, "idempotency_key": KEY})
    assert response.status_code == 403


def test_bidding_can_be_paused(app, world):
    db.session.get(BiddingRules, 1).bidding_enabled = False
    db.session.commit()
    response = login(app, world.owner_a).post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": KEY})
    assert response.status_code == 409


def test_admin_configured_increment_applies(app, world):
    rules = db.session.get(BiddingRules, 1)
    rules.increment_paise = 25_000  # ₹250
    db.session.commit()
    rows = {r["position"]: r for r in _board(login(app, world.owner_a))["positions"]}
    assert rows[2]["minimum_next_bid"] == 1050


def test_missing_idempotency_key_rejected(app, world):
    response = login(app, world.owner_a).post("/api/bids", json={"position": 2, "amount": 900})
    assert response.status_code == 400
