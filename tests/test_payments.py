"""Payment confirmation: signatures, idempotency, failures and races."""
import json
from datetime import timedelta

from extensions import db
from models import AuditLog, Payment, RankingPosition, WebhookEvent, utcnow
from models.bid import BID_ACTIVE, BID_FAILED, BID_SUPERSEDED, Bid
from services.payment_service import MockProvider, _hmac_hex
from services import bidding_service
from tests.conftest import login, payments_for


def _place_and_checkout(client, position, amount, key):
    bid = client.post("/api/bids", json={"position": position, "amount": amount, "idempotency_key": key}).get_json()["bid"]
    checkout = client.post("/api/payments/checkout", json={"bid_id": bid["id"]})
    assert checkout.status_code == 200, checkout.get_json()
    return bid["id"], checkout.get_json()["checkout"]


def _webhook(app, payment, outcome="success", amount=None, event_id=None, event_type=None):
    provider = MockProvider(app.config)
    raw, headers = provider.build_webhook(payment, outcome)
    if amount is not None or event_type:
        body = json.loads(raw)
        if amount is not None:
            body["payload"]["payment"]["entity"]["amount"] = amount
        if event_type:
            body["event"] = event_type
        raw = json.dumps(body).encode()
        headers[provider.signature_header] = _hmac_hex(app.config["MOCK_WEBHOOK_SECRET"], raw)
    if event_id:
        headers[provider.event_id_header] = event_id
    return app.test_client().post("/api/payments/webhook", data=raw, headers=headers, content_type="application/json")


def _rank(startup_id):
    return db.session.scalar(db.select(RankingPosition.position).where(RankingPosition.startup_id == startup_id))


def test_ranking_changes_only_after_verified_webhook(app, world):
    client = login(app, world.owner_a)
    bid_id, checkout = _place_and_checkout(client, 2, 900, "a" * 32)
    assert checkout["provider"] == "mock" and checkout["amount"] == 90_000
    assert _rank(world.a.id) == 3  # unchanged until payment is confirmed

    payment = payments_for(bid_id)[0]
    response = _webhook(app, payment)
    assert response.status_code == 200 and response.get_json()["result"] == "processed"

    bid = db.session.get(Bid, bid_id)
    assert bid.status == BID_ACTIVE and bid.achieved_position == 2
    assert db.session.get(Payment, payment.id).status == "paid"
    assert _rank(world.a.id) == 2 and _rank(world.d.id) == 3
    # The previous ₹500 bid is superseded, not double counted.
    assert db.session.scalar(db.select(db.func.count(Bid.id)).where(Bid.startup_id == world.a.id,
                                                                    Bid.status == BID_SUPERSEDED)) == 1
    actions = set(db.session.scalars(db.select(AuditLog.action)))
    assert {"bid.created", "payment.checkout_created", "payment.confirmed"} <= actions


def test_invalid_signature_is_rejected(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    payment = payments_for(bid_id)[0]
    raw, headers = MockProvider(app.config).build_webhook(payment, "success")
    headers["X-Mock-Signature"] = "0" * 64
    response = app.test_client().post("/api/payments/webhook", data=raw, headers=headers)
    assert response.status_code == 400
    assert db.session.get(Payment, payment.id).status == "created"
    assert _rank(world.a.id) == 3
    assert db.session.scalar(db.select(db.func.count(WebhookEvent.id))) == 0


def test_browser_cannot_forge_confirmation(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    # A logged-in user posting an unsigned event straight to the webhook achieves nothing.
    payment = payments_for(bid_id)[0]
    raw, _ = MockProvider(app.config).build_webhook(payment, "success")
    assert client.post("/api/payments/webhook", data=raw).status_code == 400
    assert db.session.get(Bid, bid_id).status == "pending_payment"


def test_duplicate_webhooks_are_idempotent(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    payment = payments_for(bid_id)[0]
    assert _webhook(app, payment, event_id="evt_same").get_json()["result"] == "processed"
    assert _webhook(app, payment, event_id="evt_same").get_json()["result"] == "duplicate event"
    # A different event for the same order (e.g. order.paid after payment.captured)
    assert _webhook(app, payment, event_id="evt_other", event_type="order.paid").get_json()["result"] == "already processed"
    confirmations = db.session.scalar(db.select(db.func.count(AuditLog.id)).where(AuditLog.action == "payment.confirmed"))
    assert confirmations == 1
    assert _rank(world.a.id) == 2


def test_failed_payment_leaves_ranking_unchanged(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    payment = payments_for(bid_id)[0]
    assert _webhook(app, payment, outcome="failure").status_code == 200
    assert db.session.get(Bid, bid_id).status == BID_FAILED
    assert db.session.get(Payment, payment.id).status == "failed"
    assert _rank(world.a.id) == 3


def test_retry_after_failed_attempt_on_same_order_succeeds(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    payment = payments_for(bid_id)[0]
    _webhook(app, payment, outcome="failure")
    _webhook(app, payment, outcome="success")
    assert db.session.get(Bid, bid_id).status == BID_ACTIVE
    assert _rank(world.a.id) == 2


def test_amount_mismatch_is_not_ranked(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    payment = payments_for(bid_id)[0]
    response = _webhook(app, payment, amount=100)
    assert response.get_json()["result"] == "amount mismatch"
    assert db.session.get(Payment, payment.id).status == "created"
    assert _rank(world.a.id) == 3


def test_simultaneous_bids_cannot_corrupt_order(app, world):
    """Two startups pay ₹900 for #2; the first confirmed wins, the other lands at #3."""
    a_client, b_client = login(app, world.owner_a), login(app, world.owner_b)
    a_bid, _ = _place_and_checkout(a_client, 2, 900, "a" * 32)
    b_bid, _ = _place_and_checkout(b_client, 2, 900, "b" * 32)
    _webhook(app, payments_for(b_bid)[0])
    _webhook(app, payments_for(a_bid)[0])
    assert _rank(world.b.id) == 2 and _rank(world.a.id) == 3
    assert db.session.get(Bid, a_bid).achieved_position == 3
    positions = db.session.scalars(db.select(RankingPosition.position).order_by(RankingPosition.position)).all()
    assert positions == list(range(1, len(positions) + 1))  # contiguous and unique


def test_checkout_revalidates_bid(app, world):
    a_client, b_client = login(app, world.owner_a), login(app, world.owner_b)
    a_bid = a_client.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": "a" * 32}).get_json()["bid"]
    b_bid, _ = _place_and_checkout(b_client, 1, 2000, "b" * 32)
    _webhook(app, payments_for(b_bid)[0])  # B is now #1, C drops to #2 with ₹1,500
    response = a_client.post("/api/payments/checkout", json={"bid_id": a_bid["id"]})
    assert response.status_code == 409
    assert db.session.get(Bid, a_bid["id"]).status == BID_FAILED
    assert not payments_for(a_bid["id"])


def test_late_capture_after_cancel_is_honoured(app, world):
    client = login(app, world.owner_a)
    bid_id, _ = _place_and_checkout(client, 2, 900, "a" * 32)
    assert client.post(f"/api/bids/{bid_id}/cancel").status_code == 200
    payment = payments_for(bid_id)[0]
    _webhook(app, payment)  # the provider captured money anyway
    assert db.session.get(Bid, bid_id).status == BID_ACTIVE
    assert _rank(world.a.id) == 2


def test_expired_checkout_cannot_be_paid(app, world):
    client = login(app, world.owner_a)
    bid = client.post("/api/bids", json={"position": 2, "amount": 900, "idempotency_key": "a" * 32}).get_json()["bid"]
    record = db.session.get(Bid, bid["id"])
    record.checkout_expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert client.post("/api/payments/checkout", json={"bid_id": bid["id"]}).status_code == 410


def test_lapsed_rankings_expire(app, world):
    bid = db.session.scalars(db.select(Bid).where(Bid.startup_id == world.c.id)).first()
    bid.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    bidding_service.ensure_rankings_fresh()
    assert _rank(world.c.id) is None and _rank(world.d.id) == 1 and _rank(world.a.id) == 2


def test_mock_checkout_page_runs_full_flow(app, world):
    client = login(app, world.owner_a)
    bid_id, checkout = _place_and_checkout(client, 1, 1600, "a" * 32)
    assert client.get(checkout["redirect_url"]).status_code == 200
    response = client.post(checkout["redirect_url"], data={"outcome": "success"})
    assert response.status_code == 302
    assert _rank(world.a.id) == 1
    other = login(app, world.owner_b)
    assert other.get(checkout["redirect_url"]).status_code == 404  # not their payment
