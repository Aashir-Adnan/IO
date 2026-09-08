from __future__ import annotations

from sqlalchemy import func, select

from io_assistant.conversation.context import Turn
from io_assistant.db import models as m

__all__ = ["ConversationStore"]


class ConversationStore:
    def __init__(self, session_factory):
        self._sf = session_factory

    def create(self) -> int:
        with self._sf() as s:
            conv = m.Conversation()
            s.add(conv)
            s.commit()
            return conv.id

    def active_id(self) -> int | None:
        with self._sf() as s:
            return s.execute(
                select(m.Conversation.id)
                .order_by(m.Conversation.last_at.desc(), m.Conversation.id.desc())
                .limit(1)
            ).scalar_one_or_none()

    def ensure_active(self) -> int:
        return self.active_id() or self.create()

    def append(
        self, conv_id, role, text, *, kind=None, intent=None,
        source="text", utterance_id=None, audio_ms=None,
    ) -> int:
        with self._sf() as s:
            conv = s.get(m.Conversation, conv_id)
            if conv is None:
                raise ValueError(f"no conversation {conv_id}")
            msg = m.Message(
                conversation_id=conv_id, role=role, text=text, kind=kind,
                intent=intent, source=source, utterance_id=utterance_id,
                audio_ms=audio_ms,
            )
            s.add(msg)
            conv.last_at = func.now()
            if role == "user" and conv.title is None:
                conv.title = text.strip()[:80]
            s.commit()
            return msg.id

    def recent_turns(self, conv_id, n: int = 6) -> list[Turn]:
        with self._sf() as s:
            rows = s.execute(
                select(m.Message.role, m.Message.text)
                .where(m.Message.conversation_id == conv_id)
                .order_by(m.Message.created_at.desc(), m.Message.id.desc())
                .limit(n)
            ).all()
        return [Turn(role=r, text=t) for r, t in reversed(rows)]

    def history(self, conv_id, *, before_id=None, limit: int = 50) -> list[dict]:
        with self._sf() as s:
            stmt = select(m.Message).where(m.Message.conversation_id == conv_id)
            if before_id is not None:
                stmt = stmt.where(m.Message.id < before_id)
            stmt = stmt.order_by(m.Message.id.desc()).limit(limit)
            rows = s.execute(stmt).scalars().all()
        return [
            {
                "id": r.id, "role": r.role, "text": r.text, "kind": r.kind,
                "intent": r.intent, "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    def list_conversations(self, limit: int = 40) -> list[dict]:
        with self._sf() as s:
            rows = s.execute(
                select(
                    m.Conversation.id, m.Conversation.title, m.Conversation.last_at,
                    func.count(m.Message.id),
                )
                .outerjoin(m.Message, m.Message.conversation_id == m.Conversation.id)
                .group_by(m.Conversation.id)
                .order_by(m.Conversation.last_at.desc())
                .limit(limit)
            ).all()
        return [
            {"id": i, "title": t, "last_at": la.isoformat(), "message_count": c}
            for i, t, la, c in rows
        ]
