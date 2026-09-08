from io_assistant.conversation.context import Turn, format_context


def test_empty():
    assert format_context([]) == ""


def test_renders_oldest_first():
    out = format_context([Turn("user", "hi"), Turn("assistant", "hello"),
                          Turn("user", "what work do I have")])
    assert out.splitlines() == ["you: hi", "io: hello", "you: what work do I have"]


def test_drops_from_front_when_over_cap():
    turns = [Turn("user", "x" * 300) for _ in range(10)]
    out = format_context(turns, max_chars=700)
    assert len(out) <= 700
    assert out.endswith("x" * 300)  # newest kept
