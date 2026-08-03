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


def test_manual_session_start_and_stop_gate_combo_inputs():
    app = _app_with_overlay_settings()
    app.settings["manual_listening"] = {"enabled": True}
    app.listening_session_active = False
    app.overlay_temporarily_hidden = True

    app._handle_input_event(InputEvent("utility", 1.0))
    assert app.events.empty()

    app._handle_input_event(InputEvent("listening_start", 1.1))
    assert app.listening_session_active is True
    assert app.overlay_temporarily_hidden is False
    assert app.events.get_nowait() == ("command", "session_started")

    app._handle_input_event(InputEvent("listening_stop", 1.2))
    assert app.listening_session_active is False
    assert app.events.get_nowait() == ("command", "session_stopped")
