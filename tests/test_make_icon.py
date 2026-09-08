import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_icon import make_icon  # noqa: E402


def test_make_icon_produces_ico_and_png(tmp_path):
    src = tmp_path / "logo.png"
    Image.new("RGBA", (300, 240), (100, 120, 200, 255)).save(src)  # non-square
    ico = tmp_path / "out.ico"
    png = tmp_path / "out-512.png"
    make_icon(src, ico, png)
    assert ico.exists() and png.exists()
    with Image.open(ico) as im:
        assert im.size[0] in (16, 32, 48, 64, 128, 256)
    with Image.open(png) as im:
        assert im.size == (512, 512) and im.mode == "RGBA"
