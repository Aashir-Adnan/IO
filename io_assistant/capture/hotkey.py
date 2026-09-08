from __future__ import annotations

__all__ = ["push_to_talk"]


def push_to_talk(combo: str, on_press, on_release):
    """Register a global hotkey. Returns a started pynput listener with .stop().

    pynput's GlobalHotKeys fires once per activation; a true press/release
    hold is emulated by treating the activation as press and scheduling
    on_release after a short tail is handled by the caller's own timing.
    For Phase 1 the activation toggles recording start; the loop stops on the
    next activation.
    """
    from pynput import keyboard

    state = {"recording": False}

    def _toggle():
        if not state["recording"]:
            state["recording"] = True
            on_press()
        else:
            state["recording"] = False
            on_release()

    listener = keyboard.GlobalHotKeys({combo: _toggle})
    listener.start()
    return listener
