"""collections: learned descriptors for ad-hoc user lists

A row is created the first time the extraction model flags a record as an item
in a personal list that is not event/task/chore (movies to watch, books to
read, gift ideas). Keyed by the records.kind slug those items share; synonyms
and item_noun feed the plan/decide prompts so the list stays findable.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind_slug", sa.Text(), nullable=False),
        sa.Column("item_noun", sa.Text(), nullable=True),
        sa.Column("synonyms", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("field_hint", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("example_record_id", sa.BigInteger(),
                  sa.ForeignKey("records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_collections_kind_slug", "collections", ["kind_slug"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("ix_collections_kind_slug", table_name="collections")
    op.drop_table("collections")
