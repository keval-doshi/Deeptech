from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.base import TimestampMixin, utcnow

ROLE_STARTUP_OWNER = "startup_owner"
ROLE_INVESTOR = "investor"
ROLE_ADMIN = "admin"
ROLES = (ROLE_STARTUP_OWNER, ROLE_INVESTOR, ROLE_ADMIN)
PUBLIC_SIGNUP_ROLES = (ROLE_STARTUP_OWNER, ROLE_INVESTOR)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint(f"role IN {ROLES}", name="role_valid"),
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_STARTUP_OWNER)
    email_verified_at = db.Column(db.DateTime)
    active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime)
    # Bumped on password change so outstanding reset links stop working.
    password_changed_at = db.Column(db.DateTime, default=utcnow)

    memberships = db.relationship("StartupMember", back_populates="user", cascade="all, delete-orphan")
    investor_profile = db.relationship("InvestorProfile", back_populates="user", uselist=False)

    def set_password(self, password):
        # Werkzeug defaults to scrypt with a random salt.
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return bool(self.active)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_investor(self):
        return self.role == ROLE_INVESTOR

    @property
    def is_startup_owner(self):
        return self.role == ROLE_STARTUP_OWNER

    @property
    def is_verified(self):
        return self.email_verified_at is not None

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "U"

    @property
    def primary_membership(self):
        for membership in self.memberships:
            return membership
        return None

    @property
    def primary_startup(self):
        membership = self.primary_membership
        return membership.startup if membership else None

    @property
    def is_startup_owner_member(self):
        """True when the user is an *owner* (not just an editor) of their startup."""
        membership = self.primary_membership
        return bool(membership and membership.role == "owner")

    def can_manage(self, startup):
        if startup is None:
            return False
        return any(m.startup_id == startup.id for m in self.memberships)

    def __repr__(self):
        return f"<User {self.email}>"
