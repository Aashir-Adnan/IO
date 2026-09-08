from pathlib import Path
from io_assistant.config import FilesConfig
from io_assistant.files.extract import read_document

FX = Path(__file__).parent / "fixtures" / "files"


def test_reads_markdown_with_title():
    d = read_document(FX / "notes.md", FilesConfig())
    assert d.status == "ok"
    assert "lease" in d.text.lower()
    assert d.title == "Apartment Notes"


def test_reads_csv_rows():
    d = read_document(FX / "data.csv", FilesConfig())
    assert d.status == "ok"
    assert "Granjur" in d.text


def test_reads_pdf():
    d = read_document(FX / "sample.pdf", FilesConfig())
    assert d.status == "ok"
    assert d.text.strip()


def test_reads_docx():
    d = read_document(FX / "sample.docx", FilesConfig())
    assert d.status == "ok"
    assert d.text.strip()


def test_binary_is_unreadable():
    d = read_document(FX / "binary.bin", FilesConfig())
    assert d.status == "unreadable"


def test_oversize_keeps_no_text(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 5000)
    d = read_document(big, FilesConfig(max_file_bytes=1000))
    assert d.status == "too_large"
    assert d.text == ""
