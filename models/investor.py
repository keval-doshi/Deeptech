from extensions import db
from models.base import TimestampMixin, utcnow
from models.funding import format_inr_short

INVESTOR_TYPES = ("VC", "Angel", "Angel Network", "Corporate VC", "Family Office", "Accelerator", "Government")
INTRO_STATUSES = ("pending", "accepted", "declined")

investor_categories = db.Table(
    "investor_categories",
    db.Column("investor_id", db.Integer, db.ForeignKey("investor_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)


class InvestorProfile(TimestampMixin, db.Model):
    __tablename__ = "investor_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    firm_name = db.Column(db.String(120), nullable=False)
    investor_type = db.Column(db.String(30), nullable=False, default="VC")
    thesis = db.Column(db.String(600), nullable=False, default="")
    website = db.Column(db.String(255))
    city = db.Column(db.String(80), nullable=False, default="")
    check_min_inr = db.Column(db.BigInteger, nullable=False, default=0)
    check_max_inr = db.Column(db.BigInteger, nullable=False, default=0)
    stages = db.Column(db.String(120), nullable=False, default="")
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    logo_path = db.Column(db.String(255))

    user = db.relationship("User", back_populates="investor_profile")
    categories = db.relationship("Category", secondary=investor_categories, lazy="selectin")

    @property
    def initials(self):
        return "".join(p[0] for p in self.firm_name.split()[:2]).upper()

    def to_public(self):
        """Directory listing. Contact details stay private until an intro is accepted."""
        cheque = None
        if self.check_min_inr or self.check_max_inr:
            cheque = f"{format_inr_short(self.check_min_inr) or '₹0'} – {format_inr_short(self.check_max_inr) or 'open'}"
        return {
            "id": self.id,
            "firm_name": self.firm_name,
            "investor_type": self.investor_type,
            "thesis": self.thesis,
            "city": self.city,
            "website": self.website,
            "cheque_size": cheque,
            "stages": [s.strip() for s in self.stages.split(",") if s.strip()],
            "categories": [c.name for c in self.categories],
            "is_verified": self.is_verified,
            "initials": self.initials,
            "logo_url": self.logo_url,
        }

    @property
    def logo_url(self):
        return f"/static/{self.logo_path}" if self.logo_path else None


class IntroductionRequest(db.Model):
    __tablename__ = "introduction_requests"
    __table_args__ = (
        db.UniqueConstraint("investor_id", "startup_id", name="uq_introduction_requests_investor_startup"),
        db.CheckConstraint(f"status IN {INTRO_STATUSES}", name="status_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.Integer, db.ForeignKey("investor_profiles.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    message = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    responded_at = db.Column(db.DateTime)

    investor = db.relationship("InvestorProfile")
    startup = db.relationship("Startup")

    def to_dict(self, for_startup=False):
        data = {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at.isoformat(),
            "startup": {"name": self.startup.name, "slug": self.startup.slug},
            "investor": {"firm_name": self.investor.firm_name, "type": self.investor.investor_type},
        }
        # The investor's email is revealed to the startup only once accepted,
        # and the startup's email to the investor likewise.
        if self.status == "accepted":
            if for_startup:
                data["investor"]["email"] = self.investor.user.email
            else:
                data["startup"]["email"] = self.startup.contact_email
        return data
