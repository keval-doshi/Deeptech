from flask import Blueprint, abort, jsonify, redirect, url_for
from sqlalchemy import func, select

from extensions import db
from models import Category, Startup
from models.startup import STATUS_PUBLISHED

bp = Blueprint("categories", __name__)


def categories_with_counts():
    counts = dict(db.session.execute(
        select(Startup.category_id, func.count(Startup.id))
        .where(Startup.status == STATUS_PUBLISHED).group_by(Startup.category_id)
    ).all())
    categories = db.session.scalars(select(Category).order_by(Category.sort_order, Category.name)).all()
    return [(c, counts.get(c.id, 0)) for c in categories]


@bp.route("/categories")
def index():
    """Categories are filters on the homepage list now; keep old links working."""
    return redirect(url_for("startups.index", _anchor="startups"), code=301)


@bp.route("/categories/<slug>")
def detail(slug):
    if not db.session.scalars(select(Category.id).where(Category.slug == slug)).first():
        abort(404)
    return redirect(url_for("startups.index", category=slug, _anchor="startups"), code=301)


@bp.get("/api/categories")
def api_list():
    return jsonify({"ok": True, "items": [c.to_dict(count) for c, count in categories_with_counts()]})
