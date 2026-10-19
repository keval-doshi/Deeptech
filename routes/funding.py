from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, select

from extensions import db, limiter
from models import FundingProfile, Startup
from models.funding import FUNDING_STAGES, format_inr_short
from models.startup import STATUS_PUBLISHED
from routes.startups import _locations, search_startups

bp = Blueprint("funding", __name__)


def funding_summary():
    raising = (select(FundingProfile).join(Startup, Startup.id == FundingProfile.startup_id)
               .where(Startup.status == STATUS_PUBLISHED, FundingProfile.is_raising.is_(True)))
    sub = raising.subquery()
    count = db.session.scalar(select(func.count()).select_from(sub))
    target = db.session.scalar(select(func.coalesce(func.sum(sub.c.raising_target_inr), 0)))
    by_stage = dict(db.session.execute(
        select(sub.c.stage, func.count()).group_by(sub.c.stage)).all())
    return {
        "raising_count": count,
        "total_target": format_inr_short(target) or "₹0",
        "by_stage": [{"stage": s, "count": by_stage.get(s, 0)} for s in FUNDING_STAGES],
    }


@bp.route("/funding")
def index():
    return render_template("funding.html", summary=funding_summary(), stages=FUNDING_STAGES,
                           locations=_locations())


@bp.get("/api/funding")
@limiter.limit("120 per minute")
def api_list():
    result = search_startups(request.args, force_raising=True)
    # Enrich cards with the public funding ask (never bid data).
    ids = [item["id"] for item in result["items"]]
    profiles = {f.startup_id: f for f in db.session.scalars(
        select(FundingProfile).where(FundingProfile.startup_id.in_(ids)))}
    for item in result["items"]:
        profile = profiles.get(item["id"])
        item["funding"] = profile.to_public() if profile else None
    return jsonify({"ok": True, "summary": funding_summary(), **result})
