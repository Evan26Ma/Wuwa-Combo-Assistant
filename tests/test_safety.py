from pathlib import Path


def test_source_contains_no_input_injection_api():
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src").rglob("*.py"))
    forbidden = ["SendInput", "keybd_event", "mouse_event", "SetWindowsHookEx"]
    for token in forbidden:
        assert token not in source

