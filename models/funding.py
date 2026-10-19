from extensions import db
from models.base import utcnow

FUNDING_STAGES = ("Pre-Seed", "Seed", "Pre-Series A", "Series A", "Series B", "Series C+", "Grant")


def format_inr_short(rupees):
    """₹ amounts in Indian short units (Lakh / Crore)."""
    if not rupees:
        return None
    if rupees >= 1_00_00_000:
        value = rupees / 1_00_00_000
        return f"₹{value:,.0f} Cr" if value >= 100 else f"₹{value:,.1f} Cr".replace(".0 Cr", " Cr")
    if rupees >= 1_00_000:
        value = rupees / 1_00_000
        return f"₹{value:,.1f} L".replace(".0 L", " L")
    return f"₹{rupees:,}"


class FundingProfile(db.Model):
    __tablename__ = "funding_profiles"
    __table_args__ = (
        db.CheckConstraint("total_raised_inr >= 0", name="raised_non_negative"),
        db.CheckConstraint("raising_target_inr >= 0", name="target_non_negative"),
    )

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"),
                           nullable=False, unique=True)
    is_raising = db.Column(db.Boolean, nullable=False, default=False, index=True)
    stage = db.Column(db.String(30))
    total_raised_inr = db.Column(db.BigInteger, nullable=False, default=0)
    raising_target_inr = db.Column(db.BigInteger, nullable=False, default=0)
    min_ticket_inr = db.Column(db.BigInteger, nullable=False, default=0)
    use_of_funds = db.Column(db.String(600), nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    startup = db.relationship("Startup", back_populates="funding")

    def to_public(self):
        return {
            "is_raising": self.is_raising,
            "stage": self.stage,
            "total_raised": format_inr_short(self.total_raised_inr),
            "raising_target": format_inr_short(self.raising_target_inr),
            "min_ticket": format_inr_short(self.min_ticket_inr),
            "use_of_funds": self.use_of_funds,
        }
