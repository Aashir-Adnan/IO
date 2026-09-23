"""html.parser text extraction — pure, no network."""
from __future__ import annotations

from io_assistant.web.fetch import extract_text


def test_extracts_title_and_prose_drops_chrome():
    html = """
    <html><head><title>Petrol prices rise</title></head>
    <body>
      <nav><a>Home</a><a>News</a><a>Sport</a></nav>
      <header>Site name</header>
      <article>
        <h1>Petrol prices rise again</h1>
        <p>The price of petrol increased to 290 rupees per litre on Monday,
        up from 275 rupees the previous week, the ministry said.</p>
        <script>var x = 1; tracker();</script>
        <p>Analysts expect a further rise next month.</p>
      </article>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    title, text = extract_text(html)
    assert title == "Petrol prices rise"
    assert "290 rupees per litre" in text
    assert "further rise next month" in text
    assert "tracker()" not in text
    assert "Sport" not in text
    assert "Copyright 2026" not in text


def test_malformed_html_still_yields_text():
    title, text = extract_text("<p>unclosed paragraph with a reasonably long sentence here")
    assert "unclosed paragraph with a reasonably long sentence here" in text


def test_empty_html():
    title, text = extract_text("")
    assert title == ""
    assert text == ""
