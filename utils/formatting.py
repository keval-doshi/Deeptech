from datetime import timedelta

from models.funding import format_inr_short

IST = timedelta(hours=5, minutes=30)


def inr(value):
    """Whole rupees with Indian digit grouping: 1234567 → ₹12,34,567."""
    if value is None:
        return "—"
    value = int(value)
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}"


def paise(value):
    return inr((value or 0) // 100)


def ist(dt, fmt="%d %b %Y, %H:%M"):
    """Format a naive-UTC timestamp in Indian Standard Time."""
    if dt is None:
        return "—"
    return (dt + IST).strftime(fmt)


def timeago(dt):
    from models.base import utcnow
    if dt is None:
        return ""
    seconds = int((utcnow() - dt).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


def register_filters(app):
    app.jinja_env.filters["inr"] = inr
    app.jinja_env.filters["paise"] = paise
    app.jinja_env.filters["ist"] = ist
    app.jinja_env.filters["timeago"] = timeago
    app.jinja_env.filters["inr_short"] = lambda v: format_inr_short(v) or "—"
