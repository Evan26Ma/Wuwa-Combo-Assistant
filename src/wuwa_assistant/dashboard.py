from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw

from .engine import ComboEngine
from .foreground import is_game_foreground
from .input_monitor import InputMonitor
from .models import ComboPreset, Cue, EngineView
from .settings import SettingsStore
from .ui import SettingsDialog
from .vision import VisionMonitor


C = {
    "bg": "#080D19",
    "sidebar": "#0D1423",
    "panel": "#101827",
    "panel_alt": "#131D2E",
    "panel_hot": "#171A36",
    "border": "#2B374B",
    "border_hot": "#8A5CFF",
    "text": "#F4F6FC",
    "muted": "#99A5B9",
    "dim": "#68758A",
    "purple": "#8957FF",
    "purple2": "#5F3BC7",
    "blue": "#2788FF",
    "green": "#4BE18B",
    "gold": "#F5B84C",
    "red": "#FF586E",
}

STATE = {
    "WAIT": ("等待按键", C["blue"]),
    "READY": ("等待按键", C["purple"]),
    "PAUSED": ("已暂停", C["dim"]),
    "DONE": ("已完成", C["green"]),
}


def _label(parent: tk.Widget, text: str = "", *, size: int = 10, color: str = C["text"],
           weight: str = "normal", bg: str | None = None, **kwargs) -> tk.Label:
    return tk.Label(
        parent, text=text, bg=bg or str(parent.cget("bg")), fg=color,
        font=("Microsoft YaHei UI", size, weight), **kwargs,
    )


class DashboardApp:
    """Reference-inspired desktop dashboard backed by the read-only combo engine."""

    def __init__(self, root: tk.Tk, store: SettingsStore, settings: dict,
                 presets: tuple[ComboPreset, ...]) -> None:
        self.root = root
        self.store = store
        self.settings = settings
        self.presets = presets
        self.events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.engine = ComboEngine(self.presets, lambda view: self.events.put(("view", view)))
        self.input_monitor: InputMonitor | None = None
        self.vision_monitor: VisionMonitor | None = None
        self.vision_signal = ""
        self.vision_score = -1.0
        self.force_visible = True
        self._tray = None
        self._drag_origin: tuple[int, int] | None = None
        self._last_rendered_index = -1
        self._last_active: bool | None = None
        self._team_cards: dict[str, tk.Frame] = {}
        self._team_chips: dict[str, tk.Frame] = {}
        self._restore_geometry = ""

        self._build_window()
        self._select_initial_preset()
        self._restart_monitors()
        self._start_tray()
        if not self.settings.get("calibration_completed", False):
            self.root.after(450, self.open_settings)
        self.root.after(40, self._ui_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_overlay)

    # ---------- window and composition ----------
    def _build_window(self) -> None:
        self.root.title("鸣潮 · 连招教练")
        self.root.overrideredirect(True)
        self.root.configure(bg=C["border"])
        self.root.attributes("-alpha", float(self.settings.get("opacity", 0.98)))

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(1480, max(1080, sw - 96))
        height = min(930, max(700, sh - 96))
        x = max(16, (sw - width) // 2)
        y = max(16, (sh - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(1080, 700)

        shell = tk.Frame(self.root, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        shell.pack(fill="both", expand=True, padx=1, pady=1)
        self._build_header(shell)

        body = tk.Frame(shell, bg=C["bg"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        content = tk.Frame(body, bg=C["bg"])
        content.pack(side="left", fill="both", expand=True, padx=(22, 24), pady=(14, 18))
        self._build_team_row(content)
        self._build_workspace(content)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="上一步（调试）", command=lambda: self.engine.step(-1))
        self.context_menu.add_command(label="下一步（调试）", command=lambda: self.engine.step(1))
        self.context_menu.add_command(label="从启动轴重新开始", command=self.engine.reset)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="设置", command=self.open_settings)
        self.context_menu.add_command(label="隐藏到托盘", command=self.hide_overlay)
        self.context_menu.add_command(label="退出", command=self.shutdown)
        shell.bind("<Button-3>", self._show_context_menu)

    def _build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=C["bg"], height=106)
        header.pack(fill="x")
        header.pack_propagate(False)

        mark = tk.Canvas(header, width=36, height=36, bg=C["bg"], highlightthickness=0)
        mark.pack(side="left", padx=(28, 12), pady=(22, 0), anchor="n")
        mark.create_oval(3, 3, 33, 33, fill=C["purple"], outline="#BBA6FF", width=2)
        mark.create_text(18, 18, text="A", fill="white", font=("Segoe UI", 14, "bold"))

        title_box = tk.Frame(header, bg=C["bg"])
        title_box.pack(side="left", pady=(19, 0), anchor="n")
        _label(title_box, "鸣潮 · 连招教练", size=18, weight="bold", anchor="w").pack(anchor="w")
        _label(title_box, "逐键提示，不替代操作", size=10, color=C["muted"], anchor="w").pack(anchor="w", pady=(4, 0))

        controls = tk.Frame(header, bg=C["bg"])
        controls.pack(side="right", padx=20, pady=(18, 0), anchor="n")
        self.foreground_pill = tk.Label(
            controls, text="●  检测游戏状态", bg=C["panel_alt"], fg=C["muted"],
            padx=18, pady=9, font=("Microsoft YaHei UI", 10, "bold"),
            highlightthickness=1, highlightbackground=C["border"],
        )
        self.foreground_pill.pack(side="left", padx=(0, 12))
        self._header_button(controls, "设置", self.open_settings, width=7).pack(side="left", padx=(0, 18))
        self._header_button(controls, "—", self.hide_overlay, width=3).pack(side="left")
        self._header_button(controls, "□", self._toggle_maximize, width=3).pack(side="left")
        self._header_button(controls, "×", self.shutdown, width=3, danger=True).pack(side="left")

        for widget in (header, mark, title_box):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)

    def _header_button(self, parent: tk.Widget, text: str, command, *, width: int, danger: bool = False) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, width=width, relief="flat", bd=0,
            bg=C["bg"], fg=C["muted"], activebackground=C["red"] if danger else C["panel_alt"],
            activeforeground="white", font=("Microsoft YaHei UI", 9), cursor="hand2",
        )

    def _build_sidebar(self, parent: tk.Frame) -> None:
        side = tk.Frame(parent, bg=C["sidebar"], width=238)
        side.pack(side="left", fill="y", padx=(14, 0), pady=(8, 18))
        side.pack_propagate(False)

        nav = (
            ("◆", "选择教练", None, True),
            ("◇", "队伍选择", self._focus_teams, False),
            ("⌨", "键位设置", self.open_settings, False),
            ("◉", "提示设置", self.open_settings, False),
            ("▣", "画面识别", self.open_settings, False),
            ("?", "使用帮助", self._show_help, False),
            ("i", "关于", self._show_about, False),
        )
        for icon, text, command, active in nav:
            row = tk.Frame(side, bg=C["panel_hot"] if active else C["sidebar"], height=66, cursor="hand2")
            row.pack(fill="x", pady=(18 if text == "选择教练" else 0, 0))
            row.pack_propagate(False)
            if active:
                tk.Frame(row, bg=C["purple"], width=4).pack(side="left", fill="y")
            _label(row, icon, size=14, color=C["purple"] if active else C["muted"], width=3).pack(side="left", padx=(13, 1))
            _label(row, text, size=11, weight="bold" if active else "normal", color=C["text"] if active else "#C1C9D8", anchor="w").pack(side="left", fill="x", expand=True)
            if command:
                for widget in (row, *row.winfo_children()):
                    widget.bind("<Button-1>", lambda _e, fn=command: fn())

        status = tk.Frame(side, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
        status.pack(side="bottom", fill="x", padx=14, pady=14)
        _label(status, "●  运行中", size=10, color=C["green"], weight="bold", anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        _label(status, "v1.1.0  |  完全离线", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=14)
        _label(status, "不上传任何数据", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=14, pady=(2, 12))
        spark = tk.Canvas(status, height=22, bg=C["panel_alt"], highlightthickness=0)
        spark.pack(fill="x", padx=12, pady=(0, 8))
        spark.create_line(0, 17, 30, 17, 48, 14, 70, 17, 88, 8, 104, 12, 122, 3, 142, 9, fill=C["blue"], width=1)

    def _build_team_row(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=C["bg"], height=98)
        row.pack(fill="x")
        row.pack_propagate(False)
        startups = [p for p in self.presets if p.phase == "启动"]
        for preset in startups:
            card = tk.Frame(row, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"], cursor="hand2")
            card.pack(side="left", fill="both", expand=True, padx=(0, 18 if preset is startups[0] else 0))
            avatar = tk.Frame(card, bg=C["panel_alt"], width=132, height=58, highlightthickness=1, highlightbackground=C["border"])
            avatar.pack(side="left", padx=14, pady=18)
            avatar.pack_propagate(False)
            _label(avatar, " · ".join(preset.team), size=8, color="#D8D0FF", weight="bold", wraplength=120, justify="center").pack(fill="both", expand=True, padx=5, pady=5)
            text_box = tk.Frame(card, bg=C["panel"])
            text_box.pack(side="left", fill="y", pady=16)
            _label(text_box, preset.name.split(" · ", 1)[0], size=13, weight="bold", anchor="w").pack(anchor="w")
            _label(text_box, "启动轴  →  自动循环", size=10, color="#D8DDEC", anchor="w").pack(anchor="w", pady=(5, 0))
            self._team_cards[preset.id] = card
            self._team_chips[preset.id] = avatar
            for widget in (card, avatar, *avatar.winfo_children(), text_box, *text_box.winfo_children()):
                widget.bind("<Button-1>", lambda _e, pid=preset.id: self._choose_team(pid))

    def _build_workspace(self, parent: tk.Frame) -> None:
        grid = tk.Frame(parent, bg=C["bg"])
        grid.pack(fill="both", expand=True, pady=(18, 0))
        grid.grid_columnconfigure(0, weight=7, uniform="workspace")
        grid.grid_columnconfigure(1, weight=4, uniform="workspace")
        grid.grid_rowconfigure(0, weight=1)

        left = tk.Frame(grid, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        right = tk.Frame(grid, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nsew")
        self._build_next_action(left)
        self._build_progress(left)
        self._build_preview(right)
        self._build_recognition(right)
        self._build_cycle(right)
        self._build_tips(right)

    def _card(self, parent: tk.Widget, *, pady: tuple[int, int] = (0, 14)) -> tk.Frame:
        frame = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        frame.pack(fill="both", expand=True, pady=pady)
        return frame

    def _build_next_action(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        _label(card, "下一步操作", size=13, weight="bold", anchor="w").pack(fill="x", padx=20, pady=(17, 0))
        self.action_rule = tk.Canvas(card, height=3, bg=C["panel"], highlightthickness=0)
        self.action_rule.pack(fill="x", padx=20, pady=(14, 0))
        self.action_rule.bind("<Configure>", self._draw_action_rule)
        self.state_label = _label(card, "●  等待输入", size=11, color=C["purple"], weight="bold")
        self.state_label.pack(pady=(20, 6))
        self.key_box = tk.Frame(card, bg=C["panel_alt"], highlightthickness=2, highlightbackground=C["border"])
        self.key_box.pack(pady=(4, 13))
        self.key_label = _label(self.key_box, "—", size=38, weight="bold", padx=20, pady=9)
        self.key_label.pack()
        self.condition_title = _label(card, "等待第一个动作", size=20, weight="bold")
        self.condition_title.pack(pady=(5, 7))
        self.condition_label = _label(card, "程序会根据你的实际按键自动推进", size=11, color="#C7CFDD", wraplength=620, justify="center")
        self.condition_label.pack(padx=26, pady=(0, 10))
        self.segment_label = _label(card, "", size=9, color=C["purple"])
        self.segment_label.pack(pady=(0, 14))

    def _build_progress(self, parent: tk.Frame) -> None:
        card = self._card(parent, pady=(0, 0))
        head = tk.Frame(card, bg=C["panel"])
        head.pack(fill="x", padx=20, pady=(16, 8))
        _label(head, "当前进度", size=12, weight="bold").pack(side="left")
        self.phase_label = _label(head, "启动轴（仅一次）", size=10, color=C["muted"])
        self.phase_label.pack(side="right")
        self.sequence_canvas = tk.Canvas(card, height=104, bg=C["panel"], highlightthickness=0)
        self.sequence_canvas.pack(fill="x", padx=22)
        self.sequence_canvas.bind("<Configure>", lambda _e: self._draw_sequence(self.engine.view()))
        legend = tk.Frame(card, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
        legend.pack(fill="x", padx=20, pady=(2, 18))
        for color, text in ((C["purple"], "当前按键"), (C["dim"], "待执行"), (C["green"], "已完成")):
            _label(legend, f"●  {text}", size=9, color=color).pack(side="left", expand=True, pady=10)

    def _build_preview(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        _label(card, "后续按键", size=12, weight="bold", anchor="w").pack(fill="x", padx=20, pady=(17, 8))
        self.preview_labels: list[tk.Label] = []
        preview_row = tk.Frame(card, bg=C["panel"])
        preview_row.pack(fill="both", expand=True, padx=20, pady=(5, 18))
        for index in range(3):
            item = _label(
                preview_row, "—", size=12, color=C["muted"], weight="bold",
                bg=C["panel_alt"], padx=12, pady=12,
                highlightthickness=1, highlightbackground=C["border"],
            )
            item.pack(side="left", fill="both", expand=True, padx=(0, 8 if index < 2 else 0))
            self.preview_labels.append(item)

    def _build_recognition(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        _label(card, "识别状态", size=12, weight="bold", anchor="w").pack(fill="x", padx=20, pady=(16, 8))
        self.recognition_rows: list[tuple[tk.Label, tk.Label]] = []
        for text in ("按键序列匹配", "长按输入判定", "锚点同步状态"):
            row = tk.Frame(card, bg=C["panel"])
            row.pack(fill="x", padx=20, pady=5)
            name = _label(row, text, size=10, color="#D2D8E4", anchor="w")
            name.pack(side="left", fill="x", expand=True)
            value = _label(row, "●", size=12, color=C["dim"])
            value.pack(side="right")
            self.recognition_rows.append((name, value))
        tk.Frame(card, height=9, bg=C["panel"]).pack()

    def _build_cycle(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        row = tk.Frame(card, bg=C["panel"])
        row.pack(fill="x", padx=20, pady=15)
        box = tk.Frame(row, bg=C["panel"])
        box.pack(side="left", fill="x", expand=True)
        _label(box, "当前循环", size=11, weight="bold", anchor="w").pack(anchor="w")
        self.cycle_label = _label(box, "启动阶段", size=10, color="#D9D0FF", anchor="w")
        self.cycle_label.pack(anchor="w", pady=(4, 0))
        tk.Button(
            row, text="重置轮次", command=self.engine.reset, bg=C["panel_alt"], fg=C["text"],
            activebackground=C["purple2"], activeforeground="white", relief="flat", bd=0,
            padx=16, pady=9, cursor="hand2", font=("Microsoft YaHei UI", 9),
        ).pack(side="right")

    def _build_tips(self, parent: tk.Frame) -> None:
        card = self._card(parent, pady=(0, 0))
        _label(card, "使用提示", size=10, weight="bold", anchor="w").pack(fill="x", padx=18, pady=(10, 3))
        for text in ("启动轴只执行一次，完成后自动进入循环", "错键不会停止，会等待可靠锚点恢复", "长按不足会提示，请注意按住时长"):
            _label(card, f"✓  {text}", size=8, color=C["green"], anchor="w").pack(fill="x", padx=18, pady=2)
        tk.Frame(card, bg=C["panel"], height=5).pack()

    # ---------- state and rendering ----------
    def _select_initial_preset(self) -> None:
        preset_id = str(self.settings.get("preset_id", "kaxiaqian-startup"))
        if preset_id in self.engine.presets:
            self.engine.select(preset_id)

    def _choose_team(self, preset_id: str) -> None:
        self.settings["preset_id"] = preset_id
        self.store.save(self.settings)
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
            poll_interval_ms=int(self.settings.get("poll_interval_ms", 8)), enabled=enabled,
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
        self._last_active = active
        unrestricted = not self.settings.get("only_when_game_active", True)
        self.foreground_pill.config(
            text="●  全局监听已启用" if unrestricted else "●  鸣潮已在前台" if active else "●  等待鸣潮前台",
            fg=C["green"] if active else C["muted"],
        )
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "vision":
                self.vision_signal, self.vision_score = payload  # type: ignore[misc]
            elif kind == "command":
                command = str(payload)
                if command == "show": self.show_overlay()
                elif command == "settings": self.open_settings()
                elif command == "reset": self.engine.reset()
                elif command == "quit": self.shutdown(); return
        self._render(self.engine.view())
        self.root.after(80, self._ui_loop)

    def _render(self, view: EngineView) -> None:
        if self.settings.get("sound_enabled") and self._last_rendered_index >= 0 and view.index != self._last_rendered_index:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                pass
        self._last_rendered_index = view.index
        self._style_team_cards()
        cue = view.cue
        state_text, state_color = STATE.get(view.timing_state, (view.timing_state, C["muted"]))
        self.state_label.config(text=f"●  {state_text}", fg=state_color)
        self.key_box.config(highlightbackground=state_color)
        if cue is None:
            self.key_label.config(text="✓", fg=C["green"], font=("Segoe UI", 38, "bold"))
            self.condition_title.config(text="本轮完成")
            self.condition_label.config(text="等待重置或选择另一支队伍")
            self.segment_label.config(text="")
        else:
            size = 38 if len(cue.display_key) <= 2 else 29 if len(cue.display_key) == 3 else 23
            self.key_label.config(text=cue.display_key, fg=C["text"], font=("Microsoft YaHei UI", size, "bold"))
            self.condition_title.config(text=cue.segment)
            self.condition_label.config(text=f"当前角色：{cue.character}  ·  识别后自动进入下一步")
            self.segment_label.config(text=f"第 {view.index + 1} / {view.total} 步")
        self.phase_label.config(text="启动轴（仅一次）" if view.phase == "启动" else f"自动循环中  ·  第 {max(1, view.cycle_count)} 轮")
        self.cycle_label.config(text="启动阶段" if view.phase == "启动" else f"第 {max(1, view.cycle_count)} 轮 / ∞")
        self.recognition_rows[0][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        self.recognition_rows[1][1].config(fg=C["green"] if cue and cue.hold_ms else C["dim"])
        self.recognition_rows[2][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        self._update_preview(view)
        self._draw_sequence(view)

    def _style_team_cards(self) -> None:
        selected = self.engine.preset.id.replace("-cycle", "-startup")
        for preset_id, card in self._team_cards.items():
            active = preset_id == selected
            card.config(bg=C["panel_hot"] if active else C["panel"], highlightbackground=C["border_hot"] if active else C["border"])
            for widget in card.winfo_children():
                try:
                    widget.config(bg=C["panel_hot"] if active else C["panel"])
                    for child in widget.winfo_children():
                        child.config(bg=C["panel_hot"] if active else C["panel"])
                except tk.TclError:
                    pass
            chip = self._team_chips[preset_id]
            chip.config(bg=C["panel_alt"], highlightbackground=C["border_hot"] if active else C["border"])
            for child in chip.winfo_children():
                child.config(bg=C["panel_alt"])

    def _draw_action_rule(self, _event=None) -> None:
        c = self.action_rule
        w = max(1, c.winfo_width())
        c.delete("all")
        c.create_line(0, 1, w, 1, fill=C["border"])
        c.create_line(w * .36, 1, w * .64, 1, fill=C["purple"], width=2)
        c.create_oval(w / 2 - 3, -1, w / 2 + 3, 5, fill="#C9B8FF", outline="")

    def _update_preview(self, view: EngineView) -> None:
        preset = self.engine.preset
        upcoming = list(preset.cues[view.index + 1:view.index + 4])
        if len(upcoming) < 3 and preset.next_preset_id:
            upcoming.extend(self.engine.presets[preset.next_preset_id].cues[:3 - len(upcoming)])
        elif len(upcoming) < 3 and preset.loops:
            upcoming.extend(preset.cues[:3 - len(upcoming)])
        for index, label in enumerate(self.preview_labels):
            if index < len(upcoming):
                item = upcoming[index]
                label.config(text=f"{item.display_key}\n{item.character}", fg=C["text"])
            else:
                label.config(text="—", fg=C["dim"])

    def _draw_sequence(self, view: EngineView) -> None:
        canvas = self.sequence_canvas
        w = max(1, canvas.winfo_width())
        canvas.delete("all")
        preset = self.engine.preset
        start = max(0, view.index - 3)
        cues = list(preset.cues[start:start + 8])
        if not cues:
            return
        gap = min(76, max(52, (w - 56) / max(1, len(cues) - 1)))
        total_w = gap * (len(cues) - 1)
        x0 = (w - total_w) / 2
        y = 49
        for idx, cue in enumerate(cues):
            x = x0 + idx * gap
            absolute = start + idx
            if idx:
                canvas.create_line(x - gap + 22, y, x - 22, y, fill=C["purple2"] if absolute <= view.index else C["border"], width=3)
                canvas.create_polygon(x - 24, y - 5, x - 16, y, x - 24, y + 5, fill=C["purple2"] if absolute <= view.index else C["border"], outline="")
            completed = absolute < view.index
            current = absolute == view.index
            fill = C["purple2"] if completed else C["panel_alt"]
            outline = C["purple"] if current else C["border"]
            radius = 26 if current else 22
            if current:
                canvas.create_oval(x - radius - 5, y - radius - 5, x + radius + 5, y + radius + 5, outline="#3E2C75", width=2)
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline=outline, width=3 if current else 2)
            text = "✓" if completed else cue.display_key[:2]
            canvas.create_text(x, y, text=text, fill="white" if completed or current else C["muted"], font=("Microsoft YaHei UI", 12, "bold"))
        canvas.create_text(w - 8, y, text="•••", anchor="e", fill=C["muted"], font=("Segoe UI", 12))

    # ---------- interactions ----------
    def _focus_teams(self) -> None:
        self.root.lift()

    def _show_help(self) -> None:
        messagebox.showinfo("使用帮助", "选择队伍后正常操作游戏即可。程序只读取按键状态，正确输入会自动推进；错位时等待可靠锚点恢复。", parent=self.root)

    def _show_about(self) -> None:
        messagebox.showinfo("关于", "鸣潮连招辅助 v1.1.0\n完全离线 · 不拦截 · 不模拟 · 不修改游戏", parent=self.root)

    def open_settings(self) -> None:
        self.force_visible = True
        SettingsDialog(self)

    def _toggle_maximize(self) -> None:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if self._restore_geometry:
            self.root.geometry(self._restore_geometry)
            self._restore_geometry = ""
        else:
            self._restore_geometry = self.root.geometry()
            self.root.geometry(f"{sw}x{sh}+0+0")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin:
            self.root.geometry(f"+{event.x_root - self._drag_origin[0]}+{event.y_root - self._drag_origin[1]}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._drag_origin = None

    def _show_context_menu(self, event: tk.Event) -> None:
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def hide_overlay(self) -> None:
        self.root.withdraw()

    def show_overlay(self) -> None:
        self.force_visible = True
        self.root.deiconify()
        self.root.lift()

    def _start_tray(self) -> None:
        try:
            import pystray
            image = Image.new("RGB", (64, 64), C["bg"])
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill=C["purple2"])
            draw.text((22, 17), "A", fill="white")
            menu = pystray.Menu(
                pystray.MenuItem("显示控制台", lambda: self.events.put(("command", "show")), default=True),
                pystray.MenuItem("设置", lambda: self.events.put(("command", "settings"))),
                pystray.MenuItem("从启动轴重新开始", lambda: self.events.put(("command", "reset"))),
                pystray.MenuItem("退出", lambda: self.events.put(("command", "quit"))),
            )
            self._tray = pystray.Icon("WuwaComboAssistant", image, "鸣潮连招辅助", menu)
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
