"""Private bidding: rules, bids, the materialised public ranking and its event log.

All money is stored as integer paise to avoid floating point errors.
"""
from extensions import db
from models.base import TimestampMixin, utcnow

BID_PENDING = "pending_payment"
BID_ACTIVE = "active"
BID_SUPERSEDED = "superseded"
BID_EXPIRED = "expired"
BID_CANCELLED = "cancelled"
BID_FAILED = "failed"
BID_STATUSES = (BID_PENDING, BID_ACTIVE, BID_SUPERSEDED, BID_EXPIRED, BID_CANCELLED, BID_FAILED)


class BiddingRules(db.Model):
    """Singleton row (id=1) holding admin-configurable bidding rules.

    The row is also locked (SELECT ... FOR UPDATE) to serialise every
    operation that can change the ranking order.
    """
    __tablename__ = "bidding_rules"
    __table_args__ = (
        db.CheckConstraint("opening_bid_paise > 0", name="opening_positive"),
        db.CheckConstraint("increment_paise > 0", name="increment_positive"),
        db.CheckConstraint("max_positions BETWEEN 1 AND 50", name="positions_range"),
    )

    id = db.Column(db.Integer, primary_key=True)
    opening_bid_paise = db.Column(db.BigInteger, nullable=False, default=10_000)   # ₹100
    increment_paise = db.Column(db.BigInteger, nullable=False, default=10_000)     # ₹100
    max_bid_paise = db.Column(db.BigInteger, nullable=False, default=10_00_000_00)  # ₹10,00,000 safety cap
    max_positions = db.Column(db.Integer, nullable=False, default=10)
    ranking_period_days = db.Column(db.Integer, nullable=False, default=30)
    checkout_ttl_minutes = db.Column(db.Integer, nullable=False, default=20)
    bidding_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "opening_bid": self.opening_bid_paise // 100,
            "increment": self.increment_paise // 100,
            "max_bid": self.max_bid_paise // 100,
            "max_positions": self.max_positions,
            "ranking_period_days": self.ranking_period_days,
            "checkout_ttl_minutes": self.checkout_ttl_minutes,
            "bidding_enabled": self.bidding_enabled,
        }


class Bid(TimestampMixin, db.Model):
    __tablename__ = "bids"
    __table_args__ = (
        db.CheckConstraint(f"status IN {BID_STATUSES}", name="status_valid"),
        db.CheckConstraint("amount_paise > 0", name="amount_positive"),
        db.CheckConstraint("target_position >= 1", name="position_positive"),
        db.UniqueConstraint("startup_id", "idempotency_key", name="uq_bids_startup_idempotency"),
        # At most one open checkout per startup (partial unique index).
        db.Index("uq_bids_one_pending_per_startup", "startup_id", unique=True,
                 postgresql_where=db.text("status = 'pending_payment'"),
                 sqlite_where=db.text("status = 'pending_payment'")),
        db.Index("ix_bids_status_amount", "status", "amount_paise"),
    )

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    target_position = db.Column(db.Integer, nullable=False)
    amount_paise = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=BID_PENDING)
    idempotency_key = db.Column(db.String(64), nullable=False)
    achieved_position = db.Column(db.Integer)
    checkout_expires_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime, index=True)
    expires_at = db.Column(db.DateTime, index=True)  # end of the paid ranking period

    startup = db.relationship("Startup")
    user = db.relationship("User")
    payments = db.relationship("Payment", back_populates="bid", order_by="Payment.created_at")

    @property
    def amount_rupees(self):
        return self.amount_paise // 100

    @property
    def latest_payment(self):
        return self.payments[-1] if self.payments else None


class RankingPosition(db.Model):
    """Materialised public ranking. Contains no amounts on purpose."""
    __tablename__ = "ranking_positions"

    position = db.Column(db.Integer, primary_key=True, autoincrement=False)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, unique=True)
    bid_id = db.Column(db.Integer, db.ForeignKey("bids.id", ondelete="CASCADE"), nullable=False, unique=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    startup = db.relationship("Startup")
    bid = db.relationship("Bid")


class RankingEvent(db.Model):
    """Append-only log of everything that touched a startup's paid ranking."""
    __tablename__ = "ranking_events"

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_id = db.Column(db.Integer, db.ForeignKey("bids.id", ondelete="SET NULL"))
    event_type = db.Column(db.String(30), nullable=False)
    old_position = db.Column(db.Integer)
    new_position = db.Column(db.Integer)
    detail = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
