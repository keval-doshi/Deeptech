"""Payment provider integration (Razorpay, plus a local sandbox simulator).

Rules enforced here:
* The bid is re-validated before an order is created.
* A ranking changes only after a *server-verified* confirmation: a webhook
  whose signature checks out, or a direct authenticated status query to the
  provider (reconciliation). Browser callbacks never confirm a payment.
* Webhooks are idempotent (unique provider event id) and payment
  confirmation is idempotent (a paid payment is never processed twice).
"""
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass

import requests
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Payment, RankingEvent, WebhookEvent, utcnow
from models.bid import BID_ACTIVE, BID_FAILED, BID_PENDING, BID_SUPERSEDED, Bid
from models.payment import PAY_CREATED, PAY_FAILED, PAY_PAID
from services import bidding_service, ranking_service
from services.audit_service import audit
from services.bidding_service import BidError
from services.notification_service import notify_admins, notify_startup

log = logging.getLogger(__name__)


class PaymentError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class ProviderEvent:
    event_id: str
    event_type: str
    order_id: str | None
    payment_id: str | None
    amount_paise: int | None
    currency: str | None
    method: str | None
    error: str | None


def _parse_razorpay_style(payload, event_id):
    """Razorpay webhook body → ProviderEvent (the mock provider uses the same shape)."""
    entity = (payload.get("payload", {}).get("payment") or {}).get("entity") or {}
    order_entity = (payload.get("payload", {}).get("order") or {}).get("entity") or {}
    return ProviderEvent(
        event_id=event_id,
        event_type=str(payload.get("event", "")),
        order_id=entity.get("order_id") or order_entity.get("id"),
        payment_id=entity.get("id"),
        amount_paise=entity.get("amount") if entity else order_entity.get("amount_paid"),
        currency=entity.get("currency") or order_entity.get("currency"),
        method=entity.get("method"),
        error=entity.get("error_description"),
    )


def _hmac_hex(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class RazorpayProvider:
    name = "razorpay"
    api_base = "https://api.razorpay.com/v1"
    signature_header = "X-Razorpay-Signature"
    event_id_header = "X-Razorpay-Event-Id"

    def __init__(self, config):
        self.key_id = config["RAZORPAY_KEY_ID"]
        self.key_secret = config["RAZORPAY_KEY_SECRET"]
        self.webhook_secret = config["RAZORPAY_WEBHOOK_SECRET"]
        if not (self.key_id and self.key_secret and self.webhook_secret):
            raise PaymentError("Razorpay is selected but its keys are not configured.", status=503)

    def create_order(self, amount_paise, receipt, notes):
        try:
            response = requests.post(
                f"{self.api_base}/orders",
                auth=(self.key_id, self.key_secret),
                json={"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes},
                timeout=15,
            )
        except requests.RequestException as exc:
            log.exception("Razorpay order creation failed")
            raise PaymentError("Could not reach the payment provider. Please try again.") from exc
        if response.status_code >= 300:
            log.error("Razorpay order error %s: %s", response.status_code, response.text[:500])
            raise PaymentError("The payment provider rejected the order.")
        return response.json()["id"]

    def checkout_options(self, payment, user, startup):
        return {
            "provider": self.name,
            "key": self.key_id,
            "order_id": payment.provider_order_id,
            "amount": payment.amount_paise,
            "currency": payment.currency,
            "name": "DeeptechIndia.in",
            "description": f"Ranking bid #{payment.bid.target_position} for {startup.name}",
            "prefill": {"name": user.name, "email": user.email},
        }

    def verify_webhook(self, raw_body, headers):
        signature = headers.get(self.signature_header, "")
        expected = _hmac_hex(self.webhook_secret, raw_body)
        return bool(signature) and hmac.compare_digest(expected, signature)

    def parse_webhook(self, raw_body, headers):
        payload = json.loads(raw_body)
        event_id = headers.get(self.event_id_header) or hashlib.sha256(raw_body).hexdigest()
        return _parse_razorpay_style(payload, event_id)

    def fetch_order_payment(self, order_id):
        """Ask Razorpay directly for a captured payment on this order."""
        try:
            response = requests.get(f"{self.api_base}/orders/{order_id}/payments",
                                    auth=(self.key_id, self.key_secret), timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            log.exception("Razorpay reconciliation failed for %s", order_id)
            return None
        for item in response.json().get("items", []):
            if item.get("status") == "captured":
                return ProviderEvent(f"reconcile:{item['id']}", "payment.captured", order_id, item["id"],
                                     item.get("amount"), item.get("currency"), item.get("method"), None)
        return None


class MockProvider:
    """Local sandbox that mimics Razorpay's order + signed-webhook flow.

    Its checkout page posts a webhook signed with MOCK_WEBHOOK_SECRET through
    the exact same verification and confirmation code as production.
    """
    name = "mock"
    signature_header = "X-Mock-Signature"
    event_id_header = "X-Mock-Event-Id"

    def __init__(self, config):
        self.webhook_secret = config["MOCK_WEBHOOK_SECRET"]

    def create_order(self, amount_paise, receipt, notes):
        return f"order_mock_{secrets.token_hex(8)}"

    def checkout_options(self, payment, user, startup):
        return {
            "provider": self.name,
            "order_id": payment.provider_order_id,
            "amount": payment.amount_paise,
            "currency": payment.currency,
            "redirect_url": f"/payments/mock-checkout/{payment.receipt}",
        }

    def build_webhook(self, payment, outcome):
        payment_id = f"pay_mock_{secrets.token_hex(8)}"
        captured = outcome == "success"
        body = {
            "entity": "event",
            "event": "payment.captured" if captured else "payment.failed",
            "contains": ["payment"],
            "payload": {"payment": {"entity": {
                "id": payment_id,
                "order_id": payment.provider_order_id,
                "amount": payment.amount_paise,
                "currency": payment.currency,
                "status": "captured" if captured else "failed",
                "method": "upi",
                "error_description": None if captured else "Payment declined in sandbox",
            }}},
            "created_at": int(utcnow().timestamp()),
        }
        raw = json.dumps(body).encode()
        headers = {self.signature_header: _hmac_hex(self.webhook_secret, raw),
                   self.event_id_header: f"evt_mock_{secrets.token_hex(8)}"}
        return raw, headers

    def verify_webhook(self, raw_body, headers):
        signature = headers.get(self.signature_header, "")
        return bool(signature) and hmac.compare_digest(_hmac_hex(self.webhook_secret, raw_body), signature)

    def parse_webhook(self, raw_body, headers):
        return _parse_razorpay_style(json.loads(raw_body), headers.get(self.event_id_header)
                                     or hashlib.sha256(raw_body).hexdigest())

    def fetch_order_payment(self, order_id):
        return None


PROVIDERS = {"razorpay": RazorpayProvider, "mock": MockProvider}


def get_provider(name=None):
    name = name or current_app.config["PAYMENT_PROVIDER"]
    if name not in PROVIDERS:
        raise PaymentError(f"Unknown payment provider '{name}'.", status=503)
    return PROVIDERS[name](current_app.config)


# --------------------------------------------------------------------------
# Checkout
# --------------------------------------------------------------------------

def create_checkout(user, bid):
    """Re-validate a pending bid and open a provider order for it."""
    provider = get_provider()
    rules = ranking_service.get_rules(lock=True)
    now = utcnow()
    if bid.status != BID_PENDING:
        raise BidError("This bid is no longer awaiting payment.", status=409)
    if bid.checkout_expires_at and bid.checkout_expires_at <= now:
        bidding_service.expire_stale_checkouts(bid.startup_id, now)
        db.session.commit()
        raise BidError("This checkout has expired. Please place the bid again.", status=410)

    existing = next((p for p in bid.payments if p.status == PAY_CREATED and p.provider == provider.name), None)
    if existing is not None:
        db.session.rollback()
        return provider.checkout_options(existing, user, bid.startup)

    try:
        bidding_service.validate_bid(bid.startup, bid.target_position, bid.amount_paise, rules)
    except BidError:
        bid.status = BID_FAILED
        db.session.add(RankingEvent(startup_id=bid.startup_id, bid_id=bid.id, event_type="bid_invalidated",
                                    detail="Position changed before payment"))
        db.session.commit()
        raise
    # Release the ranking lock before calling the provider over the network.
    db.session.commit()

    receipt = f"DTI{bid.id:06d}{secrets.token_hex(3).upper()}"
    order_id = provider.create_order(bid.amount_paise, receipt,
                                     {"bid_id": str(bid.id), "startup_id": str(bid.startup_id)})
    payment = Payment(bid_id=bid.id, user_id=user.id, startup_id=bid.startup_id, provider=provider.name,
                      provider_order_id=order_id, receipt=receipt, amount_paise=bid.amount_paise)
    db.session.add(payment)
    db.session.flush()
    audit("payment.checkout_created", "payment", payment.id, actor=user, bid_id=bid.id,
          order_id=order_id, amount_paise=bid.amount_paise, provider=provider.name)
    db.session.commit()
    return provider.checkout_options(payment, user, bid.startup)


# --------------------------------------------------------------------------
# Webhooks & confirmation
# --------------------------------------------------------------------------

def handle_webhook(raw_body, headers, provider=None):
    """Verify, de-duplicate and process a provider webhook.

    Returns (http_status, message). Raises nothing for bad input.
    """
    provider = provider or get_provider()
    if not provider.verify_webhook(raw_body, headers):
        log.warning("Rejected %s webhook with invalid signature", provider.name)
        return 400, "invalid signature"
    try:
        event = provider.parse_webhook(raw_body, headers)
    except (ValueError, KeyError, TypeError):
        return 400, "malformed payload"

    event_id = event.event_id[:100]
    record = db.session.scalars(select(WebhookEvent).where(WebhookEvent.provider == provider.name,
                                                           WebhookEvent.event_id == event_id)).first()
    if record is not None and record.status != "error":
        return 200, "duplicate event"
    if record is None:  # an errored event is re-processed when the provider retries it
        record = WebhookEvent(provider=provider.name, event_id=event_id, event_type=event.event_type[:60],
                              signature_valid=True, payload=raw_body.decode("utf-8", "replace")[:20000])
        db.session.add(record)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return 200, "duplicate event"
    record_id = record.id

    try:
        if event.event_type in ("payment.captured", "order.paid"):
            outcome = confirm_payment(provider.name, event)
        elif event.event_type == "payment.failed":
            outcome = fail_payment(provider.name, event)
        else:
            outcome = "ignored"
        record = db.session.get(WebhookEvent, record_id)
        record.status = "processed" if outcome != "ignored" else "ignored"
        record.error = None if outcome in ("processed", "ignored") else outcome
        record.processed_at = utcnow()
        db.session.commit()
        return 200, outcome
    except Exception as exc:  # keep the event row; a non-2xx makes the provider retry
        db.session.rollback()
        log.exception("Webhook processing failed")
        record = db.session.get(WebhookEvent, record_id)
        record.status = "error"
        record.error = str(exc)[:255]
        db.session.commit()
        return 500, "processing error"


def _find_payment(provider_name, order_id, lock=True):
    query = select(Payment).where(Payment.provider == provider_name, Payment.provider_order_id == order_id)
    if lock:
        query = query.with_for_update()
    return db.session.scalars(query).first()


def confirm_payment(provider_name, event):
    """Mark a payment paid and apply its bid to the ranking (idempotent)."""
    rules = ranking_service.get_rules(lock=True)
    payment = _find_payment(provider_name, event.order_id) if event.order_id else None
    if payment is None:
        db.session.rollback()
        return "ignored"
    if payment.status == PAY_PAID:
        db.session.rollback()
        return "already processed"

    if event.amount_paise != payment.amount_paise or (event.currency or "INR") != payment.currency:
        payment.failure_reason = "Amount mismatch: manual review required"
        audit("payment.amount_mismatch", "payment", payment.id, expected=payment.amount_paise,
              received=event.amount_paise, currency=event.currency)
        notify_admins("Payment amount mismatch", f"Receipt {payment.receipt} needs manual review.", "/admin#payments")
        db.session.commit()
        return "amount mismatch"

    now = utcnow()
    payment.status = PAY_PAID
    payment.provider_payment_id = event.payment_id
    payment.method = event.method
    payment.paid_at = now
    payment.failure_reason = None

    bid = payment.bid
    # A captured payment is honoured even if the owner closed the checkout
    # window or it expired meanwhile: the money was taken.
    for previous in db.session.scalars(select(Bid).where(Bid.startup_id == bid.startup_id,
                                                         Bid.status == BID_ACTIVE, Bid.id != bid.id)):
        previous.status = BID_SUPERSEDED
    bid.status = BID_ACTIVE
    bid.paid_at = now
    bid.expires_at = ranking_service.ranking_expiry(rules, now)
    db.session.flush()

    ranking_service.recompute_rankings(rules, now)
    position, _ = bidding_service.current_position(bid.startup_id)
    bid.achieved_position = position
    db.session.add(RankingEvent(startup_id=bid.startup_id, bid_id=bid.id, event_type="payment_confirmed",
                                new_position=position, detail=f"₹{bid.amount_rupees:,} confirmed"))
    audit("payment.confirmed", "payment", payment.id, bid_id=bid.id, startup_id=bid.startup_id,
          amount_paise=payment.amount_paise, provider_payment_id=event.payment_id,
          target_position=bid.target_position, achieved_position=position)

    if position == bid.target_position:
        title = f"Payment received. You're now ranked #{position}"
        body = f"Your ₹{bid.amount_rupees:,} bid is confirmed for {rules.ranking_period_days} days."
    elif position:
        title = f"Payment received. You're ranked #{position}"
        body = (f"Another bid for #{bid.target_position} was confirmed moments before yours, "
                "so your amount placed you one spot lower. You can top up from Manage Bids.")
    else:
        title = "Payment received, but positions changed"
        body = "Your bid no longer places in the paid positions. Our team will contact you."
        notify_admins("Paid bid did not place", f"Bid {bid.id} paid but unranked; review for refund.",
                      "/admin#payments")
    notify_startup(bid.startup_id, title, body, f"/dashboard/bids/result/{bid.id}", "payment")
    db.session.commit()
    return "processed"


def fail_payment(provider_name, event):
    payment = _find_payment(provider_name, event.order_id) if event.order_id else None
    if payment is None:
        db.session.rollback()
        return "ignored"
    if payment.status == PAY_PAID:
        # Razorpay allows several attempts per order; a late failure of one
        # attempt must not undo another attempt's success.
        db.session.rollback()
        return "ignored"
    payment.status = PAY_FAILED
    payment.failure_reason = (event.error or "Payment failed")[:255]
    bid = payment.bid
    if bid.status == BID_PENDING:
        bid.status = BID_FAILED
    db.session.add(RankingEvent(startup_id=bid.startup_id, bid_id=bid.id, event_type="payment_failed",
                                detail=payment.failure_reason))
    audit("payment.failed", "payment", payment.id, bid_id=bid.id, reason=payment.failure_reason)
    notify_startup(bid.startup_id, "Payment failed", "Your ranking did not change. You can try again.",
                   f"/dashboard/bids/result/{bid.id}", "payment")
    db.session.commit()
    return "processed"


def reconcile(payment):
    """Query the provider directly for a payment still marked 'created'."""
    if payment.status != PAY_CREATED:
        return payment.status
    provider = get_provider(payment.provider)
    event = provider.fetch_order_payment(payment.provider_order_id)
    if event is not None:
        confirm_payment(provider.name, event)
    return db.session.get(Payment, payment.id).status
