from extensions import db
from models.base import utcnow


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.String(400), nullable=False, default="")
    image_path = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    startup = db.relationship("Startup", back_populates="products")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "image_url": f"/static/{self.image_path}" if self.image_path else None,
        }


class GalleryImage(db.Model):
    __tablename__ = "gallery_images"

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    image_path = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.String(160), nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    startup = db.relationship("Startup", back_populates="gallery")

    def to_dict(self):
        return {"id": self.id, "url": f"/static/{self.image_path}", "caption": self.caption}
