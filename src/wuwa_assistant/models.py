from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class InputEvent:
    action: str
    timestamp: float
    held_ms: int = 0


@dataclass(frozen=True)
class Cue:
    id: str
    character: str
    segment: str
    action: str
    display_key: str
    condition: str
    earliest_ms: int
    recommended_ms: int
    latest_ms: int
    source_at: str = ""
    timing_quality: str = "参考"
    anchor: bool = False
    hold_ms: int = 0
    vision_signal: str = ""
    advice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComboPreset:
    id: str
    name: str
    team: tuple[str, str, str]
    phase: str
    target_total_ms: int
    source_url: str
    raw_axis: str
    cues: tuple[Cue, ...] = field(default_factory=tuple)
    next_preset_id: str = ""
    loops: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["team"] = list(self.team)
        result["cues"] = [cue.to_dict() for cue in self.cues]
        return result


@dataclass(frozen=True)
class EngineView:
    preset_name: str
    phase: str
    index: int
    total: int
    cue: Cue | None
    next_cue: Cue | None
    elapsed_ms: int
    total_elapsed_ms: int
    timing_state: str
    message: str
    confidence: float
    active: bool
    cycle_count: int = 0
    error_cue_id: str = ""
    error_action: str = ""
    input_locked: bool = False
    lock_reason: str = ""


@dataclass(frozen=True)
class SequenceStep:
    cue: Cue
    phase: str
    phase_index: int
    state: str
