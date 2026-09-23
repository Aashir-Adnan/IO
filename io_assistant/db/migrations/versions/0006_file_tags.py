"""file_tags: tokenized salient terms per file, for fast fuzzy media lookup

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_tags",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),          # display surface
        sa.Column("norm", sa.Text(), nullable=False),          # lowercased, for matching
        sa.Column("kind", sa.String(12), nullable=False),      # person|place|self|thing|event|topic
        sa.Column("media_kind", sa.String(8), nullable=True),  # denorm from the file
        sa.Column("entity_etype", sa.String(8), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(8), nullable=False, server_default="caption"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_tags_uniq", "file_tags",
                    ["file_id", "norm", "kind"], unique=True)
    op.create_index("ix_file_tags_norm", "file_tags", ["norm"])
    op.create_index("ix_file_tags_media_norm", "file_tags", ["media_kind", "norm"])
    op.execute(
        "CREATE INDEX ix_file_tags_norm_trgm ON file_tags "
        "USING gin (norm gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_file_tags_norm_trgm", table_name="file_tags")
    op.drop_index("ix_file_tags_media_norm", table_name="file_tags")
    op.drop_index("ix_file_tags_norm", table_name="file_tags")
    op.drop_index("ix_file_tags_uniq", table_name="file_tags")
    op.drop_table("file_tags")
