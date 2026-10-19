from functools import wraps

from flask import abort, jsonify, request
from flask_login import current_user

from extensions import db
from models import Startup


def wants_json():
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def json_error(message, status=400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def roles_required(*roles):
    """Server-side role check. Unauthenticated users go through Flask-Login."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                from extensions import login_manager
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def get_managed_startup_or_404(startup_id):
    """Load a startup the current user is authorised to manage.

    Returns 404 (not 403) for startups the user cannot manage so that
    private IDs cannot be probed.
    """
    startup = db.session.get(Startup, startup_id)
    if startup is None or not current_user.is_authenticated:
        abort(404)
    if not (current_user.can_manage(startup) or current_user.is_admin):
        abort(404)
    return startup


def require_owned_startup(owner=False):
    """The startup a dashboard user manages, or 404 if they have none.

    With owner=True, editors get 403: bids, payments and team management are
    reserved for the startup's owners.
    """
    membership = current_user.primary_membership if current_user.is_authenticated else None
    if membership is None:
        abort(404)
    if owner and membership.role != "owner":
        abort(403)
    return membership.startup


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://checkout.razorpay.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "frame-src https://api.razorpay.com https://checkout.razorpay.com; "
        "connect-src 'self' https://lumberjack.razorpay.com; "
        "form-action 'self'; base-uri 'self'; frame-ancestors 'none'"
    ),
}


def apply_security_headers(response, https=False):
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
