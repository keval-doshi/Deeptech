import logging
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
