"""proof documents on registration; no listing approval; paid rankings never expire

- startups.proof_document_path / proof_document_name: private proof-of-company upload
- listings no longer wait for admin approval: pending ones are published,
  rejected ones become drafts (an admin can publish them from the console)
- paid rankings are held until outbid: drop bids.expires_at and
  bidding_rules.ranking_period_days

Revision ID: c4e1d2a9b7f3
Revises: a7c3f5034973
Create Date: 2026-11-16 12:00:00.000000

"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e1d2a9b7f3'
down_revision = 'a7c3f5034973'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('startups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proof_document_path', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('proof_document_name', sa.String(length=120), nullable=True))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    startups = sa.table('startups', sa.column('status', sa.String), sa.column('published_at', sa.DateTime))
    op.execute(startups.update().where(startups.c.status == 'pending').where(startups.c.published_at.is_(None))
               .values(published_at=now))
    op.execute(startups.update().where(startups.c.status == 'pending').values(status='published'))
    op.execute(startups.update().where(startups.c.status == 'rejected').values(status='draft'))

    settings = sa.table('platform_settings', sa.column('key', sa.String))
    op.execute(settings.delete().where(settings.c.key == 'listings_require_approval'))

    with op.batch_alter_table('bids', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bids_expires_at'))
        batch_op.drop_column('expires_at')

    with op.batch_alter_table('bidding_rules', schema=None) as batch_op:
        batch_op.drop_column('ranking_period_days')


def downgrade():
    with op.batch_alter_table('bidding_rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ranking_period_days', sa.Integer(), nullable=False, server_default='30'))

    with op.batch_alter_table('bids', schema=None) as batch_op:
        batch_op.add_column(sa.Column('expires_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_bids_expires_at'), ['expires_at'], unique=False)

    with op.batch_alter_table('startups', schema=None) as batch_op:
        batch_op.drop_column('proof_document_name')
        batch_op.drop_column('proof_document_path')
