from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .engine import ComboEngine
from .foreground import enumerate_window_titles, is_game_foreground
from .input_monitor import InputMonitor, VK_CODES
from .models import ComboPreset, EngineView
from .presets import clone_with_timing
from .settings import SettingsStore
from .vision import VisionMonitor


COLORS = {
    "bg": "#080B12",
    "surface": "#10151F",
    "surface2": "#161D29",
    "surface3": "#202A38",
    "text": "#F4F7FB",
    "muted": "#8491A3",
    "green": "#5EF2A0",
    "green_dark": "#123F31",
    "gold": "#FFC857",
    "red": "#FF6B7A",
    "blue": "#63D8FF",
    "cyan": "#5CE1E6",
    "border": "#263244",
}

STATE_STYLE = {
    "WAIT": ("等待时机", COLORS["gold"]),
    "READY": ("现在可以按", COLORS["green"]),
    "LATE": ("已超出建议窗", COLORS["red"]),
    "PAUSED": ("已暂停", COLORS["muted"]),
    "DONE": ("本轮完成", COLORS["green"]),
}


class OverlayApp:
    def __init__(self, root: tk.Tk, store: SettingsStore, settings: dict, presets: tuple[ComboPreset, ...]) -> None:
        self.root = root
        self.store = store
        self.settings = settings
        self.presets = tuple(clone_with_timing(p, settings.get("timing_overrides", {})) for p in presets)
        self.events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.engine = ComboEngine(self.presets, lambda view: self.events.put(("view", view)))
        self.input_monitor: InputMonitor | None = None
        self.vision_monitor: VisionMonitor | None = None
        self.vision_signal = ""
        self.vision_score = -1.0
        self.force_visible = False
        self._drag_origin: tuple[int, int] | None = None
        self._tray = None
        self._last_rendered_index = -1
        self._build_overlay()
        self._select_initial_preset()
        self._restart_monitors()
        self._start_tray()
        if not self.settings.get("calibration_completed", False):
            self.root.after(350, self.open_settings)
        self.root.after(30, self._ui_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_overlay)

    def _build_overlay(self) -> None:
        self.root.title("鸣潮逐键教练")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", float(self.settings["opacity"]))
        self.root.configure(bg=COLORS["border"])
        scale = float(self.settings.get("scale", 1.0))
        width, height = int(540 * scale), int(342 * scale)
        x = self.settings["overlay"].get("x")
        x = int(x) if x is not None else max(20, self.root.winfo_screenwidth() - width - 36)
        y = int(self.settings["overlay"].get("y") or 56)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        self.panel = tk.Frame(self.root, bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["border"])
        self.panel.pack(fill="both", expand=True, padx=1, pady=1)

        accent = tk.Frame(self.panel, bg=COLORS["cyan"], height=3)
        accent.pack(fill="x")
        accent.pack_propagate(False)

        header = tk.Frame(self.panel, bg=COLORS["surface"], height=47)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_box = tk.Frame(header, bg=COLORS["surface"])
        title_box.pack(side="left", fill="y", padx=(16, 0))
        self.preset_label = tk.Label(title_box, text="", bg=COLORS["surface"], fg=COLORS["text"], font=("Microsoft YaHei UI", 11, "bold"), anchor="w")
        self.preset_label.pack(side="left", pady=11)
        self.phase_label = tk.Label(title_box, text="", bg=COLORS["surface3"], fg=COLORS["cyan"], padx=8, pady=2, font=("Microsoft YaHei UI", 8, "bold"))
        self.phase_label.pack(side="left", padx=(10, 0), pady=12)
        self.progress_label = tk.Label(header, text="", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 9))
        self.progress_label.pack(side="right", padx=16)
        for widget in (accent, header, title_box, self.preset_label, self.phase_label, self.progress_label):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)
            widget.bind("<Button-3>", self._show_context_menu)

        body = tk.Frame(self.panel, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=14, pady=(12, 10))

        command_row = tk.Frame(body, bg=COLORS["bg"], height=142)
        command_row.pack(fill="x")
        command_row.pack_propagate(False)
        key_card = tk.Frame(command_row, bg=COLORS["surface2"], width=172, highlightthickness=1, highlightbackground=COLORS["border"])
        key_card.pack(side="left", fill="y")
        key_card.pack_propagate(False)
        self.character_label = tk.Label(key_card, text="", bg=COLORS["surface2"], fg=COLORS["cyan"], font=("Microsoft YaHei UI", 10, "bold"))
        self.character_label.pack(fill="x", pady=(15, 0))
        self.key_label = tk.Label(key_card, text="—", bg=COLORS["surface2"], fg=COLORS["text"], font=("Microsoft YaHei UI", 33, "bold"))
        self.key_label.pack(fill="both", expand=True, padx=6, pady=(0, 9))

        instruction = tk.Frame(command_row, bg=COLORS["bg"])
        instruction.pack(side="left", fill="both", expand=True, padx=(14, 0))
        status_row = tk.Frame(instruction, bg=COLORS["bg"])
        status_row.pack(fill="x")
        self.state_dot = tk.Label(status_row, text="●", bg=COLORS["bg"], fg=COLORS["gold"], font=("Segoe UI", 11))
        self.state_dot.pack(side="left")
        self.state_label = tk.Label(status_row, text="", bg=COLORS["bg"], fg=COLORS["gold"], font=("Microsoft YaHei UI", 11, "bold"))
        self.state_label.pack(side="left", padx=(5, 0))
        self.segment_label = tk.Label(instruction, text="", bg=COLORS["bg"], fg=COLORS["blue"], anchor="w", font=("Microsoft YaHei UI", 9, "bold"))
        self.segment_label.pack(fill="x", pady=(9, 4))
        self.condition_label = tk.Label(instruction, text="", bg=COLORS["bg"], fg=COLORS["text"], justify="left", anchor="nw", wraplength=320, font=("Microsoft YaHei UI", 10), height=3)
        self.condition_label.pack(fill="both", expand=True)

        timing_head = tk.Frame(body, bg=COLORS["bg"])
        timing_head.pack(fill="x", pady=(10, 4))
        tk.Label(timing_head, text="时机窗口", bg=COLORS["bg"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 8)).pack(side="left")
        self.timing_label = tk.Label(timing_head, text="", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8))
        self.timing_label.pack(side="right")
        self.canvas = tk.Canvas(body, height=12, bg=COLORS["surface2"], highlightthickness=0)
        self.canvas.pack(fill="x")
        footer = tk.Frame(body, bg=COLORS["bg"])
        footer.pack(fill="x", pady=(9, 0))
        self.message_label = tk.Label(footer, text="", bg=COLORS["bg"], fg=COLORS["muted"], anchor="w", font=("Microsoft YaHei UI", 9))
        self.message_label.pack(side="left", fill="x", expand=True)
        self.vision_label = tk.Label(footer, text="", bg=COLORS["bg"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 8))
        self.vision_label.pack(side="right")
        self.next_label = tk.Label(body, text="", bg=COLORS["surface"], fg=COLORS["muted"], anchor="w", padx=10, pady=7, font=("Microsoft YaHei UI", 9))
        self.next_label.pack(fill="x", pady=(7, 0))

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="上一步（调试）", command=lambda: self.engine.step(-1))
        self.context_menu.add_command(label="下一步（调试）", command=lambda: self.engine.step(1))
        self.context_menu.add_command(label="从启动轴重新开始", command=self.engine.reset)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="选择连招 / 设置", command=self.open_settings)
        self.context_menu.add_command(label="隐藏悬浮窗", command=self.hide_overlay)
        self.context_menu.add_command(label="退出", command=self.shutdown)

    def _select_initial_preset(self) -> None:
        preset_id = self.settings.get("preset_id")
        if preset_id in self.engine.presets:
            self.engine.select(preset_id)

    def _restart_monitors(self) -> None:
        if self.input_monitor:
            self.input_monitor.stop()
        if self.vision_monitor:
            self.vision_monitor.stop()
        enabled = lambda: (not self.settings.get("only_when_game_active", True)) or is_game_foreground(self.settings.get("game_titles", []))
        self.input_monitor = InputMonitor(
            self.settings["keymap"], self.engine.process,
            heavy_hold_ms=int(self.settings.get("heavy_hold_ms", 360)),
            poll_interval_ms=int(self.settings.get("poll_interval_ms", 8)),
            enabled=enabled,
        )
        self.input_monitor.start()
        self.vision_monitor = VisionMonitor(
            self.store.templates_dir, self.settings,
            expected_signal=lambda: self.engine.cue.vision_signal if self.engine.cue and self.settings.get("vision_enabled") else "",
            callback=lambda signal, score: self.events.put(("vision", (signal, score))),
        )
        if self.settings.get("vision_enabled"):
            self.vision_monitor.start()

    def _ui_loop(self) -> None:
        active = (not self.settings.get("only_when_game_active", True)) or is_game_foreground(self.settings.get("game_titles", []))
        self.engine.set_active(active)
        if self.settings.get("only_when_game_active", True) and not active and not self.force_visible:
            self.root.withdraw()
        else:
            self.root.deiconify()
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "view":
                self._render(payload)  # type: ignore[arg-type]
            elif kind == "vision":
                self.vision_signal, self.vision_score = payload  # type: ignore[misc]
            elif kind == "command":
                command = str(payload)
                if command == "show": self.show_overlay()
                elif command == "settings": self.open_settings()
                elif command == "reset": self.engine.reset()
                elif command == "quit": self.shutdown(); return
        self._render(self.engine.view())
        self.root.after(50, self._ui_loop)

    def _render(self, view: EngineView) -> None:
        if self.settings.get("sound_enabled") and self._last_rendered_index >= 0 and view.index != self._last_rendered_index:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass
        self._last_rendered_index = view.index
        team_name = view.preset_name.split(" · ", 1)[0]
        phase_text = "启动" if view.phase == "启动" else f"循环 {max(1, view.cycle_count)}"
        self.preset_label.config(text=team_name)
        self.phase_label.config(text=phase_text)
        self.progress_label.config(text=f"STEP {min(view.index + 1, view.total):02d} / {view.total:02d}   {view.total_elapsed_ms / 1000:05.1f}s")
        state_text, state_color = STATE_STYLE.get(view.timing_state, (view.timing_state, COLORS["muted"]))
        self.state_label.config(text=state_text, fg=state_color)
        self.state_dot.config(fg=state_color)
        cue = view.cue
        if cue is None:
            self.character_label.config(text="完成", fg=COLORS["green"])
            self.key_label.config(text="本轮完成", fg=COLORS["green"])
            self.segment_label.config(text="整套流程已完成")
            self.condition_label.config(text="本程序没有发送任何游戏输入。")
            self.next_label.config(text="")
            self.timing_label.config(text="")
            self._draw_timing(0, None, COLORS["green"])
            return
        self.character_label.config(text=cue.character, fg=COLORS["cyan"])
        key_size = 33 if len(cue.display_key) <= 2 else 27 if len(cue.display_key) == 3 else 21
        self.key_label.config(font=("Microsoft YaHei UI", key_size, "bold"))
        self.key_label.config(text=cue.display_key, fg=state_color if view.timing_state != "WAIT" else COLORS["text"])
        self.segment_label.config(text=cue.segment)
        quality = "" if cue.timing_quality == "已验证" else "  [参考时间窗]"
        self.condition_label.config(text=cue.condition + quality)
        self.message_label.config(text=view.message)
        self.next_label.config(text=f"随后  →  {view.next_cue.display_key}   ·   {view.next_cue.segment}" if view.next_cue else "随后  →  整轴完成")
        self.timing_label.config(text=f"{cue.earliest_ms}  /  {cue.recommended_ms}  /  {cue.latest_ms} ms")
        self._draw_timing(view.elapsed_ms, cue, state_color)
        if self.vision_signal:
            if self.vision_score < 0:
                text = "视觉：未校准"
            else:
                text = f"视觉：{self.vision_score:.0%}"
            self.vision_label.config(text=text, fg=COLORS["green"] if self.vision_score >= self.settings["vision"]["match_threshold"] else COLORS["muted"])
        else:
            self.vision_label.config(text="")

    def _draw_timing(self, elapsed_ms: int, cue, color: str) -> None:
        width = max(1, self.canvas.winfo_width())
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, width, 12, fill=COLORS["surface2"], outline="")
        if cue is None:
            self.canvas.create_rectangle(0, 0, width, 12, fill=color, outline="")
            return
        horizon = max(1, int(cue.latest_ms * 1.18))
        ready_x = int(width * cue.earliest_ms / horizon)
        late_x = int(width * cue.latest_ms / horizon)
        recommended_x = int(width * cue.recommended_ms / horizon)
        cursor_x = min(width - 2, int(width * elapsed_ms / horizon))
        self.canvas.create_rectangle(ready_x, 0, late_x, 12, fill="#173D34", outline="")
        self.canvas.create_line(recommended_x, 0, recommended_x, 12, fill=COLORS["green"], width=2)
        self.canvas.create_rectangle(max(0, cursor_x - 2), 0, cursor_x + 2, 12, fill=color, outline="")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin:
            self.root.geometry(f"+{event.x_root - self._drag_origin[0]}+{event.y_root - self._drag_origin[1]}")

    def _end_drag(self, _event: tk.Event) -> None:
        self.settings["overlay"]["x"] = self.root.winfo_x()
        self.settings["overlay"]["y"] = self.root.winfo_y()
        self.store.save(self.settings)
        self._drag_origin = None

    def _show_context_menu(self, event: tk.Event) -> None:
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def hide_overlay(self) -> None:
        self.force_visible = False
        self.root.withdraw()

    def show_overlay(self) -> None:
        self.force_visible = True
        self.root.deiconify()

    def open_settings(self) -> None:
        self.force_visible = True
        SettingsDialog(self)

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (64, 64), COLORS["bg"])
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=COLORS["green_dark"])
            draw.text((20, 17), "A", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("显示悬浮窗", lambda: self.events.put(("command", "show")), default=True),
                pystray.MenuItem("设置", lambda: self.events.put(("command", "settings"))),
                pystray.MenuItem("从启动轴重新开始", lambda: self.events.put(("command", "reset"))),
                pystray.MenuItem("退出", lambda: self.events.put(("command", "quit"))),
            )
            self._tray = pystray.Icon("WuwaComboAssistant", image, "鸣潮逐键教练", menu)
            threading.Thread(target=self._tray.run, name="tray", daemon=True).start()
        except Exception:
            self._tray = None

    def shutdown(self) -> None:
        if self.input_monitor:
            self.input_monitor.stop()
        if self.vision_monitor:
            self.vision_monitor.stop()
        if self._tray:
            self._tray.stop()
        self.store.save(self.settings)
        self.root.destroy()


class SettingsDialog:
    def __init__(self, app: OverlayApp) -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("鸣潮逐键教练设置")
        width, height = 760, 760
        x = max(0, (self.window.winfo_screenwidth() - width) // 2)
        y = max(0, (self.window.winfo_screenheight() - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.minsize(620, 600)
        self.window.configure(bg=COLORS["bg"])
        self.window.attributes("-topmost", True)
        self.values: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface"], foreground=COLORS["muted"], padding=(18, 10), borderwidth=0, font=("Microsoft YaHei UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface2"])], foreground=[("selected", COLORS["cyan"])])
        style.configure("TCombobox", fieldbackground=COLORS["surface2"], background=COLORS["surface3"], foreground=COLORS["text"], arrowcolor=COLORS["cyan"], bordercolor=COLORS["border"], lightcolor=COLORS["border"], darkcolor=COLORS["border"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface2"])], foreground=[("readonly", COLORS["text"])], selectbackground=[("readonly", COLORS["surface2"])], selectforeground=[("readonly", COLORS["text"])])
        heading = tk.Frame(self.window, bg=COLORS["surface"], height=66)
        heading.pack(side="top", fill="x")
        heading.pack_propagate(False)
        tk.Frame(heading, bg=COLORS["cyan"], width=4).pack(side="left", fill="y")
        title_box = tk.Frame(heading, bg=COLORS["surface"])
        title_box.pack(side="left", fill="y", padx=18)
        tk.Label(title_box, text="鸣潮逐键教练", bg=COLORS["surface"], fg=COLORS["text"], anchor="w", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(10, 0))
        tk.Label(title_box, text="队伍流程、输入监听与保守视觉校准", bg=COLORS["surface"], fg=COLORS["muted"], anchor="w", font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        notebook = ttk.Notebook(self.window)
        footer = tk.Frame(self.window, bg=COLORS["bg"])
        footer.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        tk.Button(footer, text="导出连招数据", command=self._export, bg=COLORS["surface2"], fg=COLORS["text"], relief="flat", padx=14, pady=8).pack(side="left")
        tk.Button(footer, text="取消", command=self.window.destroy, bg=COLORS["surface2"], fg=COLORS["text"], relief="flat", padx=18, pady=8).pack(side="right", padx=(8, 0))
        tk.Button(footer, text="保存并应用", command=self._save, bg=COLORS["green_dark"], fg="white", relief="flat", padx=18, pady=8).pack(side="right")
        notebook.pack(side="top", fill="both", expand=True, padx=16, pady=16)
        general = tk.Frame(notebook, bg=COLORS["bg"])
        keys = tk.Frame(notebook, bg=COLORS["bg"])
        calibration = tk.Frame(notebook, bg=COLORS["bg"])
        notebook.add(general, text="常规")
        notebook.add(keys, text="键位")
        notebook.add(calibration, text="视觉校准")
        self._build_general(general)
        self._build_keys(keys)
        self._build_calibration(calibration)

    def _label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=COLORS["bg"], fg=COLORS["text"], anchor="w", font=("Microsoft YaHei UI", 10))

    def _build_general(self, parent: tk.Frame) -> None:
        self._label(parent, "队伍流程").pack(fill="x", pady=(8, 4))
        startup_presets = [preset for preset in self.app.presets if preset.phase == "启动"]
        self.preset_name_to_id = {
            f"{preset.name.split(' · ', 1)[0]}  ·  启动后自动循环": preset.id
            for preset in startup_presets
        }
        current_id = self.app.engine.preset.id.replace("-cycle", "-startup")
        current_name = next(
            (name for name, preset_id in self.preset_name_to_id.items() if preset_id == current_id),
            next(iter(self.preset_name_to_id)),
        )
        self.values["preset_name"] = tk.StringVar(value=current_name)
        combo = ttk.Combobox(parent, state="readonly", textvariable=self.values["preset_name"], values=list(self.preset_name_to_id))
        combo.pack(fill="x", ipady=5)
        tk.Label(parent, text="启动轴只执行一次，完成后会自动进入循环轴并持续循环。实战无需额外热键。", bg=COLORS["bg"], fg=COLORS["muted"], justify="left", anchor="w").pack(fill="x", pady=(5, 10))
        self.values["only"] = tk.BooleanVar(value=self.app.settings["only_when_game_active"])
        self.values["vision"] = tk.BooleanVar(value=self.app.settings["vision_enabled"])
        self.values["sound"] = tk.BooleanVar(value=self.app.settings["sound_enabled"])
        for text, key in (("仅鸣潮位于前台时监听与显示", "only"), ("启用保守视觉信号", "vision"), ("识别推进时播放提示音", "sound")):
            tk.Checkbutton(parent, text=text, variable=self.values[key], bg=COLORS["bg"], fg=COLORS["text"], selectcolor=COLORS["surface2"], activebackground=COLORS["bg"], activeforeground=COLORS["text"]).pack(anchor="w", pady=5)
        self._label(parent, "游戏窗口标题（每行一个）").pack(fill="x", pady=(16, 4))
        self.title_text = tk.Text(parent, height=3, bg=COLORS["surface2"], fg=COLORS["text"], insertbackground="white", relief="flat")
        self.title_text.insert("1.0", "\n".join(self.app.settings["game_titles"]))
        self.title_text.pack(fill="x")
        windows = enumerate_window_titles()
        self.values["window_pick"] = tk.StringVar(value="")
        picker = ttk.Combobox(parent, values=windows, state="readonly", textvariable=self.values["window_pick"])
        picker.pack(fill="x", pady=(6, 2), ipady=4)
        tk.Button(parent, text="把所选窗口标题加入列表", command=self._add_window_title, bg=COLORS["surface2"], fg=COLORS["text"], relief="flat", pady=6).pack(fill="x")
        self._label(parent, "悬浮窗透明度").pack(fill="x", pady=(16, 4))
        self.values["opacity"] = tk.DoubleVar(value=float(self.app.settings["opacity"]))
        tk.Scale(parent, from_=0.55, to=1.0, resolution=0.01, orient="horizontal", variable=self.values["opacity"], bg=COLORS["bg"], fg=COLORS["text"], troughcolor=COLORS["surface2"], highlightthickness=0).pack(fill="x")

    def _build_keys(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="仅监听下列键位；不会拦截或发送输入。重击与普攻共用鼠标键，以按住时长区分。", bg=COLORS["bg"], fg=COLORS["muted"], wraplength=570, justify="left").pack(fill="x", pady=(8, 14))
        options = sorted(VK_CODES)
        labels = {"basic": "普攻", "heavy": "重击", "jump": "跳跃", "dodge": "闪避", "skill": "E技能", "echo": "声骸Q", "liberation": "共鸣解放R", "utility": "辅助F", "forward": "前进", "slot1": "1号位", "slot2": "2号位", "slot3": "3号位"}
        for row, (action, label) in enumerate(labels.items()):
            self._label(parent, label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 12))
            var = tk.StringVar(value=self.app.settings["keymap"][action])
            self.values[f"key:{action}"] = var
            ttk.Combobox(parent, values=options, state="readonly", textvariable=var, width=24).grid(row=row, column=1, sticky="ew", pady=5)
        parent.grid_columnconfigure(1, weight=1)
        self._label(parent, "重击判定阈值（毫秒）").grid(row=len(labels), column=0, sticky="w", pady=(16, 5))
        self.values["heavy_ms"] = tk.IntVar(value=int(self.app.settings["heavy_hold_ms"]))
        tk.Spinbox(parent, from_=200, to=1000, increment=20, textvariable=self.values["heavy_ms"], bg=COLORS["surface2"], fg=COLORS["text"], buttonbackground=COLORS["surface2"], relief="flat").grid(row=len(labels), column=1, sticky="ew", pady=(16, 5))

    def _build_calibration(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="把 ROI 对准稳定的角色/HUD区域。模板匹配只增强提示，不会阻止连招推进。", bg=COLORS["bg"], fg=COLORS["muted"], wraplength=570, justify="left").pack(fill="x", pady=(8, 14))
        grid = tk.Frame(parent, bg=COLORS["bg"])
        grid.pack(fill="x")
        roi = self.app.settings["vision"]["roi"]
        for col, key in enumerate(("left", "top", "width", "height")):
            self._label(grid, key).grid(row=0, column=col, sticky="w")
            var = tk.IntVar(value=int(roi[key]))
            self.values[f"roi:{key}"] = var
            tk.Entry(grid, textvariable=var, width=10, bg=COLORS["surface2"], fg=COLORS["text"], insertbackground="white", relief="flat").grid(row=1, column=col, padx=(0, 8), ipady=5)
        self._label(parent, "采集角色模板").pack(fill="x", pady=(18, 4))
        self.values["template_character"] = tk.StringVar(value=self.app.engine.preset.team[0])
        characters = sorted({c for preset in self.app.presets for c in preset.team})
        ttk.Combobox(parent, values=characters, state="readonly", textvariable=self.values["template_character"]).pack(fill="x", ipady=5)
        tk.Button(parent, text="保存当前 ROI 为角色模板", command=self._capture, bg=COLORS["surface2"], fg=COLORS["text"], relief="flat", pady=8).pack(fill="x", pady=10)
        self.calibration_status = tk.Label(parent, text="", bg=COLORS["bg"], fg=COLORS["muted"], anchor="w")
        self.calibration_status.pack(fill="x")

    def _apply_form(self) -> None:
        settings = self.app.settings
        settings["preset_id"] = self.preset_name_to_id[str(self.values["preset_name"].get())]
        settings["only_when_game_active"] = bool(self.values["only"].get())
        settings["vision_enabled"] = bool(self.values["vision"].get())
        settings["sound_enabled"] = bool(self.values["sound"].get())
        settings["opacity"] = float(self.values["opacity"].get())
        settings["game_titles"] = [line.strip() for line in self.title_text.get("1.0", "end").splitlines() if line.strip()]
        for action in settings["keymap"]:
            settings["keymap"][action] = str(self.values[f"key:{action}"].get())
        settings["heavy_hold_ms"] = int(self.values["heavy_ms"].get())
        for key in ("left", "top", "width", "height"):
            settings["vision"]["roi"][key] = int(self.values[f"roi:{key}"].get())

    def _save(self) -> None:
        self._apply_form()
        if not self.app.settings["game_titles"] and self.app.settings["only_when_game_active"]:
            messagebox.showerror("设置错误", "至少填写一个游戏窗口标题。", parent=self.window)
            return
        self.app.store.save(self.app.settings)
        self.app.settings["calibration_completed"] = True
        self.app.store.save(self.app.settings)
        self.app.root.attributes("-alpha", self.app.settings["opacity"])
        self.app.engine.select(self.app.settings["preset_id"])
        self.app._restart_monitors()
        self.window.destroy()

    def _add_window_title(self) -> None:
        selected = str(self.values["window_pick"].get()).strip()
        if not selected:
            return
        existing = [line.strip() for line in self.title_text.get("1.0", "end").splitlines() if line.strip()]
        if selected not in existing:
            self.title_text.insert("end", ("\n" if existing else "") + selected)

    def _capture(self) -> None:
        self._apply_form()
        signal = f"character:{self.values['template_character'].get()}"
        try:
            if not self.app.vision_monitor:
                raise RuntimeError("视觉模块未启动")
            path = self.app.vision_monitor.capture_template(signal)
            self.calibration_status.config(text=f"已保存：{path}", fg=COLORS["green"])
        except Exception as exc:
            self.calibration_status.config(text=f"采集失败：{exc}", fg=COLORS["red"])

    def _export(self) -> None:
        path = self.app.store.export_presets([preset.to_dict() for preset in self.app.presets])
        messagebox.showinfo("导出完成", f"连招数据已导出到：\n{path}", parent=self.window)
