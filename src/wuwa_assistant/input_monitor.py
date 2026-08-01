from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable

from .models import InputEvent


VK_CODES = {
    "MOUSE_LEFT": 0x01,
    "MOUSE_RIGHT": 0x02,
    "MOUSE_MIDDLE": 0x04,
    "MOUSE_X1": 0x05,
    "MOUSE_X2": 0x06,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "ALT": 0x12,
    "SPACE": 0x20,
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(ord("A") + i): 0x41 + i for i in range(26)},
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}


class InputMonitor:
    """Polls only configured keys. It never injects, blocks, or hooks input."""

    def __init__(
        self,
        keymap: dict[str, str],
        callback: Callable[[InputEvent], None],
        *,
        heavy_hold_ms: int = 360,
        poll_interval_ms: int = 8,
        enabled: Callable[[], bool] | None = None,
        state_reader: Callable[[int], bool] | None = None,
    ) -> None:
        self.keymap = dict(keymap)
        self.callback = callback
        self.heavy_hold_ms = heavy_hold_ms
        self.poll_interval = max(4, poll_interval_ms) / 1000
        self.enabled = enabled or (lambda: True)
        self._state_reader = state_reader or self._win_state
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._states: dict[int, bool] = {}
        self._pressed_at: dict[int, float] = {}
        self._actions_by_vk = self._compile_mapping()

    @staticmethod
    def _win_state(vk: int) -> bool:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _compile_mapping(self) -> dict[int, list[str]]:
        mapping: dict[int, list[str]] = {}
        for action, key_name in self.keymap.items():
            vk = VK_CODES.get(str(key_name).upper())
            if vk is not None:
                mapping.setdefault(vk, []).append(action)
        return mapping

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="input-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            time.sleep(self.poll_interval)

    def poll_once(self, now: float | None = None, active: bool | None = None) -> None:
        now = time.perf_counter() if now is None else now
        active = self.enabled() if active is None else active
        for vk, actions in self._actions_by_vk.items():
            down = self._state_reader(vk) if active else False
            previous = self._states.get(vk, False)
            if down and not previous:
                self._pressed_at[vk] = now
                if "basic" not in actions and "heavy" not in actions:
                    for action in actions:
                        self.callback(InputEvent(action, now))
            elif previous and not down:
                started = self._pressed_at.pop(vk, now)
                held_ms = max(0, int((now - started) * 1000))
                if "basic" in actions or "heavy" in actions:
                    action = "heavy" if held_ms >= self.heavy_hold_ms else "basic"
                    self.callback(InputEvent(action, now, held_ms))
            self._states[vk] = down
