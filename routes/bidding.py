"""Private bidding dashboard (startup owners only).

Bid amounts never leave these owner-scoped endpoints. Competitor identities
are never included in any response.
"""
from datetime import timedelta

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from extensions import db, limiter
from models import Bid, RankingPosition, utcnow
from models.bid import BID_PENDING
from models.payment import PAY_CREATED
from models.user import ROLE_STARTUP_OWNER
from routes.dashboard import view_stats
from services import bidding_service, payment_service, ranking_service
from services.bidding_service import BidError
from utils.security import json_error, require_owned_startup, roles_required

bp = Blueprint("bidding", __name__)

owner_only = roles_required(ROLE_STARTUP_OWNER)


def _own_bid_or_404(bid_id, startup):
    bid = db.session.get(Bid, bid_id)
    if bid is None or bid.startup_id != startup.id:
        abort(404)
    return bid


def _my_rank():
    startup = current_user.primary_startup
    if startup is None:
        return None
    return db.session.scalar(select(RankingPosition.position).where(RankingPosition.startup_id == startup.id))


# ---- Pages ----------------------------------------------------------------

@bp.route("/dashboard/bids")
@login_required
@owner_only
def manage():
    startup = require_owned_startup(owner=True)
    return render_template("bidding.html", startup=startup, active="bids")


@bp.route("/dashboard/bids/review")
@login_required
@owner_only
def review():
    startup = require_owned_startup(owner=True)
    rules = ranking_service.get_rules()
    try:
        position = int(request.args.get("position", ""))
        amount = bidding_service.parse_amount_rupees(request.args.get("amount", ""))
        minimum = bidding_service.validate_bid(startup, position, amount * 100, rules)
    except (ValueError, BidError) as exc:
        flash(getattr(exc, "message", "Choose a position and enter a valid amount."), "error")
        return redirect(url_for("bidding.manage"))
    current_position, current_amount = bidding_service.current_position(startup.id)
    return render_template("bid_review.html", startup=startup, position=position, amount=amount,
                           minimum=minimum // 100, rules=rules, current_position=current_position,
                           current_bid=current_amount // 100 if current_amount else None,
                           ranking_until=utcnow() + timedelta(days=rules.ranking_period_days), active="bids")


@bp.route("/dashboard/bids/history")
@login_required
@owner_only
def history():
    startup = require_owned_startup(owner=True)
    return render_template("bid_history.html", startup=startup, active="history")


@bp.route("/dashboard/bids/result/<int:bid_id>")
@login_required
@owner_only
def result(bid_id):
    startup = require_owned_startup(owner=True)
    bid = _own_bid_or_404(bid_id, startup)
    outcome = request.args.get("outcome")
    return render_template("bid_result.html", startup=startup, bid=bid, outcome=outcome, active="bids")


# ---- API --------------------------------------------------------------------

@bp.get("/api/dashboard/bids")
@login_required
@owner_only
def api_board():
    startup = require_owned_startup(owner=True)
    bidding_service.ensure_rankings_fresh()
    if bidding_service.expire_stale_checkouts(startup.id):
        db.session.commit()
    board = bidding_service.position_board(startup, user=current_user)
    recent = db.session.scalars(select(Bid).where(Bid.startup_id == startup.id)
                                .order_by(Bid.created_at.desc()).limit(5)).all()
    rank = board["current_position"]
    stats = view_stats(startup.id)
    return jsonify({
        "ok": True,
        "startup": {"id": startup.id, "name": startup.name, "status": startup.status},
        "board": board,
        "summary": {"current_position": rank, "current_bid": board["current_bid"],
                    "views": stats["views"], "views_change_pct": stats["change_pct"]},
        "recent": [bidding_service.serialize_bid(b, rank if b.status == "active" else None) for b in recent],
        "email_verified": current_user.is_verified,
    })


@bp.post("/api/bids")
@login_required
@owner_only
@limiter.limit("10 per minute; 60 per hour")
def api_create():
    startup = require_owned_startup(owner=True)
    payload = request.get_json(silent=True) or {}
    position = payload.get("position")
    if isinstance(position, str) and position.isdigit():
        position = int(position)
    try:
        bid, created = bidding_service.create_bid(current_user, startup, position, payload.get("amount"),
                                                  payload.get("idempotency_key"))
    except BidError as exc:
        db.session.rollback()
        return json_error(exc.message, exc.status, field=exc.field, **exc.data)
    return jsonify({"ok": True, "created": created, "bid": bidding_service.serialize_bid(bid)}), (201 if created else 200)


@bp.get("/api/bids/history")
@login_required
@owner_only
def api_history():
    startup = require_owned_startup(owner=True)
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1
    per_page = 10
    status = request.args.get("status")
    query = select(Bid).where(Bid.startup_id == startup.id)
    if status in ("active", "pending_payment", "superseded", "expired", "cancelled", "failed"):
        query = query.where(Bid.status == status)
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    bids = db.session.scalars(query.order_by(Bid.created_at.desc())
                              .limit(per_page).offset((page - 1) * per_page)).all()
    rank = _my_rank()
    paid_total = db.session.scalar(
        select(func.coalesce(func.sum(Bid.amount_paise), 0))
        .where(Bid.startup_id == startup.id, Bid.paid_at.is_not(None)))
    return jsonify({
        "ok": True,
        "items": [bidding_service.serialize_bid(b, rank if b.status == "active" else None) for b in bids],
        "page": page, "pages": max((total + per_page - 1) // per_page, 1), "total": total,
        "paid_total": paid_total // 100,
    })


@bp.get("/api/bids/<int:bid_id>")
@login_required
@owner_only
@limiter.limit("40 per minute")
def api_bid(bid_id):
    startup = require_owned_startup(owner=True)
    bid = _own_bid_or_404(bid_id, startup)
    payment = bid.latest_payment
    # Webhook not here yet? Ask the provider directly (server-to-server).
    if (payment and payment.status == PAY_CREATED and payment.provider != "mock"
            and (utcnow() - payment.created_at).total_seconds() > 20):
        payment_service.reconcile(payment)
        db.session.refresh(bid)
    rank = _my_rank()
    return jsonify({"ok": True, "bid": bidding_service.serialize_bid(bid, rank if bid.status == "active" else None)})


@bp.post("/api/bids/<int:bid_id>/cancel")
@login_required
@owner_only
def api_cancel(bid_id):
    startup = require_owned_startup(owner=True)
    bid = _own_bid_or_404(bid_id, startup)
    if bid.status != BID_PENDING:
        return jsonify({"ok": True, "bid": bidding_service.serialize_bid(bid)})
    try:
        bidding_service.cancel_bid(current_user, bid)
    except BidError as exc:
        db.session.rollback()
        return json_error(exc.message, exc.status)
    return jsonify({"ok": True, "bid": bidding_service.serialize_bid(bid)})
