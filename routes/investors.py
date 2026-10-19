"""Investor directory, investor workspace and introduction requests."""
from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter
from models import Category, InvestorProfile, IntroductionRequest, SavedStartup, Startup, utcnow
from models.investor import INVESTOR_TYPES
from models.startup import STATUS_PUBLISHED
from models.user import ROLE_INVESTOR
from services import ranking_service
from services.audit_service import audit
from services.notification_service import notify, notify_startup
from utils.security import json_error, roles_required
from utils.validation import ValidationError, Validator, like_escape

bp = Blueprint("investors", __name__)


@bp.route("/investors")
def workspace():
    categories = db.session.scalars(select(Category).order_by(Category.sort_order)).all()
    profile = None
    if current_user.is_authenticated and current_user.is_investor:
        profile = current_user.investor_profile
    return render_template("investors.html", profile=profile, categories=categories,
                           investor_types=INVESTOR_TYPES)


@bp.get("/api/investors")
@limiter.limit("60 per minute")
def api_list():
    query = select(InvestorProfile)
    term = (request.args.get("q") or "").strip()[:80]
    if term:
        pattern = f"%{like_escape(term)}%"
        query = query.where(or_(InvestorProfile.firm_name.ilike(pattern, escape="\\"),
                                InvestorProfile.thesis.ilike(pattern, escape="\\"),
                                InvestorProfile.city.ilike(pattern, escape="\\")))
    investor_type = request.args.get("type")
    if investor_type in INVESTOR_TYPES:
        query = query.where(InvestorProfile.investor_type == investor_type)
    category = request.args.get("category")
    if category:
        query = query.where(InvestorProfile.categories.any(Category.slug == category))
    items = db.session.scalars(query.order_by(InvestorProfile.is_verified.desc(),
                                              InvestorProfile.firm_name).limit(60)).all()
    return jsonify({"ok": True, "items": [i.to_public() for i in items]})


@bp.get("/api/investors/me")
@login_required
@roles_required(ROLE_INVESTOR)
def api_me():
    profile = current_user.investor_profile
    saved = db.session.scalars(
        select(SavedStartup).join(Startup, Startup.id == SavedStartup.startup_id)
        .where(SavedStartup.user_id == current_user.id, Startup.status == STATUS_PUBLISHED)
        .order_by(SavedStartup.created_at.desc())).all()
    intros = db.session.scalars(
        select(IntroductionRequest).where(IntroductionRequest.investor_id == profile.id)
        .order_by(IntroductionRequest.created_at.desc())).all()
    category_ids = [c.id for c in profile.categories]
    recommended_query = select(Startup).where(Startup.status == STATUS_PUBLISHED)
    if category_ids:
        recommended_query = recommended_query.where(Startup.category_id.in_(category_ids))
    recommended = db.session.scalars(
        recommended_query.order_by(Startup.is_verified.desc(), Startup.published_at.desc()).limit(6)).all()
    ranking = ranking_service.public_ranking()
    saved_ids = {s.startup_id for s in saved}
    return jsonify({
        "ok": True,
        "profile": {**profile.to_public(), "category_ids": category_ids,
                    "check_min_inr": profile.check_min_inr, "check_max_inr": profile.check_max_inr},
        "saved": [s.startup.to_card(rank=ranking.get(s.startup_id), saved=True) for s in saved],
        "introductions": [i.to_dict() for i in intros],
        "recommended": [s.to_card(rank=ranking.get(s.id), saved=s.id in saved_ids) for s in recommended],
    })


@bp.put("/api/investors/me")
@login_required
@roles_required(ROLE_INVESTOR)
def api_update_me():
    profile = current_user.investor_profile
    payload = request.get_json(silent=True) or {}
    v = Validator(payload)
    v.text("firm_name", "Firm name", min_len=2, max_len=120)
    v.choice("investor_type", "Investor type", INVESTOR_TYPES)
    v.text("thesis", "Investment thesis", required=False, max_len=600, multiline=True)
    v.url("website", "Website").text("city", "City", required=False, max_len=80)
    v.integer("check_min_inr", "Minimum cheque", min_value=0, max_value=10**12)
    v.integer("check_max_inr", "Maximum cheque", min_value=0, max_value=10**12)
    v.text("stages", "Stages", required=False, max_len=120)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    for field in ("firm_name", "investor_type", "thesis", "website", "city", "stages"):
        setattr(profile, field, data.get(field) or ("" if field in ("thesis", "city", "stages") else None))
    profile.check_min_inr = data.get("check_min_inr") or 0
    profile.check_max_inr = data.get("check_max_inr") or 0
    raw_ids = payload.get("category_ids") or []
    ids = [int(i) for i in raw_ids if str(i).isdigit()][:20]
    profile.categories = db.session.scalars(select(Category).where(Category.id.in_(ids))).all() if ids else []
    db.session.commit()
    return jsonify({"ok": True, "profile": profile.to_public()})


@bp.post("/api/introduction-requests")
@login_required
@roles_required(ROLE_INVESTOR)
@limiter.limit("20 per hour")
def api_create_intro():
    if not current_user.is_verified:
        return json_error("Verify your email before requesting introductions.", 403)
    payload = request.get_json(silent=True) or {}
    v = Validator(payload).text("message", "Message", min_len=20, max_len=1000, multiline=True)
    v.integer("startup_id", "Startup", required=True, min_value=1)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    startup = db.session.get(Startup, data["startup_id"])
    if startup is None or not startup.is_public:
        return json_error("Startup not found.", 404)
    intro = IntroductionRequest(investor_id=current_user.investor_profile.id, startup_id=startup.id,
                                message=data["message"])
    db.session.add(intro)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return json_error("You've already requested an introduction to this startup.", 409)
    notify_startup(startup.id, "New introduction request",
                   f"{current_user.investor_profile.firm_name} would like to connect.", "/dashboard#introductions",
                   "intro")
    audit("intro.requested", "introduction_request", intro.id, actor=current_user, startup_id=startup.id)
    db.session.commit()
    return jsonify({"ok": True, "introduction": intro.to_dict()}), 201


@bp.put("/api/introduction-requests/<int:intro_id>")
@login_required
def api_respond_intro(intro_id):
    intro = db.session.get(IntroductionRequest, intro_id)
    if intro is None or not current_user.can_manage(intro.startup):
        abort(404)
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("accepted", "declined"):
        return json_error("Choose accept or decline.", 400)
    if intro.status != "pending":
        return json_error("This request has already been answered.", 409)
    intro.status = status
    intro.responded_at = utcnow()
    notify(intro.investor.user_id, f"{intro.startup.name} {status} your introduction request",
           "Contact details are now visible in your workspace." if status == "accepted" else "",
           "/investors", "intro")
    audit(f"intro.{status}", "introduction_request", intro.id, actor=current_user)
    db.session.commit()
    return jsonify({"ok": True, "introduction": intro.to_dict(for_startup=True)})
