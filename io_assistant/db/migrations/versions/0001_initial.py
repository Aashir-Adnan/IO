"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-07

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 768


def _timestamp_cols() -> tuple[sa.Column, ...]:
    # NOT NULL + server default — matches the ORM, which types these as
    # non-optional and never sets them from Python.
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def _entity_cols() -> tuple[sa.Column, ...]:
    return (
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        *_timestamp_cols(),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "utterances",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transcription_confidence", sa.Float(), nullable=True),
        sa.Column("resolved_intent", sa.String(16), nullable=True),
        sa.Column("marker", sa.String(32), nullable=True),
    )

    op.create_table(
        "people",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_entity_cols(),
    )

    op.create_table(
        "places",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        *_entity_cols(),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.Text()), nullable=False),
        *_entity_cols(),
    )

    op.create_table(
        "occasions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        *_entity_cols(),
    )

    op.create_table(
        "records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("domain", sa.String(24), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(12), nullable=True),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column(
            "assigned_by_person_id",
            sa.BigInteger(),
            sa.ForeignKey("people.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "source_utterance_id",
            sa.BigInteger(),
            sa.ForeignKey("utterances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        *_timestamp_cols(),
    )

    def _link(name: str, a: str, a_tbl: str, b: str, b_tbl: str) -> None:
        op.create_table(
            name,
            sa.Column(a, sa.BigInteger(), sa.ForeignKey(f"{a_tbl}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column(b, sa.BigInteger(), sa.ForeignKey(f"{b_tbl}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("role", sa.Text(), nullable=True),
        )

    _link("record_people", "record_id", "records", "person_id", "people")
    _link("record_places", "record_id", "records", "place_id", "places")
    _link("record_items", "record_id", "records", "item_id", "items")
    _link("record_occasions", "record_id", "records", "occasion_id", "occasions")
    _link("occasion_people", "occasion_id", "occasions", "person_id", "people")

    # b-tree: foreign keys
    op.create_index("ix_records_assigned_by_person_id", "records", ["assigned_by_person_id"])
    op.create_index("ix_records_source_utterance_id", "records", ["source_utterance_id"])
    op.create_index("ix_record_people_record_id", "record_people", ["record_id"])
    op.create_index("ix_record_people_person_id", "record_people", ["person_id"])
    op.create_index("ix_record_places_record_id", "record_places", ["record_id"])
    op.create_index("ix_record_places_place_id", "record_places", ["place_id"])
    op.create_index("ix_record_items_record_id", "record_items", ["record_id"])
    op.create_index("ix_record_items_item_id", "record_items", ["item_id"])
    op.create_index("ix_record_occasions_record_id", "record_occasions", ["record_id"])
    op.create_index("ix_record_occasions_occasion_id", "record_occasions", ["occasion_id"])
    op.create_index("ix_occasion_people_occasion_id", "occasion_people", ["occasion_id"])
    op.create_index("ix_occasion_people_person_id", "occasion_people", ["person_id"])

    # b-tree: timestamps / lookup columns
    op.create_index("ix_utterances_captured_at", "utterances", ["captured_at"])
    op.create_index("ix_records_occurred_at", "records", ["occurred_at"])
    op.create_index("ix_records_due_at", "records", ["due_at"])
    op.create_index("ix_records_kind", "records", ["kind"])
    op.create_index("ix_records_domain", "records", ["domain"])
    op.create_index("ix_occasions_date", "occasions", ["date"])

    # GIN: alias arrays
    op.create_index("ix_people_aliases", "people", ["aliases"], postgresql_using="gin")
    op.create_index("ix_places_aliases", "places", ["aliases"], postgresql_using="gin")
    op.create_index("ix_items_aliases", "items", ["aliases"], postgresql_using="gin")

    # HNSW: embeddings
    for tbl in ("people", "places", "items", "occasions", "records"):
        op.execute(
            f"CREATE INDEX ix_{tbl}_embedding ON {tbl} USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    for tbl in ("records", "occasions", "items", "places", "people"):
        op.execute(f"DROP INDEX IF EXISTS ix_{tbl}_embedding")

    op.drop_table("occasion_people")
    op.drop_table("record_occasions")
    op.drop_table("record_items")
    op.drop_table("record_places")
    op.drop_table("record_people")
    op.drop_table("records")
    op.drop_table("occasions")
    op.drop_table("items")
    op.drop_table("places")
    op.drop_table("people")
    op.drop_table("utterances")
