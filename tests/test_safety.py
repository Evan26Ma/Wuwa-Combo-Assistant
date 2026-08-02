from pathlib import Path
from types import SimpleNamespace

from wuwa_assistant.dashboard import DashboardApp
from wuwa_assistant.models import InputEvent


def test_source_contains_no_input_injection_api():
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    forbidden = ["SendInput", "keybd_event", "mouse_event", "SetWindowsHookEx"]
    for token in forbidden:
        assert token not in source


def test_legacy_overlay_has_been_retired():
    assert not Path("src/wuwa_assistant/ui.py").exists()
    dashboard = Path("src/wuwa_assistant/dashboard.py").read_text(encoding="utf-8")
    for page_id in ("coach", "axis", "teams", "keys", "prompts", "vision", "video", "help", "about"):
        assert f'(\"{page_id}\", self._build_' in dashboard


def test_dashboard_routes_reset_keys_without_advancing_combo():
    forwarded = []
    app = DashboardApp.__new__(DashboardApp)
    app.events = __import__("queue").SimpleQueue()
    app.engine = SimpleNamespace(process=forwarded.append)

    app._handle_input_event(InputEvent("reset_primary", 1.0))
    assert app.events.get_nowait() == ("command", "reset")
    assert forwarded == []

    attack = InputEvent("attack", 2.0)
    app._handle_input_event(attack)
    assert forwarded == [attack]
