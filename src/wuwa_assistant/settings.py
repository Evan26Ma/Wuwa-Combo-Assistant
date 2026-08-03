from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "calibration_completed": False,
    "preset_id": "kaxiaqian-startup",
    "only_when_game_active": True,
    "game_titles": ["鸣潮", "Wuthering Waves"],
    "opacity": 0.94,
    "scale": 1.0,
    "sound_enabled": False,
    "vision_enabled": True,
    "team_orders": {},
    "overlay": {
        "enabled": True,
        "x": None,
        "y": 72,
        "scale": 1.0,
        "layout": "horizontal",
        "move_mode": False,
        "show_icons": True,
        "toggle_hotkey_enabled": True,
    },
    "keymap": {
        "basic": "MOUSE_LEFT",
        "heavy": "MOUSE_LEFT",
        "jump": "SPACE",
        "dodge": "SHIFT",
        "skill": "E",
        "echo": "Q",
        "liberation": "R",
        "utility": "F",
        "forward": "W",
        "slot1": "1",
        "slot2": "2",
        "slot3": "3",
        "reset_primary": "ESC",
        "reset_secondary": "F8",
        "toggle_overlay": "F7",
    },
    "heavy_hold_ms": 360,
    "poll_interval_ms": 8,
    "input_guard": {
        "enabled": True,
        "basic_lock_ms": 110,
        "liberation_min_ms": 900,
        "liberation_enter_timeout_ms": 1200,
        "liberation_fallback_ms": 3000,
        "liberation_max_ms": 8000,
    },
    "vision": {
        "monitor_index": 1,
        "roi": {"left": 0, "top": 0, "width": 320, "height": 180},
        "match_threshold": 0.86,
    },
    "state_vision": {
        "enabled": False,
        "okww_path": "F:\\Tools\\okww",
        "signals": {},
    },
    "video_recognition": {
        "ffmpeg_path": "F:\\GAM3\\wwcombo 正式版 0.6 便携版\\wwcombo 正式版 0.6 便携版\\ffmpeg.exe",
        "video_path": "",
        "fps": 30,
        "cycle_start_ms": 0,
        "bounds_percent": {"x": 0.0, "y": 0.0, "width": 26.0, "height": 22.0},
    },
}


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "WuwaComboAssistant"


def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir()
        self.path = self.root / "settings.json"
        self.templates_dir = self.root / "templates"
        self.assets_dir = self.root / "okww-assets"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(DEFAULT_SETTINGS)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return deepcopy(DEFAULT_SETTINGS)
            return _merge(DEFAULT_SETTINGS, data)
        except (OSError, ValueError, TypeError):
            return deepcopy(DEFAULT_SETTINGS)

    def save(self, settings: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def export_presets(self, presets: list[dict[str, Any]]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "combos.export.json"
        path.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
