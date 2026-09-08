"""file index: nodes, chunks, edges, entity links

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 768


def upgrade() -> None:
    op.create_table(
        "file_nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("path_key", sa.Text(), nullable=False),
        sa.Column("parent_key", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("media_kind", sa.String(8), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_root", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_hash", sa.String(64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_nodes_path_key", "file_nodes", ["path_key"], unique=True)
    op.create_index("ix_file_nodes_parent_key", "file_nodes", ["parent_key"])
    op.create_index("ix_file_nodes_content_hash", "file_nodes", ["content_hash"])
    op.create_index("ix_file_nodes_status", "file_nodes", ["status"])
    op.create_index("ix_file_nodes_media_kind", "file_nodes", ["media_kind"])
    op.create_index("ix_file_nodes_registered_root", "file_nodes",
                    ["registered_root"],
                    postgresql_where=sa.text("registered_root"))

    op.create_table(
        "file_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('english', text)", persisted=True)),
    )
    op.create_index("ix_file_chunks_file_id_ord", "file_chunks",
                    ["file_id", "ord"], unique=True)
    op.execute("CREATE INDEX ix_file_chunks_tsv ON file_chunks USING gin (tsv)")

    op.create_table(
        "file_edges",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("src_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rel", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_edges_src_rel", "file_edges", ["src_id", "rel"])
    op.create_index("ix_file_edges_dst_rel", "file_edges", ["dst_id", "rel"])
    op.create_index("ix_file_edges_uniq", "file_edges",
                    ["src_id", "dst_id", "rel"], unique=True)

    op.create_table(
        "file_entity_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("etype", sa.String(8), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("mentions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(8), nullable=False, server_default="summary"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_entity_links_uniq", "file_entity_links",
                    ["file_id", "etype", "entity_id"], unique=True)
    op.create_index("ix_file_entity_links_entity", "file_entity_links",
                    ["etype", "entity_id"])

    op.execute(
        "CREATE INDEX ix_file_nodes_embedding ON file_nodes "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_file_chunks_embedding ON file_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("file_entity_links")
    op.drop_table("file_edges")
    op.drop_table("file_chunks")
    op.drop_table("file_nodes")
