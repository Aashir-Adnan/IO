from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .base import Base

EMBED_DIM = 768  # keep in sync with config.embedding_dim; migration owns the DDL


class Utterance(Base):
    __tablename__ = "utterances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # voice|text
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transcription_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolved_intent: Mapped[str | None] = mapped_column(String(16), nullable=True)
    marker: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Person(Base):
    __tablename__ = "people"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Occasion(Base):
    __tablename__ = "occasions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(24), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(12), nullable=True)  # open|done|dropped
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recurrence_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_by_person_id: Mapped[int | None] = mapped_column(
        ForeignKey("people.id", ondelete="SET NULL"), nullable=True
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_utterance_id: Mapped[int] = mapped_column(
        ForeignKey("utterances.id", ondelete="CASCADE"), nullable=False
    )
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Collection(Base):
    """A learned descriptor for an ad-hoc personal list (movies to watch, books
    to read, gift ideas). Created the first time the extraction model flags a
    record as an item in such a list; keyed by the records.kind slug the items
    share. synonyms / item_noun feed the plan/decide prompts so the list stays
    findable. The model only *proposes* — Python (collections/registry.py) owns
    identity."""
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind_slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    item_noun: Mapped[str | None] = mapped_column(Text, nullable=True)
    synonyms: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    field_hint: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    example_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("records.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RecordPerson(Base):
    __tablename__ = "record_people"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordPlace(Base):
    __tablename__ = "record_places"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordItem(Base):
    __tablename__ = "record_items"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecordOccasion(Base):
    __tablename__ = "record_occasions"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), primary_key=True
    )
    occasion_id: Mapped[int] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)


class OccasionPerson(Base):
    __tablename__ = "occasion_people"

    occasion_id: Mapped[int] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_last_at", "last_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="text")
    utterance_id: Mapped[int | None] = mapped_column(
        ForeignKey("utterances.id", ondelete="SET NULL"), nullable=True
    )
    audio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FileNode(Base):
    __tablename__ = "file_nodes"
    __table_args__ = (
        Index("ix_file_nodes_path_key", "path_key", unique=True),
        Index("ix_file_nodes_parent_key", "parent_key"),
        Index("ix_file_nodes_content_hash", "content_hash"),
        Index("ix_file_nodes_status", "status"),
        Index("ix_file_nodes_media_kind", "media_kind"),
        Index("ix_file_nodes_registered_root", "registered_root",
              postgresql_where=text("registered_root")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False)
    parent_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # file|dir
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mtime: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_root: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumb_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FileChunk(Base):
    __tablename__ = "file_chunks"
    __table_args__ = (
        Index("ix_file_chunks_file_id_ord", "file_id", "ord", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=False)
    tsv = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )


class FileEdge(Base):
    __tablename__ = "file_edges"
    __table_args__ = (
        Index("ix_file_edges_src_rel", "src_id", "rel"),
        Index("ix_file_edges_dst_rel", "dst_id", "rel"),
        Index("ix_file_edges_uniq", "src_id", "dst_id", "rel", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    src_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    dst_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    rel: Mapped[str] = mapped_column(String(16), nullable=False)  # contains|references
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FileEntityLink(Base):
    __tablename__ = "file_entity_links"
    __table_args__ = (
        Index("ix_file_entity_links_uniq", "file_id", "etype", "entity_id", unique=True),
        Index("ix_file_entity_links_entity", "etype", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    etype: Mapped[str] = mapped_column(String(8), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="summary")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FileCaption(Base):
    __tablename__ = "file_captions"
    __table_args__ = (
        Index("ix_file_captions_file_id_created_at", "file_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FileTag(Base):
    """A salient term pulled from a file's caption or summary — the fast,
    fuzzy surface layer over FileEntityLink. "me and nafay in hunza" tags a
    picture with ("Nafay", person), ("Hunza", place), ("<owner>", self),
    ("Me", self). `media_kind` is denormalised so "photos of X" is one query.
    """
    __tablename__ = "file_tags"
    __table_args__ = (
        Index("ix_file_tags_uniq", "file_id", "norm", "kind", unique=True),
        Index("ix_file_tags_norm", "norm"),
        Index("ix_file_tags_media_norm", "media_kind", "norm"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    term: Mapped[str] = mapped_column(Text, nullable=False)
    norm: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    media_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    entity_etype: Mapped[str | None] = mapped_column(String(8), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="caption")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WebCache(Base):
    """A web-backed answer held until expires_at — a Tier-A templated reply or
    a Tier-C single-call synthesis. Keyed by normalised query + kind so a
    repeat question inside the TTL costs zero network and zero model tokens."""
    __tablename__ = "web_cache"
    __table_args__ = (
        Index("ix_web_cache_uniq", "query_norm", "kind", unique=True),
        Index("ix_web_cache_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    query_norm: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # news|fact|instant
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    tier: Mapped[str] = mapped_column(String(1), nullable=False)  # a|c
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Tracker(Base):
    """Tier B: a labelled web source polled on an interval. Each poll writes a
    `reading` record, so "petrol today vs yesterday" is a query over memory."""
    __tablename__ = "trackers"
    __table_args__ = (
        Index("ix_trackers_norm", "norm", unique=True),
        Index("ix_trackers_enabled", "enabled", postgresql_where=text("enabled")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    norm: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    extractor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    interval_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default="720")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_polled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
