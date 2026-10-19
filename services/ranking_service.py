"""Paid ranking computation.

The ranking is derived purely from *confirmed, unexpired* bids: highest
amount first, earlier confirmation wins a tie. Because it is recomputed from
the database while holding the bidding-rules row lock, concurrent payments
cannot leave the order in an inconsistent state.
"""
from datetime import timedelta

from sqlalchemy import or_, select

from extensions import db
from models import Bid, BiddingRules, RankingEvent, RankingPosition, Startup, utcnow
from models.bid import BID_ACTIVE, BID_EXPIRED
from models.startup import STATUS_PUBLISHED
from services.notification_service import notify_startup


def get_rules(lock=False):
    """Return the singleton BiddingRules row, optionally locking it.

    Locking serialises ranking changes (FOR UPDATE on PostgreSQL; SQLite
    serialises writers on its own).
    """
    query = select(BiddingRules).where(BiddingRules.id == 1)
    if lock:
        query = query.with_for_update()
    rules = db.session.execute(query).scalar_one_or_none()
    if rules is None:
        rules = BiddingRules(id=1)
        db.session.add(rules)
        db.session.flush()
    return rules


def active_bids(now=None):
    """All live paid bids, best first. One per startup (older ones are superseded)."""
    now = now or utcnow()
    query = (
        select(Bid)
        .join(Startup, Startup.id == Bid.startup_id)
        .where(
            Bid.status == BID_ACTIVE,
            or_(Bid.expires_at.is_(None), Bid.expires_at > now),
            Startup.status == STATUS_PUBLISHED,
        )
        .order_by(Bid.amount_paise.desc(), Bid.paid_at.asc(), Bid.id.asc())
    )
    return db.session.scalars(query).all()


def expire_lapsed_bids(now=None):
    now = now or utcnow()
    lapsed = db.session.scalars(
        select(Bid).where(Bid.status == BID_ACTIVE, Bid.expires_at.is_not(None), Bid.expires_at <= now)
    ).all()
    for bid in lapsed:
        bid.status = BID_EXPIRED
        db.session.add(RankingEvent(startup_id=bid.startup_id, bid_id=bid.id, event_type="ranking_expired",
                                    detail="Paid ranking period ended"))
        notify_startup(bid.startup_id, "Your paid ranking period has ended",
                       "Place a new bid to keep your startup promoted.", "/dashboard/bids", "bid")
    return lapsed


def recompute_rankings(rules, now=None):
    """Rebuild ranking_positions. Caller must hold the rules lock and commit.

    Returns {startup_id: (old_position, new_position)} for every change.
    """
    now = now or utcnow()
    expire_lapsed_bids(now)

    ordered = active_bids(now)[: rules.max_positions]
    new_positions = {bid.startup_id: (index, bid) for index, bid in enumerate(ordered, start=1)}
    old_positions = {row.startup_id: row.position for row in db.session.scalars(select(RankingPosition))}

    db.session.execute(RankingPosition.__table__.delete())
    db.session.flush()
    for startup_id, (position, bid) in new_positions.items():
        db.session.add(RankingPosition(position=position, startup_id=startup_id, bid_id=bid.id, updated_at=now))
    db.session.flush()

    changes = {}
    for startup_id in set(old_positions) | set(new_positions):
        old = old_positions.get(startup_id)
        new = new_positions.get(startup_id, (None, None))[0]
        if old == new:
            continue
        changes[startup_id] = (old, new)
        bid_id = new_positions[startup_id][1].id if startup_id in new_positions else None
        if new is None:
            event, title = "dropped", f"Your startup dropped out of the top {rules.max_positions}"
        elif old is None:
            event, title = "ranked", f"Your startup is now ranked #{new}"
        elif new > old:
            event, title = "moved_down", f"You've been outbid: now ranked #{new} (was #{old})"
        else:
            event, title = "moved_up", f"Your startup moved up to #{new}"
        db.session.add(RankingEvent(startup_id=startup_id, bid_id=bid_id, event_type=event,
                                    old_position=old, new_position=new))
        if event in ("dropped", "moved_down"):
            notify_startup(startup_id, title, "Review available positions to regain your spot.",
                           "/dashboard/bids", "bid")
    return changes


def public_ranking():
    """{startup_id: position} for display. Never includes amounts."""
    rows = db.session.execute(select(RankingPosition.startup_id, RankingPosition.position)).all()
    return {startup_id: position for startup_id, position in rows}


def ranking_expiry(rules, now=None):
    return (now or utcnow()) + timedelta(days=rules.ranking_period_days)
