"""web_cache + trackers: opt-in web-backed answers (three tiers)

web_cache  - a templated Tier-A answer or a synthesised Tier-C answer, keyed by
             normalised query + kind, valid until expires_at.
trackers   - Tier B: a labelled web source polled on an interval; each poll
             writes a `reading` record, so "petrol today vs yesterday" is a
             plain query over IO's own memory.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "web_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("query_norm", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),     # news|fact|instant
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tier", sa.String(1), nullable=False),     # a|c
        sa.Column("fetched_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_web_cache_uniq", "web_cache",
                    ["query_norm", "kind"], unique=True)
    op.create_index("ix_web_cache_expires_at", "web_cache", ["expires_at"])

    op.create_table(
        "trackers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("norm", sa.Text(), nullable=False),        # matcher key
        sa.Column("domain", sa.String(24), nullable=True),   # record domain for readings
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("extractor", JSONB(), nullable=False),     # {type: css|json|regex, selector, unit}
        sa.Column("interval_min", sa.Integer(), nullable=False, server_default="720"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_value", sa.Text(), nullable=True),
        sa.Column("last_unit", sa.String(16), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_trackers_norm", "trackers", ["norm"], unique=True)
    op.create_index("ix_trackers_enabled", "trackers", ["enabled"],
                    postgresql_where=sa.text("enabled"))


def downgrade() -> None:
    op.drop_index("ix_trackers_enabled", table_name="trackers")
    op.drop_index("ix_trackers_norm", table_name="trackers")
    op.drop_table("trackers")
    op.drop_index("ix_web_cache_expires_at", table_name="web_cache")
    op.drop_index("ix_web_cache_uniq", table_name="web_cache")
    op.drop_table("web_cache")
