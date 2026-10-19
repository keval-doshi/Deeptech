import json

from extensions import db
from models.base import utcnow


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False, default="info")
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(500), nullable=False, default="")
    link = db.Column(db.String(255))
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "link": self.link,
            "read": self.read_at is not None,
            "created_at": self.created_at.isoformat(),
        }


class AuditLog(db.Model):
    """Append-only record of financial and administrative actions."""
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(40))
    data = db.Column(db.Text, nullable=False, default="{}")
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    actor = db.relationship("User")

    @property
    def data_dict(self):
        try:
            return json.loads(self.data or "{}")
        except ValueError:
            return {}


class PlatformSetting(db.Model):
    """Simple key/value store for site-wide switches editable by admins."""
    __tablename__ = "platform_settings"

    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    DEFAULTS = {
        "listings_require_approval": "true",
        "allow_new_registrations": "true",
    }

    @classmethod
    def get(cls, key):
        row = db.session.get(cls, key)
        return row.value if row else cls.DEFAULTS.get(key)

    @classmethod
    def get_bool(cls, key):
        return (cls.get(key) or "").lower() == "true"

    @classmethod
    def set(cls, key, value):
        row = db.session.get(cls, key)
        if row is None:
            row = cls(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
        return row
