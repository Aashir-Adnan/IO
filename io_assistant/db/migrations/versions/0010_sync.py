"""memory sync: global row ids, dirty tracking, tombstones, aliases, state

Every synced table gets a global `sync_id` (uuid) and `synced_at` (when the row
was last pushed/applied; NULL = never). Tables that lacked `updated_at` gain it
so a row edited after `synced_at` is detectable. Link tables (affiliations) get
only `synced_at`. `sync_tombstones` records deletes/merges, `sync_aliases` maps a
merged-away `sync_id` to its survivor, `sync_state` keeps per-device counters.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYNCED = ["utterances", "people", "places", "items", "occasions",
          "conversations", "collections", "records", "messages"]
NEEDS_UPDATED_AT = ["utterances", "conversations", "messages"]
LINKS = ["record_people", "record_places", "record_items",
         "record_occasions", "occasion_people"]


def upgrade() -> None:
    for t in SYNCED:
        op.add_column(t, sa.Column(
            "sync_id", UUID(as_uuid=False), nullable=False,
            server_default=sa.text("gen_random_uuid()")))
        op.create_index(f"uq_{t}_sync_id", t, ["sync_id"], unique=True)
        op.add_column(t, sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    for t in NEEDS_UPDATED_AT:
        op.add_column(t, sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()")))
    for t in LINKS:
        op.add_column(t, sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "sync_tombstones",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("sync_id", UUID(as_uuid=False), nullable=False),
        sa.Column("merged_into", UUID(as_uuid=False), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("table_name", "sync_id", name="uq_sync_tombstones"),
    )
    op.create_table(
        "sync_aliases",
        sa.Column("alias", UUID(as_uuid=False), primary_key=True),
        sa.Column("canonical", UUID(as_uuid=False), nullable=False),
    )
    op.create_table(
        "sync_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
    op.drop_table("sync_aliases")
    op.drop_table("sync_tombstones")
    for t in LINKS:
        op.drop_column(t, "synced_at")
    for t in NEEDS_UPDATED_AT:
        op.drop_column(t, "updated_at")
    for t in SYNCED:
        op.drop_column(t, "synced_at")
        op.drop_index(f"uq_{t}_sync_id", table_name=t)
        op.drop_column(t, "sync_id")
