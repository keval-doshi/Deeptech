"""Public startup discovery pages plus the startup REST API."""
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError

from extensions import db, limiter
from models import (Category, Founder, FundingProfile, GalleryImage, InvestorProfile, PlatformSetting,
                    Product, RankingEvent, RankingPosition, SavedStartup, Startup, StartupMember, StartupUpdate,
                    StartupView, utcnow)
from models.funding import FUNDING_STAGES
from models.startup import STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED, TEAM_SIZES
from models.user import ROLE_ADMIN, ROLE_STARTUP_OWNER
from services import bidding_service, ranking_service
from services.audit_service import audit
from services.notification_service import notify_admins
from utils.security import get_managed_startup_or_404, json_error, roles_required
from utils.uploads import UploadError, delete_image, save_image
from utils.validation import ValidationError, Validator, like_escape, slugify, year_bounds

bp = Blueprint("startups", __name__)

SORTS = ("promoted", "trending", "recent", "funded", "name")
TABS = ("trending", "recent", "funded", "picks")
MAX_PER_PAGE = 24


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _saved_ids():
    if not current_user.is_authenticated:
        return set()
    return set(db.session.scalars(select(SavedStartup.startup_id).where(SavedStartup.user_id == current_user.id)))


def _trending_subquery(days=14):
    since = date.today() - timedelta(days=days)
    return (
        select(StartupView.startup_id, func.sum(StartupView.views).label("recent_views"))
        .where(StartupView.day >= since)
        .group_by(StartupView.startup_id)
        .subquery()
    )


def search_startups(args, force_category=None, force_raising=False):
    """Shared search used by the homepage, directory, category and funding pages."""
    query = (select(Startup).join(Category, Category.id == Startup.category_id)
             .where(Startup.status == STATUS_PUBLISHED))

    term = (args.get("q") or "").strip()[:80]
    if term:
        pattern = f"%{like_escape(term)}%"
        founder_match = select(Founder.startup_id).where(Founder.name.ilike(pattern, escape="\\"))
        query = query.where(or_(
            Startup.name.ilike(pattern, escape="\\"),
            Startup.tagline.ilike(pattern, escape="\\"),
            Startup.tags.ilike(pattern, escape="\\"),
            Startup.city.ilike(pattern, escape="\\"),
            Category.name.ilike(pattern, escape="\\"),
            Startup.id.in_(founder_match),
        ))

    category = force_category or (args.get("category") or "").strip()
    if category and category != "all":
        slugs = [c for c in category.split(",") if c][:10]
        query = query.where(Category.slug.in_(slugs))

    location = (args.get("location") or "").strip()[:80]
    if location and location != "all":
        query = query.where(Startup.city.ilike(like_escape(location), escape="\\"))

    funding = force_raising and "raising" or (args.get("funding") or "").strip()
    stage = (args.get("stage") or "").strip()
    if funding in ("raising", "not_raising") or stage:
        query = query.outerjoin(FundingProfile, FundingProfile.startup_id == Startup.id)
        if funding == "raising":
            query = query.where(FundingProfile.is_raising.is_(True))
        elif funding == "not_raising":
            query = query.where(or_(FundingProfile.is_raising.is_(False), FundingProfile.id.is_(None)))
        if stage in FUNDING_STAGES:
            query = query.where(FundingProfile.stage == stage)

    if args.get("verified") == "1":
        query = query.where(Startup.is_verified.is_(True))

    tab = args.get("tab") if args.get("tab") in TABS else None
    sort = args.get("sort") if args.get("sort") in SORTS else "promoted"
    if tab == "picks":
        query = query.where(Startup.investor_pick.is_(True))
    elif tab == "recent":
        sort = "recent"
    elif tab == "funded":
        sort = "funded"

    trending = _trending_subquery()
    query = query.outerjoin(trending, trending.c.startup_id == Startup.id)
    trending_order = func.coalesce(trending.c.recent_views, 0).desc()
    orders = []
    if sort == "promoted":
        query = query.outerjoin(RankingPosition, RankingPosition.startup_id == Startup.id)
        orders = [case((RankingPosition.position.is_(None), 1), else_=0), RankingPosition.position, trending_order]
    elif sort == "trending":
        orders = [trending_order]
    elif sort == "recent":
        orders = [Startup.published_at.desc()]
    elif sort == "funded":
        funded = select(FundingProfile.total_raised_inr).where(
            FundingProfile.startup_id == Startup.id).scalar_subquery()
        orders = [func.coalesce(funded, 0).desc()]
    elif sort == "name":
        orders = [Startup.name.asc()]
    query = query.order_by(*orders, Startup.id.desc())

    try:
        page = max(int(args.get("page", 1)), 1)
        per_page = min(max(int(args.get("per_page", 6)), 1), MAX_PER_PAGE)
    except (TypeError, ValueError):
        page, per_page = 1, 6
    total = db.session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = db.session.scalars(query.limit(per_page).offset((page - 1) * per_page)).all()

    ranking = ranking_service.public_ranking()
    saved = _saved_ids()
    return {
        "items": [s.to_card(rank=ranking.get(s.id), saved=s.id in saved) for s in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max((total + per_page - 1) // per_page, 1),
        "sort": sort,
    }


def _site_stats():
    published = db.session.scalar(select(func.count(Startup.id)).where(Startup.status == STATUS_PUBLISHED))
    raising = db.session.scalar(
        select(func.count(FundingProfile.id)).join(Startup, Startup.id == FundingProfile.startup_id)
        .where(Startup.status == STATUS_PUBLISHED, FundingProfile.is_raising.is_(True)))
    investors = db.session.scalar(select(func.count(InvestorProfile.id)))
    categories = db.session.scalar(select(func.count(Category.id)))
    return {"startups": published, "raising": raising, "investors": investors, "categories": categories}


def _locations():
    return db.session.scalars(
        select(Startup.city).where(Startup.status == STATUS_PUBLISHED).distinct().order_by(Startup.city)
    ).all()


def _record_view(startup):
    if current_user.is_authenticated and current_user.can_manage(startup):
        return
    key = f"v{startup.id}:{date.today().isoformat()}"
    seen = session.get("views", [])
    if key in seen:
        return
    session["views"] = (seen + [key])[-50:]
    today = date.today()
    row = db.session.scalars(select(StartupView).where(StartupView.startup_id == startup.id,
                                                       StartupView.day == today)).first()
    if row is None:
        db.session.add(StartupView(startup_id=startup.id, day=today, views=1))
    else:
        row.views = StartupView.views + 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def _visible_startup_or_404(slug):
    startup = db.session.scalars(select(Startup).where(Startup.slug == slug)).first()
    if startup is None:
        abort(404)
    if not startup.is_public:
        allowed = current_user.is_authenticated and (current_user.is_admin or current_user.can_manage(startup))
        if not allowed:
            abort(404)
    return startup


def _unique_slug(name):
    base = slugify(name)
    slug, n = base, 2
    while db.session.scalars(select(Startup.id).where(Startup.slug == slug)).first():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _startup_validator(form, partial=False):
    low, high = year_bounds()
    category_ids = {str(c) for c in db.session.scalars(select(Category.id))}
    v = Validator(form)
    fields = {
        "name": lambda: v.text("name", "Startup name", min_len=2, max_len=120),
        "tagline": lambda: v.text("tagline", "Tagline", min_len=10, max_len=160),
        "description": lambda: v.text("description", "Description", min_len=80, max_len=5000, multiline=True),
        "category_id": lambda: v.choice("category_id", "Category", category_ids),
        "tags": lambda: v.text("tags", "Focus areas", required=False, max_len=255),
        "city": lambda: v.text("city", "City", min_len=2, max_len=80),
        "state": lambda: v.text("state", "State", required=False, max_len=80),
        "founded_year": lambda: v.integer("founded_year", "Founded year", required=True, min_value=low, max_value=high),
        "team_size": lambda: v.choice("team_size", "Team size", TEAM_SIZES),
        "website": lambda: v.url("website", "Website"),
        "contact_email": lambda: v.email("contact_email", "Contact email"),
        "address": lambda: v.text("address", "Address", required=False, max_len=255),
    }
    for field, rule in fields.items():
        if not partial or field in form:
            rule()
    return v


def _apply_images(startup, files):
    """Save logo/cover uploads. On failure, removes files saved by this call and
    raises UploadError with `.field` set to the offending input."""
    saved, replaced = [], []
    for field, kind, attr in (("logo", "logo", "logo_path"), ("cover", "cover", "cover_path")):
        upload = files.get(field)
        if upload and upload.filename:
            try:
                new_path = save_image(upload, f"startups/{startup.id}", kind)
            except UploadError as exc:
                for path in saved:
                    delete_image(path)
                exc.field = field
                raise
            saved.append(new_path)
            replaced.append(getattr(startup, attr))
            setattr(startup, attr, new_path)
    for old in replaced:
        delete_image(old)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def _todays_ranking(limit=5):
    """Current paid positions for the sidebar. Positions only, never amounts."""
    return db.session.execute(
        select(RankingPosition.position, Startup)
        .join(Startup, Startup.id == RankingPosition.startup_id)
        .order_by(RankingPosition.position).limit(limit)
    ).all()


def _latest_activity(limit=6):
    """Public activity feed: rank claims/climbs and new listings. No amounts."""
    items, seen = [], set()
    events = db.session.execute(
        select(RankingEvent, Startup).join(Startup, Startup.id == RankingEvent.startup_id)
        .where(RankingEvent.event_type.in_(("payment_confirmed", "ranked", "moved_up")),
               RankingEvent.new_position.is_not(None), Startup.status == STATUS_PUBLISHED)
        .order_by(RankingEvent.created_at.desc()).limit(limit * 4)
    ).all()
    for event, startup in events:
        key = (startup.id, event.new_position)
        if key in seen:
            continue
        seen.add(key)
        verb = "moved up to" if event.event_type == "moved_up" else "claimed"
        items.append({"startup": startup, "text": f"{verb} #{event.new_position}", "at": event.created_at,
                      "icon": "crown"})
    for startup in db.session.scalars(
            select(Startup).where(Startup.status == STATUS_PUBLISHED, Startup.published_at.is_not(None))
            .order_by(Startup.published_at.desc()).limit(limit)):
        items.append({"startup": startup, "text": "joined DeeptechIndia", "at": startup.published_at,
                      "icon": "sparkles"})
    items.sort(key=lambda item: item["at"], reverse=True)
    return items[:limit]


@bp.route("/")
def index():
    bidding_service.ensure_rankings_fresh()
    return render_template("index.html", stats=_site_stats(), locations=_locations(), stages=FUNDING_STAGES,
                           todays_ranking=_todays_ranking(), activity=_latest_activity())


@bp.route("/startups")
def directory():
    """The directory now lives on the homepage; keep old links working."""
    return redirect(url_for("startups.index", **request.args, _anchor="startups"), code=301)


@bp.route("/startups/<slug>")
def profile(slug):
    startup = _visible_startup_or_404(slug)
    _record_view(startup)
    ranking = ranking_service.public_ranking()
    similar = db.session.scalars(
        select(Startup).where(Startup.category_id == startup.category_id, Startup.id != startup.id,
                              Startup.status == STATUS_PUBLISHED).order_by(Startup.is_verified.desc()).limit(4)
    ).all()
    saved = startup.id in _saved_ids()
    intro_status = None
    if current_user.is_authenticated and current_user.is_investor and current_user.investor_profile:
        from models import IntroductionRequest
        intro = db.session.scalars(select(IntroductionRequest).where(
            IntroductionRequest.investor_id == current_user.investor_profile.id,
            IntroductionRequest.startup_id == startup.id)).first()
        intro_status = intro.status if intro else None
    return render_template("startup_profile.html", startup=startup, rank=ranking.get(startup.id),
                           similar=similar, saved=saved, intro_status=intro_status,
                           can_manage=current_user.is_authenticated and current_user.can_manage(startup))


@bp.route("/credits")
def credits():
    """Attribution for the demo photography (required by CC BY / BY-SA licences)."""
    import json
    import os
    from flask import current_app
    path = os.path.join(current_app.static_folder, "images", "photos", "CREDITS.json")
    items = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return render_template("credits.html", items=sorted(items.items()))


@bp.route("/startup/new")
@login_required
@roles_required(ROLE_STARTUP_OWNER, ROLE_ADMIN)
def new_startup():
    existing = current_user.primary_startup
    categories = db.session.scalars(select(Category).order_by(Category.sort_order)).all()
    return render_template("list_startup.html", categories=categories, team_sizes=TEAM_SIZES,
                           stages=FUNDING_STAGES, existing=existing)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@bp.get("/api/startups")
@limiter.limit("120 per minute")
def api_list():
    return jsonify({"ok": True, **search_startups(request.args)})


@bp.get("/api/stats")
def api_stats():
    return jsonify({"ok": True, "stats": _site_stats()})


@bp.get("/api/startups/<slug>")
def api_detail(slug):
    startup = _visible_startup_or_404(slug)
    rank = ranking_service.public_ranking().get(startup.id)
    return jsonify({"ok": True, "startup": startup.to_profile(rank=rank, saved=startup.id in _saved_ids())})


@bp.post("/api/startups")
@login_required
@roles_required(ROLE_STARTUP_OWNER)
@limiter.limit("5 per hour")
def api_create():
    if current_user.primary_startup is not None:
        return json_error("Your account already manages a startup. Edit it from your dashboard.", 409)
    v = _startup_validator(request.form)
    v.boolean("is_raising")
    if request.form.get("is_raising") in ("true", "on", "1"):
        v.choice("stage", "Funding stage", FUNDING_STAGES)
        v.integer("raising_target_inr", "Raise target", min_value=0, max_value=10**12)
    v.integer("total_raised_inr", "Total raised", min_value=0, max_value=10**12)
    if not request.form.get("confirm_accuracy"):
        v.errors["confirm_accuracy"] = "Please confirm the information is accurate."
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)

    needs_review = PlatformSetting.get_bool("listings_require_approval")
    startup = Startup(
        slug=_unique_slug(data["name"]), name=data["name"], tagline=data["tagline"],
        description=data["description"], category_id=int(data["category_id"]), tags=data["tags"] or "",
        city=data["city"], state=data.get("state") or "", founded_year=data["founded_year"],
        team_size=data["team_size"], website=data.get("website"), contact_email=data["contact_email"],
        address=data.get("address"), created_by_id=current_user.id,
        status=STATUS_PENDING if needs_review else STATUS_PUBLISHED,
        published_at=None if needs_review else utcnow(),
    )
    db.session.add(startup)
    db.session.flush()
    try:
        _apply_images(startup, request.files)
    except UploadError as exc:
        db.session.rollback()
        return json_error(str(exc), 400, errors={getattr(exc, "field", "logo"): str(exc)})
    db.session.add(StartupMember(startup_id=startup.id, user_id=current_user.id, role="owner"))
    db.session.add(FundingProfile(
        startup_id=startup.id, is_raising=data["is_raising"], stage=data.get("stage"),
        total_raised_inr=data.get("total_raised_inr") or 0,
        raising_target_inr=data.get("raising_target_inr") or 0,
    ))
    audit("startup.created", "startup", startup.id, actor=current_user, status=startup.status)
    if needs_review:
        notify_admins("New startup awaiting review", startup.name, "/admin#approvals", "review")
    db.session.commit()
    return jsonify({"ok": True, "id": startup.id, "slug": startup.slug, "status": startup.status,
                    "redirect": url_for("dashboard.overview")}), 201


@bp.put("/api/startups/<int:startup_id>")
@login_required
@limiter.limit("60 per hour")
def api_update(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    form = request.form if request.form or request.files else (request.get_json(silent=True) or {})
    v = _startup_validator(form, partial=True)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    for field, value in data.items():
        if field == "category_id":
            value = int(value)
        setattr(startup, field, value)
    try:
        _apply_images(startup, request.files)
    except UploadError as exc:
        db.session.rollback()
        return json_error(str(exc), 400, errors={getattr(exc, "field", "logo"): str(exc)})
    resubmitted = False
    if startup.status == STATUS_REJECTED and not current_user.is_admin:
        # Editing a rejected listing sends it back to the review queue.
        startup.status = STATUS_PENDING
        startup.rejection_reason = None
        resubmitted = True
        notify_admins("Listing resubmitted for review", startup.name, "/admin#approvals", "review")
    audit("startup.updated", "startup", startup.id, actor=current_user, fields=sorted(data), resubmitted=resubmitted)
    db.session.commit()
    return jsonify({"ok": True, "startup": startup.to_profile(), "resubmitted": resubmitted})


@bp.put("/api/startups/<int:startup_id>/funding")
@login_required
def api_update_funding(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    payload = request.get_json(silent=True) or {}
    v = Validator(payload).boolean("is_raising")
    v.choice("stage", "Funding stage", FUNDING_STAGES, required=bool(payload.get("is_raising")))
    for field, label in (("total_raised_inr", "Total raised"), ("raising_target_inr", "Raise target"),
                         ("min_ticket_inr", "Minimum ticket")):
        v.integer(field, label, min_value=0, max_value=10**12)
    v.text("use_of_funds", "Use of funds", required=False, max_len=600, multiline=True)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    funding = startup.funding or FundingProfile(startup_id=startup.id)
    funding.is_raising = data["is_raising"]
    funding.stage = data.get("stage")
    funding.total_raised_inr = data.get("total_raised_inr") or 0
    funding.raising_target_inr = data.get("raising_target_inr") or 0
    funding.min_ticket_inr = data.get("min_ticket_inr") or 0
    funding.use_of_funds = data.get("use_of_funds") or ""
    db.session.add(funding)
    audit("startup.funding_updated", "startup", startup.id, actor=current_user, is_raising=funding.is_raising)
    db.session.commit()
    return jsonify({"ok": True, "funding": funding.to_public()})


@bp.post("/api/startups/<int:startup_id>/save")
@login_required
@limiter.limit("60 per minute")
def api_toggle_save(startup_id):
    startup = db.session.get(Startup, startup_id)
    if startup is None or not startup.is_public:
        return json_error("Startup not found.", 404)
    existing = db.session.scalars(select(SavedStartup).where(
        SavedStartup.user_id == current_user.id, SavedStartup.startup_id == startup.id)).first()
    if existing:
        db.session.delete(existing)
        saved = False
    else:
        db.session.add(SavedStartup(user_id=current_user.id, startup_id=startup.id))
        saved = True
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        saved = True
    return jsonify({"ok": True, "saved": saved})


# ---- Founders / products / gallery / updates ------------------------------

def _owned_child(model, startup, child_id):
    child = db.session.get(model, child_id)
    if child is None or child.startup_id != startup.id:
        abort(404)
    return child


@bp.post("/api/startups/<int:startup_id>/founders")
@login_required
def api_add_founder(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    v = Validator(request.form)
    v.text("name", "Name", min_len=2, max_len=120).text("title", "Role", min_len=2, max_len=120)
    v.text("bio", "Bio", required=False, max_len=500, multiline=True).url("linkedin_url", "LinkedIn", linkedin=True)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    if len(startup.founders) >= 12:
        return json_error("You can list up to 12 founders and leaders.", 400)
    founder = Founder(startup_id=startup.id, name=data["name"], title=data["title"], bio=data.get("bio") or "",
                      linkedin_url=data.get("linkedin_url"), sort_order=len(startup.founders))
    try:
        if request.files.get("photo") and request.files["photo"].filename:
            founder.photo_path = save_image(request.files["photo"], f"startups/{startup.id}", "photo")
    except UploadError as exc:
        return json_error(str(exc), 400, errors={"photo": str(exc)})
    db.session.add(founder)
    db.session.commit()
    return jsonify({"ok": True, "founder": founder.to_dict()}), 201


@bp.delete("/api/startups/<int:startup_id>/founders/<int:founder_id>")
@login_required
def api_delete_founder(startup_id, founder_id):
    startup = get_managed_startup_or_404(startup_id)
    founder = _owned_child(Founder, startup, founder_id)
    delete_image(founder.photo_path)
    db.session.delete(founder)
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/api/startups/<int:startup_id>/products")
@login_required
def api_add_product(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    v = Validator(request.form)
    v.text("name", "Product name", min_len=2, max_len=120).text("summary", "Summary", required=False, max_len=400)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    if len(startup.products) >= 12:
        return json_error("You can list up to 12 products.", 400)
    product = Product(startup_id=startup.id, name=data["name"], summary=data.get("summary") or "",
                      sort_order=len(startup.products))
    try:
        if request.files.get("image") and request.files["image"].filename:
            product.image_path = save_image(request.files["image"], f"startups/{startup.id}", "image")
    except UploadError as exc:
        return json_error(str(exc), 400, errors={"image": str(exc)})
    db.session.add(product)
    db.session.commit()
    return jsonify({"ok": True, "product": product.to_dict()}), 201


@bp.delete("/api/startups/<int:startup_id>/products/<int:product_id>")
@login_required
def api_delete_product(startup_id, product_id):
    startup = get_managed_startup_or_404(startup_id)
    product = _owned_child(Product, startup, product_id)
    delete_image(product.image_path)
    db.session.delete(product)
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/api/startups/<int:startup_id>/gallery")
@login_required
@limiter.limit("40 per hour")
def api_add_gallery(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    if len(startup.gallery) >= 20:
        return json_error("The gallery holds up to 20 images.", 400)
    caption = (request.form.get("caption") or "").strip()[:160]
    try:
        path = save_image(request.files.get("image"), f"startups/{startup.id}", "image")
    except UploadError as exc:
        return json_error(str(exc), 400, errors={"image": str(exc)})
    image = GalleryImage(startup_id=startup.id, image_path=path, caption=caption, sort_order=len(startup.gallery))
    db.session.add(image)
    db.session.commit()
    return jsonify({"ok": True, "image": image.to_dict()}), 201


@bp.delete("/api/startups/<int:startup_id>/gallery/<int:image_id>")
@login_required
def api_delete_gallery(startup_id, image_id):
    startup = get_managed_startup_or_404(startup_id)
    image = _owned_child(GalleryImage, startup, image_id)
    delete_image(image.image_path)
    db.session.delete(image)
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/api/startups/<int:startup_id>/updates")
@login_required
@limiter.limit("20 per hour")
def api_add_update(startup_id):
    startup = get_managed_startup_or_404(startup_id)
    v = Validator(request.get_json(silent=True) or {})
    v.text("title", "Title", min_len=4, max_len=160).text("body", "Update", min_len=10, max_len=3000, multiline=True)
    try:
        data = v.check()
    except ValidationError as exc:
        return json_error("Please fix the highlighted fields.", 400, errors=exc.errors)
    update = StartupUpdate(startup_id=startup.id, title=data["title"], body=data["body"])
    db.session.add(update)
    db.session.commit()
    return jsonify({"ok": True, "update": update.to_dict()}), 201


@bp.delete("/api/startups/<int:startup_id>/updates/<int:update_id>")
@login_required
def api_delete_update(startup_id, update_id):
    startup = get_managed_startup_or_404(startup_id)
    db.session.delete(_owned_child(StartupUpdate, startup, update_id))
    db.session.commit()
    return jsonify({"ok": True})
