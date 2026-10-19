"""Private bidding rules: what a startup must bid to reach a position.

Every amount shown to an owner or accepted from one is computed here, on the
server, from the current database state. Client-side calculations are only a
convenience for the UI.
"""
import re
from datetime import timedelta

from sqlalchemy import select

from extensions import db
from models import Bid, RankingEvent, RankingPosition, utcnow
from models.bid import BID_ACTIVE, BID_CANCELLED, BID_EXPIRED, BID_PENDING
from models.payment import PAY_CANCELLED, PAY_CREATED, PAY_EXPIRED
from models.startup import STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED
from services import ranking_service
from services.audit_service import audit

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class BidError(Exception):
    def __init__(self, message, status=400, field=None, data=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field
        self.data = data or {}


def ensure_rankings_fresh():
    """Expire lapsed rankings lazily so public pages never show stale promotions.

    Also expires abandoned checkouts. A cron job (`flask bids maintain`) does
    the same thing on a schedule; this is the safety net.
    """
    now = utcnow()
    stale_rank = db.session.execute(
        select(RankingPosition.position).join(Bid, Bid.id == RankingPosition.bid_id)
        .where(Bid.expires_at.is_not(None), Bid.expires_at <= now).limit(1)
    ).first()
    if stale_rank:
        rules = ranking_service.get_rules(lock=True)
        ranking_service.recompute_rankings(rules, now)
        db.session.commit()


def expire_stale_checkouts(startup_id=None, now=None):
    now = now or utcnow()
    query = select(Bid).where(Bid.status == BID_PENDING, Bid.checkout_expires_at <= now)
    if startup_id is not None:
        query = query.where(Bid.startup_id == startup_id)
    expired = db.session.scalars(query).all()
    for bid in expired:
        _close_pending(bid, BID_EXPIRED, PAY_EXPIRED, "Checkout window elapsed")
    return expired


def _close_pending(bid, bid_status, payment_status, detail):
    bid.status = bid_status
    for payment in bid.payments:
        if payment.status == PAY_CREATED:
            payment.status = payment_status
    db.session.add(RankingEvent(startup_id=bid.startup_id, bid_id=bid.id, event_type=f"bid_{bid_status}",
                                detail=detail))


def _others_amounts(startup_id, now=None):
    """Amounts of every live bid except this startup's own, best first."""
    return [b.amount_paise for b in ranking_service.active_bids(now) if b.startup_id != startup_id]


def current_position(startup_id):
    row = db.session.execute(
        select(RankingPosition.position, Bid.amount_paise)
        .join(Bid, Bid.id == RankingPosition.bid_id)
        .where(RankingPosition.startup_id == startup_id)
    ).first()
    return (row.position, row.amount_paise) if row else (None, None)


def minimum_for_position(position, others, rules):
    """Smallest amount (paise) that secures `position` against `others`."""
    if position <= len(others):
        minimum = others[position - 1] + rules.increment_paise
    else:
        minimum = rules.opening_bid_paise
    return max(minimum, rules.opening_bid_paise)


BLOCK_MESSAGES = {
    "pending_review": "Your listing is under review. Bidding opens as soon as an admin approves it "
                      "(usually within 1–2 working days).",
    "rejected": "Your listing needs changes before it can go live. Update your company profile to resubmit it.",
    "unpublished": "Your listing is not public right now, so it can't hold a ranking. Contact support.",
    "paused": "Bidding is temporarily paused by the platform. Please check back soon.",
    "unverified": "Verify your email address to place bids.",
}


def bidding_block_reason(startup, rules, user=None):
    """Why this startup/user can't bid right now, or None if they can."""
    if startup.status == STATUS_PENDING:
        return "pending_review"
    if startup.status == STATUS_REJECTED:
        return "rejected"
    if startup.status != STATUS_PUBLISHED:
        return "unpublished"
    if not rules.bidding_enabled:
        return "paused"
    if user is not None and not user.is_verified:
        return "unverified"
    return None


def position_board(startup, rules=None, user=None):
    """Owner-only view of the positions. Contains amounts but never identities."""
    rules = rules or ranking_service.get_rules()
    blocked = bidding_block_reason(startup, rules, user)
    now = utcnow()
    my_position, my_amount = current_position(startup.id)
    ranking = {
        row.position: row.amount_paise
        for row in db.session.execute(
            select(RankingPosition.position, Bid.amount_paise).join(Bid, Bid.id == RankingPosition.bid_id)
        )
    }
    others = _others_amounts(startup.id, now)
    occupied = len(ranking)
    visible = min(rules.max_positions, max(occupied + (0 if my_position else 1), 1))

    rows = []
    for position in range(1, visible + 1):
        is_mine = position == my_position
        qualifying = ranking.get(position)
        higher = (not is_mine) and (my_position is None or position < my_position)
        minimum = minimum_for_position(position, others, rules) if higher else None
        rows.append({
            "position": position,
            "is_mine": is_mine,
            "is_open": qualifying is None,
            "qualifying_bid": qualifying // 100 if qualifying else None,
            "minimum_next_bid": minimum // 100 if minimum else None,
            "higher": higher,
            "eligible": higher and blocked is None,
        })

    pending = db.session.scalars(
        select(Bid).where(Bid.startup_id == startup.id, Bid.status == BID_PENDING,
                          Bid.checkout_expires_at > now)
    ).first()
    my_active = db.session.scalars(
        select(Bid).where(Bid.startup_id == startup.id, Bid.status == BID_ACTIVE)
        .order_by(Bid.paid_at.desc())
    ).first()
    return {
        "rules": rules.to_dict(),
        "blocked_reason": blocked,
        "blocked_message": BLOCK_MESSAGES.get(blocked),
        "rejection_reason": startup.rejection_reason if blocked == "rejected" else None,
        "current_position": my_position,
        "current_bid": my_amount // 100 if my_amount else (my_active.amount_rupees if my_active else None),
        "ranking_expires_at": my_active.expires_at.isoformat() if my_active and my_active.expires_at else None,
        "positions": rows,
        "pending_bid": serialize_bid(pending) if pending else None,
        "updated_at": now.isoformat(),
    }


def parse_amount_rupees(raw):
    """Accept whole rupees as int or digit string; reject anything else."""
    if isinstance(raw, bool):
        raise BidError("Enter a whole rupee amount.", field="amount")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
    else:
        raise BidError("Enter a whole rupee amount.", field="amount")
    if value <= 0:
        raise BidError("Amount must be positive.", field="amount")
    return value


def validate_bid(startup, position, amount_paise, rules):
    """Raise BidError unless the bid can win `position` right now."""
    blocked = bidding_block_reason(startup, rules)
    if blocked:
        raise BidError(BLOCK_MESSAGES[blocked], status=409 if blocked == "paused" else 403)
    if not isinstance(position, int) or not 1 <= position <= rules.max_positions:
        raise BidError("Choose a valid position.", field="position")

    my_position, _ = current_position(startup.id)
    if my_position is not None and position >= my_position:
        raise BidError("You can only bid for a position above your current one.", field="position")

    others = _others_amounts(startup.id)
    if position > len(others) + 1:
        raise BidError("That position is not available yet.", field="position")

    minimum = minimum_for_position(position, others, rules)
    if amount_paise < minimum:
        raise BidError(f"The minimum bid for #{position} is now ₹{minimum // 100:,}.", status=409,
                       field="amount", data={"minimum_next_bid": minimum // 100})
    if amount_paise > rules.max_bid_paise:
        raise BidError(f"Bids above ₹{rules.max_bid_paise // 100:,} need manual approval.", field="amount")
    return minimum


def create_bid(user, startup, position, amount_rupees, idempotency_key):
    """Create a pending bid. Payment happens separately via payment_service."""
    if not user.is_verified:
        raise BidError("Verify your email address before placing a bid.", status=403)
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise BidError("Missing or invalid request key. Reload the page and try again.")
    amount_paise = parse_amount_rupees(amount_rupees) * 100

    rules = ranking_service.get_rules(lock=True)  # serialise with other ranking changes

    replay = db.session.scalars(
        select(Bid).where(Bid.startup_id == startup.id, Bid.idempotency_key == idempotency_key)
    ).first()
    if replay is not None:
        if replay.target_position != position or replay.amount_paise != amount_paise:
            raise BidError("This request was already used for a different bid.", status=409)
        db.session.rollback()
        return replay, False

    now = utcnow()
    expire_stale_checkouts(startup.id, now)
    validate_bid(startup, position, amount_paise, rules)

    # Only one open checkout per startup: a fresh bid replaces an abandoned one.
    open_bid = db.session.scalars(
        select(Bid).where(Bid.startup_id == startup.id, Bid.status == BID_PENDING)
    ).first()
    if open_bid is not None:
        _close_pending(open_bid, BID_CANCELLED, PAY_CANCELLED, "Replaced by a newer bid")
        db.session.flush()

    bid = Bid(
        startup_id=startup.id,
        user_id=user.id,
        target_position=position,
        amount_paise=amount_paise,
        idempotency_key=idempotency_key,
        checkout_expires_at=now + timedelta(minutes=rules.checkout_ttl_minutes),
    )
    db.session.add(bid)
    db.session.flush()
    db.session.add(RankingEvent(startup_id=startup.id, bid_id=bid.id, event_type="bid_created",
                                new_position=position, detail=f"Pending payment of ₹{amount_paise // 100:,}"))
    audit("bid.created", "bid", bid.id, actor=user, startup_id=startup.id,
          position=position, amount_paise=amount_paise)
    db.session.commit()
    return bid, True


def cancel_bid(user, bid):
    if bid.status != BID_PENDING:
        raise BidError("Only bids awaiting payment can be cancelled.", status=409)
    ranking_service.get_rules(lock=True)
    _close_pending(bid, BID_CANCELLED, PAY_CANCELLED, "Cancelled by owner")
    audit("bid.cancelled", "bid", bid.id, actor=user, startup_id=bid.startup_id)
    db.session.commit()
    return bid


def display_status(bid, ranked_position=None):
    """Human status for history tables (adds the derived 'outbid' state)."""
    if bid.status == BID_ACTIVE:
        return "active" if ranked_position else "outbid"
    return bid.status


def serialize_bid(bid, ranked_position=None):
    payment = bid.latest_payment
    return {
        "id": bid.id,
        "target_position": bid.target_position,
        "achieved_position": bid.achieved_position,
        "current_position": ranked_position,
        "amount": bid.amount_rupees,
        "status": bid.status,
        "display_status": display_status(bid, ranked_position),
        "created_at": bid.created_at.isoformat(),
        "paid_at": bid.paid_at.isoformat() if bid.paid_at else None,
        "expires_at": bid.expires_at.isoformat() if bid.expires_at else None,
        "checkout_expires_at": bid.checkout_expires_at.isoformat() if bid.checkout_expires_at else None,
        "payment_status": payment.status if payment else None,
        "receipt": payment.receipt if payment else None,
    }
