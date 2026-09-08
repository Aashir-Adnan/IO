from io_assistant.speak.speech_text import prep_for_speech, split_sentences


def test_prep_expands_and_pauses():
    out = prep_for_speech("**Dr. Smith** moved you to Thu 14:30 — bring the Q3 deck.")
    assert "Doctor Smith" in out
    assert "Thursday" in out
    assert "—" not in out
    assert "*" not in out
    assert "14:30" not in out


def test_split_sentences_keeps_marks():
    s = "Two things are open. Finish the deck, and call the dentist. That's it."
    assert split_sentences(s) == [
        "Two things are open.",
        "Finish the deck, and call the dentist.",
        "That's it.",
    ]


def test_split_breaks_a_long_clause():
    long = "a, " * 80  # ~240 chars, no sentence mark
    parts = split_sentences(long.strip().rstrip(","))
    assert len(parts) > 1
