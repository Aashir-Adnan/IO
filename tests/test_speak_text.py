from io_assistant.speak.text import flatten_markdown


def test_strips_markdown_to_prose():
    md = "# Today\n\n- **finish** the `deck`\n- email [Sam](mailto:s@x.com)\n"
    out = flatten_markdown(md)
    assert "#" not in out and "*" not in out and "`" not in out
    assert "finish the deck" in out
    assert "Sam" in out and "mailto" not in out


def test_fenced_blocks_become_words():
    md = "Here:\n```mermaid\ngraph TD; A-->B\n```\nand\n```\nx=1\n```"
    out = flatten_markdown(md)
    assert "a diagram" in out
    assert "graph TD" not in out
