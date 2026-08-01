from __future__ import annotations

import json
import sys
from pathlib import Path


ACTIONS = {
    "basic", "heavy", "jump", "dodge", "skill", "echo", "liberation",
    "utility", "forward", "slot1", "slot2", "slot3",
}
VISION_SIGNALS = {
    "character:卡提希娅", "character:夏空", "character:千咲", "character:秧秧", "character:穗穗",
    "cartethyia:small", "cartethyia:sword1", "cartethyia:sword2", "cartethyia:sword3",
    "cartethyia:mid_air", "cartethyia:lib_big", "suisui:forte3",
}


def validate(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for field in ("id", "name", "team", "source_url", "startup", "cycle"):
        if not data.get(field):
            errors.append(f"missing top-level field: {field}")
    team = data.get("team", [])
    if not isinstance(team, list) or len(team) != 3 or len(set(team)) != 3:
        errors.append("team must contain three unique character names in slot order")
    for phase in ("startup", "cycle"):
        block = data.get(phase, {})
        if not isinstance(block, dict) or not block.get("raw_axis"):
            errors.append(f"{phase}.raw_axis is required")
            continue
        cues = block.get("cues")
        if not isinstance(cues, list) or not cues:
            errors.append(f"{phase}.cues must be a non-empty list")
            continue
        for index, cue in enumerate(cues, 1):
            prefix = f"{phase}.cues[{index}]"
            if not isinstance(cue, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("character", "segment", "action", "condition"):
                if not cue.get(field):
                    errors.append(f"{prefix}.{field} is required")
            if cue.get("character") not in team:
                errors.append(f"{prefix}.character is not in team")
            if cue.get("action") not in ACTIONS:
                errors.append(f"{prefix}.action is invalid: {cue.get('action')}")
            signal = cue.get("vision_signal", "")
            if signal and signal not in VISION_SIGNALS:
                errors.append(f"{prefix}.vision_signal is not a bundled stable signal: {signal}")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_combo_spec.py <combo-spec.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        errors = validate(path)
    except (OSError, ValueError, TypeError) as exc:
        print(f"invalid spec: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors), file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
