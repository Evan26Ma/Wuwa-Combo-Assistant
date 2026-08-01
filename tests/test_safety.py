from pathlib import Path


def test_source_contains_no_input_injection_api():
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    forbidden = ["SendInput", "keybd_event", "mouse_event", "SetWindowsHookEx"]
    for token in forbidden:
        assert token not in source


def test_legacy_overlay_has_been_retired():
    assert not Path("src/wuwa_assistant/ui.py").exists()
    dashboard = Path("src/wuwa_assistant/dashboard.py").read_text(encoding="utf-8")
    for page_id in ("coach", "axis", "teams", "keys", "prompts", "vision", "help", "about"):
        assert f'(\"{page_id}\", self._build_' in dashboard
