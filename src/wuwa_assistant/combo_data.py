from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ComboPreset, Cue


ASSET_ROOT = Path(__file__).resolve().parent / "assets"
BUILTIN_COMBOS_PATH = ASSET_ROOT / "combos" / "builtin.json"
ICON_MAPPINGS_PATH = ASSET_ROOT / "action_icons" / "icon_mappings.json"


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 JSON 对象")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空文本")
    return value.strip()


def _cue(value: Any, *, combo_id: str, phase_id: str, characters: tuple[str, str, str]) -> Cue:
    data = _object(value, f"{combo_id}.{phase_id}.step")
    character = _text(data.get("character"), "character")
    if character not in characters:
        raise ValueError(f"步骤角色 {character} 不属于队伍 {characters}")
    return Cue(
        id=_text(data.get("id"), "step.id"),
        character=character,
        segment=_text(data.get("segment"), "step.segment"),
        action=_text(data.get("action"), "step.action"),
        display_key=_text(data.get("display_text"), "step.display_text"),
        condition=str(data.get("condition", "")),
        earliest_ms=max(0, int(data.get("earliest_ms", 0))),
        recommended_ms=max(0, int(data.get("recommended_ms", 0))),
        latest_ms=max(0, int(data.get("latest_ms", 0))),
        source_at=str(data.get("source_at", "")),
        timing_quality=str(data.get("timing_quality", "参考")),
        anchor=bool(data.get("anchor", False)),
        hold_ms=max(0, int(data.get("hold_ms", 0))),
        vision_signal=str(data.get("vision_signal", "")),
        advice=str(data.get("advice", "")),
    )


def _phase(
    value: Any,
    *,
    combo_id: str,
    phase_label: str,
    characters: tuple[str, str, str],
    source_url: str,
    next_preset_id: str = "",
) -> ComboPreset:
    data = _object(value, f"{combo_id}.{phase_label}")
    phase_id = _text(data.get("id"), f"{phase_label}.id")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{phase_id}.steps 必须是非空数组")
    cues = tuple(_cue(step, combo_id=combo_id, phase_id=phase_id, characters=characters) for step in steps)
    return ComboPreset(
        id=phase_id,
        name=_text(data.get("name"), f"{phase_id}.name"),
        team=characters,
        phase=phase_label,
        target_total_ms=max(0, int(data.get("target_total_ms", 0))),
        source_url=source_url,
        raw_axis=str(data.get("raw_axis", "")),
        cues=cues,
        next_preset_id=next_preset_id,
        loops=bool(data.get("loops", phase_label == "循环")),
    )


def load_combo_library(path: Path | None = None) -> tuple[ComboPreset, ...]:
    source = path or BUILTIN_COMBOS_PATH
    root = _object(json.loads(source.read_text(encoding="utf-8")), "root")
    if int(root.get("version", 0)) != 1:
        raise ValueError("不支持的连招 JSON 版本")
    combos = root.get("combos")
    if not isinstance(combos, list) or not combos:
        raise ValueError("combos 必须是非空数组")
    presets: list[ComboPreset] = []
    seen_ids: set[str] = set()
    for value in combos:
        combo = _object(value, "combo")
        combo_id = _text(combo.get("id"), "combo.id")
        characters_value = combo.get("characters")
        if not isinstance(characters_value, list) or len(characters_value) != 3:
            raise ValueError(f"{combo_id}.characters 必须包含三个角色")
        characters = tuple(_text(item, "character") for item in characters_value)
        if len(set(characters)) != 3:
            raise ValueError(f"{combo_id}.characters 不能重复")
        source_url = str(combo.get("source_url", ""))
        cycle_data = _object(combo.get("cycle"), f"{combo_id}.cycle")
        cycle_id = _text(cycle_data.get("id"), "cycle.id")
        startup = _phase(
            combo.get("startup"), combo_id=combo_id, phase_label="启动",
            characters=characters, source_url=source_url, next_preset_id=cycle_id,
        )
        cycle = _phase(
            cycle_data, combo_id=combo_id, phase_label="循环",
            characters=characters, source_url=source_url,
        )
        for preset in (startup, cycle):
            if preset.id in seen_ids:
                raise ValueError(f"重复的连招阶段 ID：{preset.id}")
            seen_ids.add(preset.id)
            presets.append(preset)
    return tuple(presets)


def load_icon_mappings(path: Path | None = None) -> dict[str, dict[str, str]]:
    source = path or ICON_MAPPINGS_PATH
    root = _object(json.loads(source.read_text(encoding="utf-8")), "icon mappings")
    mappings = _object(root.get("mappings"), "mappings")
    normalized: dict[str, dict[str, str]] = {}
    for action, value in mappings.items():
        entry = _object(value, f"mapping.{action}")
        normalized[str(action)] = {
            "token": _text(entry.get("token"), f"mapping.{action}.token"),
            "icon": _text(entry.get("icon"), f"mapping.{action}.icon"),
            "label": _text(entry.get("label"), f"mapping.{action}.label"),
        }
    return normalized
