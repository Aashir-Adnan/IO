import datetime as dt
from pathlib import Path

from PIL import Image

from io_assistant.files.thumbs import make_thumb, exif_captured_at, thumb_name

FX = Path(__file__).parent / "fixtures" / "files"


def test_make_thumb_image(tmp_path):
    out = make_thumb(FX / "pic.jpg", "image", tmp_path, path_key="k/pic.jpg")
    assert out is not None and out.exists()
    with Image.open(out) as im:
        assert max(im.size) <= 512
        assert im.format == "WEBP"
    assert out.name == thumb_name("k/pic.jpg")


def test_make_thumb_video_is_none(tmp_path):
    assert make_thumb(FX / "clip.mp4", "video", tmp_path, path_key="k/clip.mp4") is None


def test_make_thumb_corrupt_is_none(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert make_thumb(bad, "image", tmp_path, path_key="k/bad.jpg") is None


def test_exif_captured_at_parses():
    got = exif_captured_at(FX / "pic.jpg")
    assert isinstance(got, dt.datetime) and got.year == 2026


def test_exif_missing_is_none(tmp_path):
    p = tmp_path / "noexif.jpg"
    Image.new("RGB", (8, 8), "blue").save(p)
    assert exif_captured_at(p) is None
