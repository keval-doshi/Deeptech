"""Payment transactions and provider webhook events.

Only provider references and statuses are stored. Card or bank details never
touch this application: checkout is hosted by the payment provider.
"""
from extensions import db
from models.base import TimestampMixin, utcnow

PAY_CREATED = "created"
PAY_PAID = "paid"
PAY_FAILED = "failed"
PAY_CANCELLED = "cancelled"
PAY_EXPIRED = "expired"
PAYMENT_STATUSES = (PAY_CREATED, PAY_PAID, PAY_FAILED, PAY_CANCELLED, PAY_EXPIRED)


class Payment(TimestampMixin, db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        db.CheckConstraint(f"status IN {PAYMENT_STATUSES}", name="status_valid"),
        db.CheckConstraint("amount_paise > 0", name="amount_positive"),
        db.UniqueConstraint("provider", "provider_order_id", name="uq_payments_provider_order"),
        db.UniqueConstraint("provider", "provider_payment_id", name="uq_payments_provider_payment"),
    )

    id = db.Column(db.Integer, primary_key=True)
    bid_id = db.Column(db.Integer, db.ForeignKey("bids.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider = db.Column(db.String(20), nullable=False)
    provider_order_id = db.Column(db.String(64), nullable=False)
    provider_payment_id = db.Column(db.String(64))
    receipt = db.Column(db.String(40), nullable=False, unique=True)
    amount_paise = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="INR")
    status = db.Column(db.String(20), nullable=False, default=PAY_CREATED, index=True)
    method = db.Column(db.String(30))
    failure_reason = db.Column(db.String(255))
    paid_at = db.Column(db.DateTime)

    bid = db.relationship("Bid", back_populates="payments")
    startup = db.relationship("Startup")

    def to_dict(self):
        return {
            "id": self.id,
            "receipt": self.receipt,
            "provider": self.provider,
            "order_id": self.provider_order_id,
            "payment_id": self.provider_payment_id,
            "amount": self.amount_paise // 100,
            "currency": self.currency,
            "status": self.status,
            "method": self.method,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat(),
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "bid_id": self.bid_id,
            "target_position": self.bid.target_position,
        }


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"
    __table_args__ = (
        db.UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event"),
    )

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False)
    event_id = db.Column(db.String(100), nullable=False)
    event_type = db.Column(db.String(60), nullable=False)
    signature_valid = db.Column(db.Boolean, nullable=False, default=False)
    payload = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="received")  # received/processed/ignored/error
    error = db.Column(db.String(255))
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    processed_at = db.Column(db.DateTime)
