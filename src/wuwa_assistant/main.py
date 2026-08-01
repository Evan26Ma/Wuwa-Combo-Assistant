from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from .presets import load_builtin_presets
from .settings import SettingsStore
from .dashboard import DashboardApp


def configure_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    if sys.platform != "win32":
        print("鸣潮逐键教练仅支持 Windows 10/11。", file=sys.stderr)
        return 1
    configure_dpi()
    store = SettingsStore()
    settings = store.load()
    root = tk.Tk()
    DashboardApp(root, store, settings, load_builtin_presets())
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
