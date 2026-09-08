"""cleanup: aliases default, drop redundant PK-leading indexes, add pg_trgm

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Indexes on the *first* column of a composite PK — redundant, the PK's own
# index already serves a leading-column prefix. The second-column indexes stay.
_REDUNDANT = {
    "ix_record_people_record_id": ("record_people", "record_id"),
    "ix_record_places_record_id": ("record_places", "record_id"),
    "ix_record_items_record_id": ("record_items", "record_id"),
    "ix_record_occasions_record_id": ("record_occasions", "record_id"),
    "ix_occasion_people_occasion_id": ("occasion_people", "occasion_id"),
}

# GIN trigram indexes on the entity name columns — the resolver uses
# similarity() to narrow candidates in SQL instead of scanning the table.
_TRGM = [
    ("ix_people_canonical_name_trgm", "people", "canonical_name"),
    ("ix_places_name_trgm", "places", "name"),
    ("ix_items_name_trgm", "items", "name"),
]


def upgrade() -> None:
    for tbl in ("people", "places", "items"):
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN aliases SET DEFAULT '{{}}'")

    for name in _REDUNDANT:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, tbl, col in _TRGM:
        op.execute(
            f"CREATE INDEX {name} ON {tbl} USING gin ({col} gin_trgm_ops)"
        )


def downgrade() -> None:
    for name, tbl, _col in _TRGM:
        op.execute(f"DROP INDEX IF EXISTS {name}")

    for name, (tbl, col) in _REDUNDANT.items():
        op.execute(f"CREATE INDEX {name} ON {tbl} ({col})")

    for tbl in ("people", "places", "items"):
        op.execute(f"ALTER TABLE {tbl} ALTER COLUMN aliases DROP DEFAULT")
