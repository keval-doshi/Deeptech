"""Legal and contact pages, plus the endpoints search engines and uptime monitors read."""
from flask import Blueprint, Response, current_app, jsonify, render_template, url_for
from sqlalchemy import select, text

from extensions import db, limiter
from models import Startup
from models.startup import STATUS_PUBLISHED
from services import ranking_service

bp = Blueprint("pages", __name__)

# Paths that are private, per-user or pointless in search results.
ROBOTS_DISALLOW = ("/admin", "/api/", "/dashboard", "/payments", "/profile", "/settings", "/startup/new",
                   "/login", "/register", "/logout", "/forgot-password", "/reset-password", "/verify-email",
                   "/resend-verification", "/invite/")


def _legal_context():
    cfg = current_app.config
    return {
        "entity": cfg["LEGAL_ENTITY_NAME"] or "[Company legal name]",
        "address": cfg["LEGAL_ADDRESS"] or "[Registered office address]",
        "jurisdiction": cfg["LEGAL_JURISDICTION"] or "[City, State]",
        "grievance_name": cfg["GRIEVANCE_OFFICER_NAME"] or "[Grievance Officer name]",
        "grievance_email": cfg["GRIEVANCE_OFFICER_EMAIL"] or cfg["SUPPORT_EMAIL"],
        "reviewed": cfg["LEGAL_REVIEWED"],
        "version": cfg["LEGAL_VERSION"],
    }


def _absolute(path):
    return current_app.config["SITE_URL"].rstrip("/") + path


@bp.route("/terms")
def terms():
    return render_template("legal/terms.html", **_legal_context())


@bp.route("/privacy")
def privacy():
    return render_template("legal/privacy.html", **_legal_context())


@bp.route("/refunds")
def refunds():
    return render_template("legal/refunds.html", **_legal_context())


@bp.route("/promoted-listing-terms")
def promoted_terms():
    return render_template("legal/promoted.html", rules=ranking_service.get_rules(), **_legal_context())


@bp.route("/contact")
def contact():
    return render_template("contact.html", **_legal_context())


@bp.route("/health")
@limiter.exempt
def health():
    """For uptime monitors and Docker: 200 only when the database answers."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Health check failed")
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")


@bp.route("/robots.txt")
@limiter.exempt
def robots():
    lines = ["User-agent: *", *(f"Disallow: {path}" for path in ROBOTS_DISALLOW),
             "", f"Sitemap: {_absolute(url_for('pages.sitemap'))}", ""]
    return Response("\n".join(lines), mimetype="text/plain")


@bp.route("/sitemap.xml")
@limiter.exempt
def sitemap():
    static_pages = [url_for("startups.index"), url_for("funding.index"), url_for("investors.workspace"),
                    url_for("pages.contact"), url_for("pages.terms"), url_for("pages.privacy"),
                    url_for("pages.refunds"), url_for("pages.promoted_terms")]
    entries = [(_absolute(path), None) for path in static_pages]
    published = db.session.execute(select(Startup.slug, Startup.updated_at)
                                   .where(Startup.status == STATUS_PUBLISHED).order_by(Startup.slug))
    for slug, updated in published:
        entries.append((_absolute(url_for("startups.profile", slug=slug)), updated))
    response = Response(render_template("sitemap.xml", entries=entries), mimetype="application/xml")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response
