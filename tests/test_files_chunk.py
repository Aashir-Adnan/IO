from io_assistant.files.chunk import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("hello world", chunk_tokens=400, overlap=40, max_chunks=60) == ["hello world"]


def test_empty_text_is_no_chunks():
    assert chunk_text("   ", chunk_tokens=400, overlap=40, max_chunks=60) == []


def test_splits_on_paragraphs_and_respects_size():
    para = ("word " * 300).strip()          # ~1500 chars ~ 375 tokens
    text = para + "\n\n" + para
    chunks = chunk_text(text, chunk_tokens=400, overlap=20, max_chunks=60)
    assert len(chunks) == 2
    assert all(len(c) <= 400 * 4 + 80 for c in chunks)


def test_hard_splits_a_giant_paragraph():
    giant = "x" * 5000
    chunks = chunk_text(giant, chunk_tokens=100, overlap=0, max_chunks=60)
    assert len(chunks) >= 12


def test_stops_at_max_chunks():
    text = "\n\n".join("para " + str(i) for i in range(100))
    assert len(chunk_text(text, chunk_tokens=1, overlap=0, max_chunks=5)) == 5
