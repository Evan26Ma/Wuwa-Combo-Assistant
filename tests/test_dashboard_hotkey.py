import queue

from wuwa_assistant.dashboard import DashboardApp
from wuwa_assistant.models import InputEvent


def _app_with_overlay_settings(*, enabled=True, hotkey_enabled=True):
    app = DashboardApp.__new__(DashboardApp)
    app.settings = {
        "overlay": {
            "enabled": enabled,
            "toggle_hotkey_enabled": hotkey_enabled,
        },
    }
    app.events = queue.SimpleQueue()
    return app


def test_overlay_hotkey_queues_temporary_toggle():
    app = _app_with_overlay_settings()
    app._handle_input_event(InputEvent("toggle_overlay", 1.0))
    assert app.events.get_nowait() == ("command", "toggle_overlay_temp")


def test_overlay_hotkey_is_ignored_when_option_is_disabled():
    app = _app_with_overlay_settings(hotkey_enabled=False)
    app._handle_input_event(InputEvent("toggle_overlay", 1.0))
    assert app.events.empty()


def test_overlay_hotkey_does_not_override_master_switch():
    app = _app_with_overlay_settings(enabled=False)
    app._handle_input_event(InputEvent("toggle_overlay", 1.0))
    assert app.events.empty()
