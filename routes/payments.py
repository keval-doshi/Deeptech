from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from extensions import csrf, db, limiter
from models import Bid, Payment
from models.payment import PAY_CREATED
from models.user import ROLE_STARTUP_OWNER
from services import bidding_service, payment_service
from services.bidding_service import BidError
from services.payment_service import MockProvider, PaymentError
from utils.security import json_error, require_owned_startup, roles_required

bp = Blueprint("payments", __name__)


@bp.post("/api/payments/checkout")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
@limiter.limit("10 per minute; 40 per hour")
def api_checkout():
    startup = require_owned_startup(owner=True)
    payload = request.get_json(silent=True) or {}
    bid = db.session.get(Bid, payload.get("bid_id")) if str(payload.get("bid_id", "")).isdigit() else None
    if bid is None or bid.startup_id != startup.id:
        return json_error("Bid not found.", 404)
    try:
        options = payment_service.create_checkout(current_user, bid)
    except BidError as exc:
        db.session.rollback()
        return json_error(exc.message, exc.status, **exc.data)
    except PaymentError as exc:
        db.session.rollback()
        return json_error(exc.message, exc.status)
    options["result_url"] = url_for("bidding.result", bid_id=bid.id)
    return jsonify({"ok": True, "checkout": options})


@bp.post("/api/payments/webhook")
@csrf.exempt
@limiter.exempt
def webhook():
    """Provider → server notification. The signature is the only authentication."""
    raw = request.get_data(cache=False, as_text=False)
    if len(raw) > 512 * 1024:
        return json_error("payload too large", 413)
    status, message = payment_service.handle_webhook(raw, request.headers)
    return jsonify({"ok": status < 300, "result": message}), status


# ---- Local sandbox checkout (PAYMENT_PROVIDER=mock only) ---------------------

def _mock_payment_or_404(receipt):
    if current_app.config["PAYMENT_PROVIDER"] != "mock" or current_app.config["ENV_NAME"] == "production":
        abort(404)
    startup = require_owned_startup(owner=True)
    payment = db.session.scalars(select(Payment).where(Payment.receipt == receipt)).first()
    if payment is None or payment.startup_id != startup.id or payment.provider != "mock":
        abort(404)
    return payment


@bp.get("/payments/mock-checkout/<receipt>")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def mock_checkout(receipt):
    payment = _mock_payment_or_404(receipt)
    return render_template("mock_checkout.html", payment=payment, startup=payment.startup)


@bp.post("/payments/mock-checkout/<receipt>")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
def mock_checkout_submit(receipt):
    payment = _mock_payment_or_404(receipt)
    outcome = request.form.get("outcome")
    bid_id = payment.bid_id
    if outcome == "cancel":
        if payment.bid.status == "pending_payment":
            bidding_service.cancel_bid(current_user, payment.bid)
        return redirect(url_for("bidding.result", bid_id=bid_id))
    if payment.status == PAY_CREATED or outcome == "success":
        provider = MockProvider(current_app.config)
        raw, headers = provider.build_webhook(payment, "success" if outcome == "success" else "failure")
        # Runs the same signature verification + processing as a real webhook.
        payment_service.handle_webhook(raw, headers, provider=provider)
    return redirect(url_for("bidding.result", bid_id=bid_id))
