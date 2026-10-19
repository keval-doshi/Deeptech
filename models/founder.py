from extensions import db


class Founder(db.Model):
    __tablename__ = "founders"

    id = db.Column(db.Integer, primary_key=True)
    startup_id = db.Column(db.Integer, db.ForeignKey("startups.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    bio = db.Column(db.String(500), nullable=False, default="")
    linkedin_url = db.Column(db.String(255))
    photo_path = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    startup = db.relationship("Startup", back_populates="founders")

    @property
    def initials(self):
        return "".join(p[0] for p in self.name.split()[:2]).upper()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "bio": self.bio,
            "linkedin_url": self.linkedin_url,
            "photo_url": f"/static/{self.photo_path}" if self.photo_path else None,
            "initials": self.initials,
        }
