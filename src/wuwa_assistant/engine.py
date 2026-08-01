from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from .models import ComboPreset, Cue, EngineView, InputEvent


class ComboEngine:
    def __init__(self, presets: tuple[ComboPreset, ...], on_change: Callable[[EngineView], None] | None = None) -> None:
        if not presets:
            raise ValueError("at least one preset is required")
        self.presets = {preset.id: preset for preset in presets}
        self.preset = presets[0]
        self._root_preset_id = self.preset.id
        self.cycle_count = 0
        self.index = 0
        self.started_at = time.perf_counter()
        self.cue_started_at = self.started_at
        self.active = True
        self.message = "等待你的实际游戏输入"
        self.confidence = 1.0
        self._history: deque[InputEvent] = deque(maxlen=10)
        self._vision_character = ""
        self._vision_character_at = -1.0
        self._team_order = tuple(self.preset.team)
        self._team_order_confirmed = False
        self._pending_slot_event: InputEvent | None = None
        self._on_change = on_change
        self._lock = threading.RLock()

    @property
    def cue(self) -> Cue | None:
        if 0 <= self.index < len(self.preset.cues):
            return self.preset.cues[self.index]
        return None

    def select(self, preset_id: str) -> None:
        with self._lock:
            if preset_id not in self.presets:
                raise KeyError(preset_id)
            selected = self.presets[preset_id]
            # Old configs may still point at a cycle. Selecting a team always starts
            # from its startup phase when that phase is available.
            if selected.phase == "循环":
                startup_id = preset_id.replace("-cycle", "-startup")
                selected = self.presets.get(startup_id, selected)
            self.preset = selected
            self._root_preset_id = selected.id
            self._team_order = tuple(selected.team)
            self._team_order_confirmed = False
            self._pending_slot_event = None
            self.reset()

    @property
    def team_order(self) -> tuple[str, str, str]:
        return self._team_order

    @property
    def team_order_confirmed(self) -> bool:
        return self._team_order_confirmed

    def set_team_order(self, order: tuple[str, str, str] | list[str], *, confirmed: bool = True) -> bool:
        """Apply the actual in-game slot order when it contains the selected team."""
        with self._lock:
            normalized = tuple(str(item) for item in order)
            if len(normalized) != 3 or set(normalized) != set(self.preset.team):
                return False
            changed = normalized != self._team_order or (confirmed and not self._team_order_confirmed)
            self._team_order = normalized
            self._team_order_confirmed = self._team_order_confirmed or confirmed
            if changed:
                self.message = "队伍位置已识别：" + " · ".join(
                    f"{index + 1} {name}" for index, name in enumerate(normalized)
                )
                self._emit()
            return changed

    def action_for(self, cue: Cue) -> str:
        """Resolve a character switch cue to its current physical team slot."""
        if cue.action.startswith("slot") and cue.character in self._team_order:
            return f"slot{self._team_order.index(cue.character) + 1}"
        return cue.action

    def reset(self) -> None:
        with self._lock:
            now = time.perf_counter()
            self.preset = self.presets[self._root_preset_id]
            self.index = 0
            self.cycle_count = 0
            self.started_at = now
            self.cue_started_at = now
            self.message = "已重置，等待第一个游戏输入"
            self.confidence = 1.0
            self._history.clear()
            self._pending_slot_event = None
            self._emit(now)

    def step(self, delta: int) -> None:
        with self._lock:
            now = time.perf_counter()
            target = self.index + delta
            if delta > 0 and target >= len(self.preset.cues):
                self.index = len(self.preset.cues)
                self._advance_phase(now)
            else:
                self.index = max(0, min(len(self.preset.cues), target))
            self.cue_started_at = now
            self.message = "手动校正位置"
            self.confidence = 1.0
            self._emit()

    def set_active(self, active: bool) -> None:
        with self._lock:
            if self.active == active:
                return
            self.active = active
            self.cue_started_at = time.perf_counter()
            self.message = "正在监听游戏输入" if active else "游戏未在前台，已暂停"
            self._emit()

    def observe_character(self, character: str, timestamp: float | None = None,
                          *, learn_slot: bool = True) -> None:
        """Accept a visual observation and optionally learn the last pressed team slot."""
        with self._lock:
            observed_at = timestamp if timestamp is not None else time.perf_counter()
            self._vision_character = character
            self._vision_character_at = observed_at
            pending = self._pending_slot_event
            if not learn_slot or character not in self.preset.team or pending is None:
                return
            if observed_at - pending.timestamp > 2.5:
                self._pending_slot_event = None
                return
            target_index = int(pending.action[-1]) - 1
            current_index = self._team_order.index(character)
            if target_index != current_index:
                reordered = list(self._team_order)
                reordered[target_index], reordered[current_index] = reordered[current_index], reordered[target_index]
                self.set_team_order(reordered, confirmed=True)
            else:
                self._team_order_confirmed = True
            cue = self.cue
            if cue and cue.action.startswith("slot") and cue.character == character \
                    and self.action_for(cue) == pending.action:
                self._accept_current_cue(pending)
            self._pending_slot_event = None

    def process(self, event: InputEvent) -> None:
        with self._lock:
            if not self.active or self.cue is None:
                return
            self._history.append(event)
            if event.action in {"slot1", "slot2", "slot3"}:
                self._pending_slot_event = event
            cue = self.cue
            if event.action == self.action_for(cue):
                if cue.hold_ms and event.held_ms < cue.hold_ms:
                    self.message = f"长按不足：需要约 {cue.hold_ms}ms"
                    self.confidence = 0.72
                    self._emit(event.timestamp)
                    return
                self._accept_current_cue(event)
                return

            recovered = self._try_anchor_resync(event)
            if not recovered:
                self.message = f"观察到 {event.action}，等待 {cue.display_key} 或下一个关键锚点"
                self.confidence = 0.45
                self._emit(event.timestamp)

    def _accept_current_cue(self, event: InputEvent) -> None:
        cue = self.cue
        if cue is None:
            return
        self.index += 1
        self.cue_started_at = event.timestamp
        self.confidence = 1.0
        self.message = f"已识别 {cue.display_key}"
        if self.index >= len(self.preset.cues):
            self._advance_phase(event.timestamp)
        self._emit(event.timestamp)

    def _advance_phase(self, timestamp: float) -> None:
        """Move startup → cycle, then repeat the cycle without user input."""
        if self.preset.next_preset_id:
            self.preset = self.presets[self.preset.next_preset_id]
            self.index = 0
            self.cycle_count = 1
            self._history.clear()
            self.cue_started_at = timestamp
            self.message = "启动完成 · 已自动进入循环第 1 轮"
        elif self.preset.loops:
            self.index = 0
            self.cycle_count += 1
            self._history.clear()
            self.cue_started_at = timestamp
            self.message = f"循环完成 · 已自动进入第 {self.cycle_count} 轮"
        else:
            self.message = "整轴完成"

    def _try_anchor_resync(self, event: InputEvent) -> bool:
        start = self.index + 1
        stop = min(len(self.preset.cues), self.index + 18)
        candidates: list[tuple[int, int]] = []
        recent = [item.action for item in self._history]
        for idx in range(start, stop):
            candidate = self.preset.cues[idx]
            if not candidate.anchor or self.action_for(candidate) != event.action:
                continue
            score = 4
            if candidate.character == self._observed_character():
                score += 3
            template_start = max(0, idx - min(3, len(recent)))
            template = [self.action_for(cue) for cue in self.preset.cues[template_start:idx + 1]]
            observed = recent[-len(template):]
            suffix_matches = sum(a == b for a, b in zip(template, observed))
            score += suffix_matches
            candidates.append((score, idx))
        candidates.sort(reverse=True)
        if not candidates:
            return False
        best_score, best_idx = candidates[0]
        runner_up = candidates[1][0] if len(candidates) > 1 else -1
        if best_score < 7 or best_score - runner_up < 2:
            return False
        matched = self.preset.cues[best_idx]
        self.index = best_idx + 1
        self.cue_started_at = event.timestamp
        self.message = f"已恢复到：{matched.character} / {matched.segment}"
        self.confidence = min(0.98, best_score / 10)
        self._emit(event.timestamp)
        return True

    def _observed_character(self) -> str:
        if self._vision_character and time.perf_counter() - self._vision_character_at <= 2.0:
            return self._vision_character
        role_by_action = {f"slot{index + 1}": name for index, name in enumerate(self._team_order)}
        for event in reversed(self._history):
            if event.action in role_by_action:
                return role_by_action[event.action]
        cue = self.cue
        return cue.character if cue else ""

    def timing_state(self, now: float | None = None) -> str:
        cue = self.cue
        if not self.active:
            return "PAUSED"
        if cue is None:
            return "DONE"
        return "READY"

    def view(self, now: float | None = None) -> EngineView:
        now = now or time.perf_counter()
        cue = self.cue
        if self.index + 1 < len(self.preset.cues):
            next_cue = self.preset.cues[self.index + 1]
        elif self.preset.next_preset_id:
            next_cues = self.presets[self.preset.next_preset_id].cues
            next_cue = next_cues[0] if next_cues else None
        elif self.preset.loops:
            next_cue = self.preset.cues[0] if self.preset.cues else None
        else:
            next_cue = None
        return EngineView(
            preset_name=self.preset.name,
            phase=self.preset.phase,
            index=self.index,
            total=len(self.preset.cues),
            cue=cue,
            next_cue=next_cue,
            elapsed_ms=max(0, int((now - self.cue_started_at) * 1000)),
            total_elapsed_ms=max(0, int((now - self.started_at) * 1000)),
            timing_state=self.timing_state(now),
            message=self.message,
            confidence=self.confidence,
            active=self.active,
            cycle_count=self.cycle_count,
        )

    def _emit(self, now: float | None = None) -> None:
        if self._on_change:
            self._on_change(self.view(now))
