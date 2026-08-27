"""Initial migration - create all tables.

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create articles table
    op.create_table(
        'articles',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('title', sa.Text, nullable=False),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('source', sa.String(200), nullable=False),
        sa.Column('published', sa.DateTime(timezone=True), nullable=False),
        sa.Column('category', sa.String(50), nullable=False, server_default='general'),
        sa.Column('tickers', sa.JSON, nullable=False, server_default='[]'),
        sa.Column('summary', sa.Text, nullable=False, server_default=''),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_articles_published', 'articles', [sa.text('published DESC')])
    op.create_index('idx_articles_category', 'articles', ['category'])

    # Create upgrades_downgrades table
    op.create_table(
        'upgrades_downgrades',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('ticker', sa.String(10), nullable=False),
        sa.Column('firm', sa.String(200), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('old_rating', sa.String(100), server_default=''),
        sa.Column('new_rating', sa.String(100), server_default=''),
        sa.Column('price_target', sa.String(50), server_default=''),
        sa.Column('published', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_url', sa.Text, server_default=''),
        sa.Column('source', sa.String(200), server_default=''),
    )
    op.create_index('idx_ud_published', 'upgrades_downgrades', [sa.text('published DESC')])

    # Create custom_feeds table
    op.create_table(
        'custom_feeds',
        sa.Column('name', sa.String(200), primary_key=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('category', sa.String(50), nullable=False, server_default='general'),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('1')),
    )

    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('hashed_password', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True)),
    )

    # Create user_watchlists table
    op.create_table(
        'user_watchlists',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('ticker', sa.String(10), primary_key=True),
    )

    # Create user_settings table
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='America/New_York'),
        sa.Column('notification_prefs', sa.JSON, nullable=False, server_default='{}'),
    )

    # Create device_tokens table
    op.create_table(
        'device_tokens',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('token', sa.Text, unique=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table('device_tokens')
    op.drop_table('user_settings')
    op.drop_table('user_watchlists')
    op.drop_table('users')
    op.drop_table('custom_feeds')
    op.drop_table('upgrades_downgrades')
    op.drop_table('articles')
