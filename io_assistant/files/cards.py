from __future__ import annotations

from io_assistant.models_domain import FilesCard, GalleryCard

__all__ = ["files_card", "gallery_card"]


def files_card(answer) -> FilesCard:
    return FilesCard(hits=list(answer.hits), searched=answer.searched)


def gallery_card(payload: GalleryCard) -> GalleryCard:
    return payload
