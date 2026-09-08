"""media: file_nodes.thumb_path + file_captions

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("file_nodes", sa.Column("thumb_path", sa.Text(), nullable=True))
    op.create_table(
        "file_captions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_captions_file_id_created_at", "file_captions",
                    ["file_id", "created_at"])


def downgrade() -> None:
    op.drop_table("file_captions")
    op.drop_column("file_nodes", "thumb_path")
