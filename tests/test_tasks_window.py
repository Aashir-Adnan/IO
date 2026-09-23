import sys
import types

import pytest

import io_assistant.service.runner as runner


class FakeWindow:
    def __init__(self, **kw):
        self.kw = kw
        self.restored = 0
        self.destroyed = 0
        self.events = types.SimpleNamespace(closed=_Event())

    def restore(self):
        self.restored += 1

    def show(self):
        pass

    def destroy(self):
        self.destroyed += 1
        self.events.closed.fire()


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for h in self.handlers:
            h()


@pytest.fixture
def fake_webview(monkeypatch):
    mod = types.ModuleType("webview")
    mod.created = []
    mod.screens = [types.SimpleNamespace(width=1920, height=1080)]

    def create_window(title, url, **kw):
        w = FakeWindow(title=title, url=url, **kw)
        mod.created.append(w)
        return w

    mod.create_window = create_window
    monkeypatch.setitem(sys.modules, "webview", mod)
    monkeypatch.setattr(runner, "_TASKS_WINDOW", None)
    return mod


def test_opens_a_small_frameless_always_on_top_window_bottom_right(fake_webview):
    assert runner.open_tasks_window("http://127.0.0.1:8765/app/") is True
    (w,) = fake_webview.created
    assert w.kw["url"] == "http://127.0.0.1:8765/app/#tasks"
    assert (w.kw["width"], w.kw["height"]) == (340, 520)
    assert w.kw["on_top"] is True and w.kw["frameless"] is True
    assert w.kw["resizable"] is False
    assert w.kw["easy_drag"] is False                    # IO windows are never draggable
    assert w.kw["x"] == 1920 - 340 - 24 and w.kw["y"] == 1080 - 520 - 72


def test_a_second_call_focuses_the_existing_window(fake_webview):
    runner.open_tasks_window("http://127.0.0.1:8765/app/")
    runner.open_tasks_window("http://127.0.0.1:8765/app/")
    assert len(fake_webview.created) == 1
    assert fake_webview.created[0].restored == 1


def test_closing_lets_it_open_again(fake_webview):
    runner.open_tasks_window("http://127.0.0.1:8765/app/")
    fake_webview.created[0].destroy()
    runner.open_tasks_window("http://127.0.0.1:8765/app/")
    assert len(fake_webview.created) == 2


def test_a_hash_already_on_the_url_is_replaced(fake_webview):
    runner.open_tasks_window("http://127.0.0.1:8765/app/#standby")
    assert fake_webview.created[0].kw["url"].endswith("/app/#tasks")


def test_without_screen_info_it_still_opens(fake_webview):
    fake_webview.screens = []
    assert runner.open_tasks_window("http://x/app/") is True
    assert fake_webview.created[0].kw["x"] is None


def test_the_tasks_api_closes_the_window(fake_webview):
    runner.open_tasks_window("http://x/app/")
    runner.TasksApi().close()
    assert fake_webview.created[0].destroyed == 1
