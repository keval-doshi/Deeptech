import os

from extensions import db
from models.base import TimestampMixin, utcnow

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
STARTUP_STATUSES = (STATUS_DRAFT, STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

TEAM_SIZES = ("1-10", "11-50", "51-200", "201-500", "500+")


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, unique=True)
    slug = db.Column(db.String(60), nullable=False, unique=True, index=True)
    icon = db.Column(db.String(40), nullable=False, default="grid")
    color = db.Column(db.String(9), nullable=False, default="#5b3df5")
    description = db.Column(db.String(300), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    startups = db.relationship("Startup", back_populates="category", lazy="dynamic")

    def photo_url(self, n=1):
        """Category photo n (falls back to the generated illustration)."""
        rel = f"images/photos/{self.slug}/{n:02d}.jpg"
        if os.path.exists(os.path.join(STATIC_DIR, rel)):
            return f"/static/{rel}"
        return f"/static/images/covers/{self.slug}{'' if n == 1 else f'-{min(n, 3)}'}.svg"

    @property
    def cover_url(self):
        return self.photo_url(1)

    def to_dict(self, count=None):
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "icon": self.icon,
            "color": self.color,
            "description": self.description,
        }
        if count is not None:
            data["startup_count"] = count
        return data


class Startup(TimestampMixin, db.Model):
    __tablename__ = "startups"
    __table_args__ = (
        db.CheckConstraint(f"status IN {STARTUP_STATUSES}", name="status_valid"),
        db.Index("ix_startups_status_category", "status", "category_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(90), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    tagline = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    tags = db.Column(db.String(255), nullable=False, default="")
    city = db.Column(db.String(80), nullable=False, index=True)
    state = db.Column(db.String(80), nullable=False, default="")
    founded_year = db.Column(db.Integer)
    team_size = db.Column(db.String(20))
    website = db.Column(db.String(255))
    contact_email = db.Column(db.String(255))
    address = db.Column(db.String(255))
    logo_path = db.Column(db.String(255))
    cover_path = db.Column(db.String(255))
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    rejection_reason = db.Column(db.String(300))
    published_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    # Editorial flag used for the "Investors' Picks" tab.
    investor_pick = db.Column(db.Boolean, nullable=False, default=False)

    category = db.relationship("Category", back_populates="startups")
    members = db.relationship("StartupMember", back_populates="startup", cascade="all, delete-orphan")
    founders = db.relationship("Founder", back_populates="startup", cascade="all, delete-orphan",
                               order_by="Founder.sort_order")
    products = db.relationship("Product", back_populates="startup", cascade="all, delete-orphan",
                               order_by="Product.sort_order")
    gallery = db.relationship("GalleryImage", back_populates="startup", cascade="all, delete-orphan",
                              order_by="GalleryImage.sort_order")
    updates = db.relationship("StartupUpdate", back_populates="startup", cascade="all, delete-orphan",
                              order_by="StartupUpdate.created_at.desc()")
    funding = db.relationship("FundingProfile", back_populates="startup", uselist=False,
                              cascade="all, delete-orphan")

    @property
    def is_public(self):
        return self.status == STATUS_PUBLISHED

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    @property
    def location(self):
        return ", ".join(p for p in (self.city, self.state or "India") if p)

    @property
    def initials(self):
        words = [w for w in self.name.split() if w[:1].isalnum()]
        return "".join(w[0] for w in words[:2]).upper() or "S"

    @property
    def logo_url(self):
        return f"/static/{self.logo_path}" if self.logo_path else None

    @property
    def cover_url(self):
        if self.cover_path:
            return f"/static/{self.cover_path}"
        return self.category.cover_url

    def to_card(self, rank=None, saved=False):
        """Public, list-safe representation. Never includes bid data."""
        funding = self.funding
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "tagline": self.tagline,
            "category": {"name": self.category.name, "slug": self.category.slug,
                         "icon": self.category.icon, "color": self.category.color},
            "tags": self.tag_list[:3],
            "location": self.location,
            "city": self.city,
            "is_verified": self.is_verified,
            "logo_url": self.logo_url,
            "cover_url": self.cover_url,
            "initials": self.initials,
            "looking_for_funds": bool(funding and funding.is_raising),
            "funding_stage": funding.stage if funding else None,
            "promoted_rank": rank,
            "saved": saved,
            "url": f"/startups/{self.slug}",
        }

    def to_profile(self, rank=None, saved=False):
        data = self.to_card(rank=rank, saved=saved)
        funding = self.funding
        data.update({
            "description": self.description,
            "founded_year": self.founded_year,
            "team_size": self.team_size,
            "website": self.website,
            "contact_email": self.contact_email,
            "address": self.address,
            "tags": self.tag_list,
            "founders": [f.to_dict() for f in self.founders],
            "products": [p.to_dict() for p in self.products],
            "gallery": [g.to_dict() for g in self.gallery],
            "updates": [u.to_dict() for u in self.updates],
            "funding": funding.to_public() if funding else None,
        })
        return data


class StartupMember(db.Model):
    """Links users to the startups they are authorised to manage."""
    __tablename__ = "startup_members"
    __table_args__ = (
        db.UniqueConstraint("startup_id", "user_id", name="uq_startup_members_startup_user"),
        db.CheckConstraint("role IN ('owner', 'editor')", name="role_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="owner")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    startup = db.relationship("Startup", back_populates="members")
    user = db.relationship("User", back_populates="memberships")


class StartupUpdate(db.Model):
    __tablename__ = "startup_updates"

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    startup = db.relationship("Startup", back_populates="updates")

    def to_dict(self):
        return {"id": self.id, "title": self.title, "body": self.body,
                "created_at": self.created_at.isoformat()}


class SavedStartup(db.Model):
    __tablename__ = "saved_startups"
    __table_args__ = (
        db.UniqueConstraint("user_id", "startup_id", name="uq_saved_startups_user_startup"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    startup = db.relationship("Startup")


class StartupView(db.Model):
    """Daily profile-view counter used for owner analytics."""
    __tablename__ = "startup_views"
    __table_args__ = (
        db.UniqueConstraint("startup_id", "day", name="uq_startup_views_startup_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    day = db.Column(db.Date, nullable=False)
    views = db.Column(db.Integer, nullable=False, default=0)


INVITE_ROLES = ("owner", "editor")


class StartupInvite(db.Model):
    """Email invitation to join a startup's team. Only a hash of the token is stored."""
    __tablename__ = "startup_invites"
    __table_args__ = (
        db.CheckConstraint("role IN ('owner', 'editor')", name="role_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="editor")
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)

    startup = db.relationship("Startup")
    invited_by = db.relationship("User")

    @property
    def is_open(self):
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > utcnow()

    def to_dict(self):
        return {"id": self.id, "email": self.email, "role": self.role, "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat(), "open": self.is_open}
