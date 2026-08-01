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
            self.reset()

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

    def process(self, event: InputEvent) -> None:
        with self._lock:
            if not self.active or self.cue is None:
                return
            self._history.append(event)
            cue = self.cue
            elapsed_ms = int((event.timestamp - self.cue_started_at) * 1000)
            if event.action == cue.action:
                if cue.hold_ms and event.held_ms < cue.hold_ms:
                    self.message = f"长按不足：需要约 {cue.hold_ms}ms"
                    self.confidence = 0.72
                    self._emit(event.timestamp)
                    return
                timing = "过早" if elapsed_ms < cue.earliest_ms else "偏晚" if elapsed_ms > cue.latest_ms else "准确"
                self.index += 1
                self.cue_started_at = event.timestamp
                self.confidence = 1.0 if timing == "准确" else 0.88
                self.message = f"{timing} · 已识别 {cue.display_key}"
                if self.index >= len(self.preset.cues):
                    self._advance_phase(event.timestamp)
                self._emit(event.timestamp)
                return

            recovered = self._try_anchor_resync(event)
            if not recovered:
                self.message = f"观察到 {event.action}，等待 {cue.display_key} 或下一个关键锚点"
                self.confidence = 0.45
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
            if not candidate.anchor or candidate.action != event.action:
                continue
            score = 4
            if candidate.character == self._observed_character():
                score += 3
            template_start = max(0, idx - min(3, len(recent)))
            template = [cue.action for cue in self.preset.cues[template_start:idx + 1]]
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
        role_by_action = {
            "slot1": self.preset.team[0],
            "slot2": self.preset.team[1],
            "slot3": self.preset.team[2],
        }
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
        elapsed = int(((now or time.perf_counter()) - self.cue_started_at) * 1000)
        if elapsed < cue.earliest_ms:
            return "WAIT"
        if elapsed <= cue.latest_ms:
            return "READY"
        return "LATE"

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
