"""Flask CLI commands: seeding, admin creation and scheduled maintenance.

    flask --app app seed               # SAMPLE data for development
    flask --app app create-admin       # interactive
    flask --app app bids maintain      # run from cron every 5 minutes
    flask --app app payments reconcile # run from cron every 10 minutes
"""
import getpass
from datetime import timedelta

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import select

from extensions import db
from models import Payment, User, utcnow
from models.payment import PAY_CREATED
from models.user import ROLE_ADMIN

bids_cli = AppGroup("bids", help="Bidding maintenance.")
payments_cli = AppGroup("payments", help="Payment maintenance.")


@bids_cli.command("maintain")
def bids_maintain():
    """Expire abandoned checkouts and lapsed rankings, then rebuild positions."""
    from services import bidding_service, ranking_service
    rules = ranking_service.get_rules(lock=True)
    expired = bidding_service.expire_stale_checkouts()
    changes = ranking_service.recompute_rankings(rules)
    db.session.commit()
    click.echo(f"Expired {len(expired)} checkouts; {len(changes)} ranking changes.")


@payments_cli.command("reconcile")
@click.option("--older-than", default=5, help="Minutes since the order was created.")
def payments_reconcile(older_than):
    """Ask the provider about orders whose webhook never arrived."""
    from services import payment_service
    cutoff = utcnow() - timedelta(minutes=older_than)
    pending = db.session.scalars(
        select(Payment).where(Payment.status == PAY_CREATED, Payment.created_at <= cutoff)
    ).all()
    for payment in pending:
        status = payment_service.reconcile(payment)
        click.echo(f"{payment.receipt}: {status}")
    click.echo(f"Checked {len(pending)} payments.")


def register_commands(app):
    app.cli.add_command(bids_cli)
    app.cli.add_command(payments_cli)

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Drop and recreate all tables first (DESTROYS DATA).")
    def seed(reset):
        """Load clearly-labelled SAMPLE data for local development."""
        if current_app.config["ENV_NAME"] == "production":
            raise click.ClickException("Refusing to seed sample data in production.")
        from seed import seed_database
        if reset:
            db.drop_all()
        db.create_all()
        summary = seed_database()
        click.echo(summary)

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True, default="Platform Admin")
    def create_admin(email, name):
        """Create (or promote) an administrator account."""
        password = getpass.getpass("Password (min 10 chars): ")
        if len(password) < 10:
            raise click.ClickException("Password too short.")
        user = db.session.scalars(select(User).where(User.email == email.lower())).first()
        if user is None:
            user = User(email=email.lower(), name=name)
            db.session.add(user)
        user.role = ROLE_ADMIN
        user.email_verified_at = user.email_verified_at or utcnow()
        user.set_password(password)
        db.session.commit()
        click.echo(f"Admin ready: {user.email}")
