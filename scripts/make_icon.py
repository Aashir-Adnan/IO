"""Generate assets/io.ico + assets/io-512.png from assets/io-logo.png."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
_ROOT = Path(__file__).resolve().parents[1]


def _square(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    if w == h:
        return im
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def make_icon(src: Path, ico_out: Path, png_out: Path) -> None:
    im = _square(Image.open(src))
    ico_out.parent.mkdir(parents=True, exist_ok=True)
    im.resize((256, 256), Image.LANCZOS).save(ico_out, format="ICO", sizes=_ICO_SIZES)
    im.resize((512, 512), Image.LANCZOS).save(png_out, format="PNG")


def main() -> None:
    src = _ROOT / "assets" / "io-logo.png"
    if not src.exists():
        raise SystemExit(f"missing {src} — drop the logo there first")
    ico = _ROOT / "assets" / "io.ico"
    png = _ROOT / "assets" / "io-512.png"
    make_icon(src, ico, png)
    print(ico)
    print(png)


if __name__ == "__main__":
    main()
