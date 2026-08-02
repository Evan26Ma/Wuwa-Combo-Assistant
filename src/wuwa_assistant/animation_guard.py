from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .models import InputEvent


@dataclass(frozen=True)
class GuardState:
    locked: bool
    reason: str = ""
    mode: str = ""
    remaining_ms: int = 0


class AnimationInputGuard:
    """Suppress combo progression while the game is unlikely to accept input.

    This mirrors OK-WW's conservative approach: liberation animations are
    detected from the party HUD disappearing and returning. Normal attacks use
    only a short configurable guard because their exact animation end is not a
    stable HUD signal. The monitor still polls physical keys; events are merely
    ignored by the coaching state machine while locked.
    """

    def __init__(self, settings: dict) -> None:
        self._lock = threading.RLock()
        self.configure(settings)
        self.reset()

    def configure(self, settings: dict) -> None:
        config = settings.get("input_guard", {})
        self.enabled = bool(config.get("enabled", True))
        self.basic_lock_ms = max(0, min(500, int(config.get("basic_lock_ms", 110))))
        self.liberation_min_ms = max(200, min(3000, int(config.get("liberation_min_ms", 900))))
        self.liberation_enter_timeout_ms = max(
            400, min(2500, int(config.get("liberation_enter_timeout_ms", 1200)))
        )
        self.liberation_fallback_ms = max(
            800, min(7000, int(config.get("liberation_fallback_ms", 3000)))
        )
        self.liberation_max_ms = max(
            self.liberation_fallback_ms, min(12000, int(config.get("liberation_max_ms", 8000)))
        )

    def reset(self) -> None:
        with self._lock:
            self._mode = ""
            self._reason = ""
            self._locked_until = 0.0
            self._minimum_until = 0.0
            self._enter_deadline = 0.0
            self._maximum_until = 0.0
            self._fallback_until = 0.0
            self._last_hud_present_at = -1.0
            self._present_streak = 0
            self._absent_streak = 0

    def allows(self, event: InputEvent, now: float | None = None) -> bool:
        if event.action in {"reset_primary", "reset_secondary"}:
            return True
        with self._lock:
            self._refresh(now if now is not None else event.timestamp)
            return not self.enabled or not self._mode

    def record(self, event: InputEvent, now: float | None = None) -> None:
        if not self.enabled:
            return
        current = now if now is not None else event.timestamp
        with self._lock:
            self._refresh(current)
            if event.action == "liberation":
                hud_recent = 0 <= current - self._last_hud_present_at <= 2.0
                self._minimum_until = current + self.liberation_min_ms / 1000
                self._maximum_until = current + self.liberation_max_ms / 1000
                self._fallback_until = current + self.liberation_fallback_ms / 1000
                self._present_streak = 0
                self._absent_streak = 0
                if hud_recent:
                    self._mode = "liberation_wait_hud_hide"
                    self._reason = "大招启动中 · 等待队伍 HUD 消失"
                    self._enter_deadline = current + self.liberation_enter_timeout_ms / 1000
                    self._locked_until = self._enter_deadline
                else:
                    self._mode = "liberation_fallback"
                    self._reason = "大招演出中 · 使用保守时长"
                    self._locked_until = self._fallback_until
            elif event.action == "basic" and self.basic_lock_ms:
                self._mode = "basic"
                self._reason = "普攻动作保护中"
                self._locked_until = current + self.basic_lock_ms / 1000

    def observe_party_hud(self, scores: dict[str, float], now: float | None = None) -> None:
        """Consume the three chosen party-slot scores from TeamVisionMonitor."""
        if not self.enabled or not scores:
            return
        current = time.perf_counter() if now is None else now
        values = [max(0.0, float(value)) for value in scores.values()]
        average = sum(values) / len(values)
        present = min(values) >= 0.68 and average >= 0.74
        absent = max(values) < 0.56 and average < 0.48
        with self._lock:
            if present:
                self._last_hud_present_at = current
                self._present_streak += 1
                self._absent_streak = 0
            elif absent:
                self._absent_streak += 1
                self._present_streak = 0
            else:
                self._present_streak = 0
                self._absent_streak = 0

            if self._mode == "liberation_wait_hud_hide" and self._absent_streak >= 2:
                self._mode = "liberation_hud_hidden"
                self._reason = "大招演出中 · 等待队伍 HUD 恢复"
                self._locked_until = self._maximum_until
            elif (
                self._mode == "liberation_hud_hidden"
                and self._present_streak >= 2
                and current >= self._minimum_until
            ):
                self._clear()
            self._refresh(current)

    def tick(self, now: float | None = None) -> GuardState:
        with self._lock:
            self._refresh(time.perf_counter() if now is None else now)
            return self._state(time.perf_counter() if now is None else now)

    def state(self, now: float | None = None) -> GuardState:
        current = time.perf_counter() if now is None else now
        with self._lock:
            self._refresh(current)
            return self._state(current)

    def _state(self, now: float) -> GuardState:
        deadline = self._maximum_until if self._mode == "liberation_hud_hidden" else self._locked_until
        return GuardState(
            locked=bool(self.enabled and self._mode),
            reason=self._reason if self.enabled else "",
            mode=self._mode if self.enabled else "",
            remaining_ms=max(0, round((deadline - now) * 1000)) if self._mode else 0,
        )

    def _refresh(self, now: float) -> None:
        if not self._mode:
            return
        if self._mode == "liberation_hud_hidden":
            if now >= self._maximum_until:
                self._clear()
        elif self._mode == "liberation_wait_hud_hide" and now >= self._locked_until:
            # Failure to confirm the disappearance is ambiguous: recognition may
            # have missed the cut-in. Prefer a bounded false lock to advancing the
            # combo during a real liberation animation.
            self._mode = "liberation_fallback"
            self._reason = "未确认 HUD 消失 · 使用保守大招时长"
            self._locked_until = self._fallback_until
        elif now >= self._locked_until:
            self._clear()

    def _clear(self) -> None:
        self._mode = ""
        self._reason = ""
        self._locked_until = 0.0
        self._minimum_until = 0.0
        self._enter_deadline = 0.0
        self._maximum_until = 0.0
        self._fallback_until = 0.0
        self._present_streak = 0
        self._absent_streak = 0
