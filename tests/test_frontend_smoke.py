"""Opt-in Playwright DOM smoke for the Nocturne client.

    IO_UI_TESTS=1 uv run pytest -m ui -q

One-time setup:  uv run playwright install chromium
"""
import pytest

pytestmark = pytest.mark.ui


def test_standby_renders_greeting_and_agenda(ui_page):
    ui_page.open()
    ui_page.wait_for(".standby-greet")
    greet = ui_page.eval("document.querySelector('.standby-greet').textContent")
    assert "Aashir" in greet
    ui_page.wait_for(".agenda-row")
    rows = ui_page.eval("document.querySelectorAll('.agenda-row').length")
    assert rows == 2


def test_rail_switches_to_conversation_view(ui_page):
    ui_page.open()
    ui_page.goto_view("conversation")
    ui_page.wait_for("#thread")
    assert ui_page.eval("!!document.querySelector('#thread')")


def test_no_external_requests(ui_page):
    page = ui_page.page
    external = []
    page.on("request", lambda r: external.append(r.url)
            if not r.url.startswith(ui_page.base) and not r.url.startswith("data:")
            else None)
    ui_page.open()
    ui_page.goto_view("conversation")
    page.wait_for_timeout(200)
    assert external == [], external
