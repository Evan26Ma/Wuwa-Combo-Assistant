from __future__ import annotations

import ctypes
from ctypes import wintypes


if hasattr(ctypes, "windll"):
    _user32 = ctypes.windll.user32
else:  # pragma: no cover - non-Windows import safety
    _user32 = None


def foreground_window_title() -> str:
    if _user32 is None:
        return ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_game_foreground(titles: list[str]) -> bool:
    title = foreground_window_title().casefold()
    if title.startswith("鸣潮逐键教练"):
        return False
    return bool(title and any(candidate.casefold() in title for candidate in titles if candidate))


def enumerate_window_titles() -> list[str]:
    if _user32 is None:
        return []
    titles: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if title and title not in titles:
                titles.append(title)
        return True

    _user32.EnumWindows(callback_type(visit), 0)
    return sorted(titles, key=str.casefold)
