from __future__ import annotations

from io_assistant.models_domain import FilesCard

__all__ = ["files_card"]


def files_card(answer) -> FilesCard:
    return FilesCard(hits=list(answer.hits), searched=answer.searched)
