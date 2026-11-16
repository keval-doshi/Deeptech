import html
import logging
import re
import smtplib
from email.message import EmailMessage

from flask import current_app

from extensions import db
from models import Notification, StartupMember, User

log = logging.getLogger(__name__)


def notify(user_id, title, body="", link=None, kind="info"):
    """Queue an in-app notification (caller commits)."""
    note = Notification(user_id=user_id, title=title[:160], body=body[:500], link=link, kind=kind)
    db.session.add(note)
    return note


def notify_startup(startup_id, title, body="", link=None, kind="info"):
    member_ids = db.session.scalars(
        db.select(StartupMember.user_id).where(StartupMember.startup_id == startup_id)
    ).all()
    for user_id in member_ids:
        notify(user_id, title, body, link, kind)


def notify_admins(title, body="", link=None, kind="alert"):
    admin_ids = db.session.scalars(db.select(User.id).where(User.role == "admin", User.active.is_(True))).all()
    for user_id in admin_ids:
        notify(user_id, title, body, link, kind)


def _email_html(subject, body):
    """HTML version of a plain-text email: escaped paragraphs with clickable links."""
    def paragraph(text):
        escaped = html.escape(text.strip()).replace("\n", "<br>")
        linked = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" style="color:#b4470b">\1</a>', escaped)
        return f'<p style="margin:0 0 16px;line-height:1.6;overflow-wrap:anywhere">{linked}</p>'

    paragraphs = "".join(paragraph(p) for p in re.split(r"\n\s*\n", body) if p.strip())
    return (
        '<!doctype html><html lang="en-IN"><body style="margin:0;padding:24px 12px;background:#f4f4f2">'
        '<div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #e6e6e3;border-radius:12px;'
        'padding:28px 24px;font:16px/1.6 Arial,Helvetica,sans-serif;color:#1c1c1c">'
        '<p style="margin:0 0 20px;font-weight:700;font-size:18px;color:#0b0b0b">DeeptechIndia.in</p>'
        f'<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;color:#0b0b0b">{html.escape(subject)}</h1>'
        f"{paragraphs}</div></body></html>"
    )


def send_email(to, subject, body):
    """Send a plain-text email via SMTP, or log it when SMTP is not configured.

    Returns True when the message was handed to an SMTP server.
    """
    cfg = current_app.config
    if not cfg.get("MAIL_SERVER"):
        log.warning("Email (SMTP not configured) to=%s subject=%s\n%s", to, subject, body)
        return False
    message = EmailMessage()
    message["From"] = cfg["MAIL_DEFAULT_SENDER"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(_email_html(subject, body), subtype="html")
    try:
        with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as smtp:
            if cfg.get("MAIL_USE_TLS"):
                smtp.starttls()
            if cfg.get("MAIL_USERNAME"):
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("Failed to send email to %s", to)
        return False
