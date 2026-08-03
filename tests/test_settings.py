import json

from wuwa_assistant.settings import SettingsStore
from wuwa_assistant.dashboard import DashboardApp


def test_settings_merge_defaults_and_roundtrip(tmp_path):
    store = SettingsStore(tmp_path)
    store.path.write_text(json.dumps({"opacity": 0.8, "keymap": {"skill": "G"}}), encoding="utf-8")
    settings = store.load()
    assert settings["opacity"] == 0.8
    assert settings["keymap"]["skill"] == "G"
    assert settings["keymap"]["basic"] == "MOUSE_LEFT"
    assert settings["keymap"]["reset_primary"] == "ESC"
    assert settings["keymap"]["reset_secondary"] == "F8"
    assert settings["overlay"]["layout"] == "horizontal"
    assert settings["overlay"]["move_mode"] is False
    assert settings["overlay"]["scale"] == 1.0
    assert settings["video_recognition"]["fps"] == 30
    assert settings["video_recognition"]["bounds_percent"]["width"] == 26
    assert settings["input_guard"]["enabled"] is True
    assert settings["input_guard"]["basic_lock_ms"] == 110
    assert settings["input_guard"]["liberation_fallback_ms"] == 3000
    store.save(settings)
    assert store.load() == settings


def test_export_presets(tmp_path):
    store = SettingsStore(tmp_path)
    path = store.export_presets([{"id": "one"}])
    assert json.loads(path.read_text(encoding="utf-8")) == [{"id": "one"}]


def test_overlay_scale_is_clamped_to_supported_range():
    assert DashboardApp._overlay_scale_value(.2) == .65
    assert DashboardApp._overlay_scale_value(1.25) == 1.25
    assert DashboardApp._overlay_scale_value(3) == 1.5
    assert DashboardApp._overlay_scale_value("invalid") == 1.0
