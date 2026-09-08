from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

__all__ = ["thumb_name", "make_thumb", "exif_captured_at"]

_EXIF_DTO = 36867  # DateTimeOriginal


def thumb_name(path_key: str) -> str:
    return hashlib.sha256(path_key.encode("utf-8")).hexdigest()[:16] + ".webp"


def make_thumb(path: Path, media_kind: str, out_dir: Path, *,
               path_key: str) -> Path | None:
    if media_kind != "image":
        return None
    try:
        from PIL import Image, ImageOps

        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / thumb_name(path_key)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((512, 512))
            im.convert("RGB").save(dest, "WEBP", quality=80)
        return dest
    except Exception:
        return None


def exif_captured_at(path: Path) -> dt.datetime | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            raw = im.getexif().get(_EXIF_DTO)
        if not raw:
            return None
        naive = dt.datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        return naive.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None
