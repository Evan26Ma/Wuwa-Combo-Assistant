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
    "overlay": {"enabled": True, "x": None, "y": 72},
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
    },
    "heavy_hold_ms": 360,
    "poll_interval_ms": 8,
    "vision": {
        "monitor_index": 1,
        "roi": {"left": 0, "top": 0, "width": 320, "height": 180},
        "match_threshold": 0.86,
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
