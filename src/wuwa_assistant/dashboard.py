from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from .engine import ComboEngine
from .foreground import enumerate_window_titles, is_game_foreground
from .input_monitor import InputMonitor, VK_CODES
from .models import ComboPreset, Cue, EngineView
from .settings import SettingsStore
from .vision import (
    OKWW_SIGNAL_CATEGORIES,
    StateVisionMonitor,
    VisionMonitor,
    bundled_portrait_paths,
    import_okww_portraits,
    import_okww_templates,
)


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
        self.state_vision_monitor: StateVisionMonitor | None = None
        self.vision_signal = ""
        self.vision_score = -1.0
        self.state_vision_scores: dict[str, tuple[float, bool]] = {}
        self.force_visible = True
        self._tray = None
        self._drag_origin: tuple[int, int] | None = None
        self._overlay_drag_origin: tuple[int, int] | None = None
        self._last_rendered_index = -1
        self._last_active: bool | None = None
        self._team_cards: dict[str, tk.Frame] = {}
        self._team_chips: dict[str, tk.Frame] = {}
        self._team_page_cards: dict[str, tk.Frame] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.nav_rows: dict[str, tuple[tk.Frame, tk.Frame, tk.Label, tk.Label]] = {}
        self.current_page = "coach"
        self._restore_geometry = ""
        self.character_asset_paths: dict[str, Path] = {}
        self.character_photos: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self._portrait_labels: list[tuple[tk.Label, str, int]] = []

        self._auto_import_okww_portraits()
        self._build_window()
        self._build_battle_overlay()
        self._auto_import_okww_templates()
        self._select_initial_preset()
        self._restart_monitors()
        self._start_tray()
        if not self.settings.get("calibration_completed", False):
            self.root.after(450, lambda: self._show_page("keys"))
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
        self.page_host = tk.Frame(body, bg=C["bg"])
        self.page_host.pack(side="left", fill="both", expand=True, padx=(22, 24), pady=(14, 18))
        self._build_pages()
        self._show_page("coach")

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="上一步（调试）", command=lambda: self.engine.step(-1))
        self.context_menu.add_command(label="下一步（调试）", command=lambda: self.engine.step(1))
        self.context_menu.add_command(label="从启动轴重新开始", command=self.engine.reset)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="查看完整按键轴", command=self._open_full_axis_event)
        self.context_menu.add_command(label="显示 / 隐藏战斗悬浮提示", command=self._toggle_battle_overlay_enabled)
        self.context_menu.add_command(label="设置", command=self.open_settings)
        self.context_menu.add_command(label="隐藏到托盘", command=self.hide_overlay)
        self.context_menu.add_command(label="退出", command=self.shutdown)
        shell.bind("<Button-3>", self._show_context_menu)

    def _build_battle_overlay(self) -> None:
        """Create a transparent, non-activating combat-only key prompt."""
        transparent = "#010203"
        self.battle_overlay = tk.Toplevel(self.root)
        self.battle_overlay.title("鸣潮逐键提示")
        self.battle_overlay.overrideredirect(True)
        self.battle_overlay.attributes("-topmost", True)
        self.battle_overlay.configure(bg=transparent)
        try:
            self.battle_overlay.attributes("-transparentcolor", transparent)
        except tk.TclError:
            self.battle_overlay.attributes("-alpha", .92)

        width, height = 330, 116
        overlay_settings = self.settings.get("overlay", {})
        x = overlay_settings.get("x")
        if x is None:
            x = self.root.winfo_screenwidth() - width - 48
        y = int(overlay_settings.get("y", 72))
        self.battle_overlay.geometry(f"{width}x{height}+{max(0, int(x))}+{max(0, y)}")

        self.float_canvas = tk.Canvas(
            self.battle_overlay, width=width, height=height, bg=transparent,
            highlightthickness=0, bd=0, cursor="fleur",
        )
        self.float_canvas.pack(fill="both", expand=True)
        self.float_canvas.bind("<ButtonPress-1>", self._start_overlay_drag)
        self.float_canvas.bind("<B1-Motion>", self._drag_overlay)
        self.float_canvas.bind("<ButtonRelease-1>", self._end_overlay_drag)
        self.float_canvas.bind("<Button-3>", self._show_context_menu)
        self.battle_overlay.update_idletasks()
        self._make_overlay_no_activate()
        self.battle_overlay.withdraw()

    def _make_overlay_no_activate(self) -> None:
        try:
            import ctypes
            hwnd = self.battle_overlay.winfo_id()
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            style = get_style(hwnd, -20)
            set_style(hwnd, -20, style | 0x08000000 | 0x00000080)
        except Exception:
            pass

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
            ("coach", "◆", "选择教练"),
            ("axis", "≡", "完整按键轴"),
            ("teams", "◇", "队伍选择"),
            ("keys", "⌨", "键位设置"),
            ("prompts", "◉", "提示设置"),
            ("vision", "▣", "画面识别"),
            ("help", "?", "使用帮助"),
            ("about", "i", "关于"),
        )
        for page_id, icon, text in nav:
            row = tk.Frame(side, bg=C["sidebar"], height=58, cursor="hand2")
            row.pack(fill="x", pady=(10 if text == "选择教练" else 0, 0))
            row.pack_propagate(False)
            accent = tk.Frame(row, bg=C["sidebar"], width=4)
            accent.pack(side="left", fill="y")
            icon_label = _label(row, icon, size=14, color=C["muted"], width=3)
            icon_label.pack(side="left", padx=(13, 1))
            text_label = _label(row, text, size=11, color="#C1C9D8", anchor="w")
            text_label.pack(side="left", fill="x", expand=True)
            self.nav_rows[page_id] = (row, accent, icon_label, text_label)
            for widget in (row, accent, icon_label, text_label):
                widget.bind("<Button-1>", lambda _e, pid=page_id: self._show_page(pid))

        status = tk.Frame(side, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
        status.pack(side="bottom", fill="x", padx=14, pady=14)
        _label(status, "●  运行中", size=10, color=C["green"], weight="bold", anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        _label(status, "v1.2.0  |  完全离线", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=14)
        _label(status, "不上传任何数据", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=14, pady=(2, 12))
        spark = tk.Canvas(status, height=22, bg=C["panel_alt"], highlightthickness=0)
        spark.pack(fill="x", padx=12, pady=(0, 8))
        spark.create_line(0, 17, 30, 17, 48, 14, 70, 17, 88, 8, 104, 12, 122, 3, 142, 9, fill=C["blue"], width=1)

    def _build_pages(self) -> None:
        builders = (
            ("coach", self._build_coach_page),
            ("axis", self._build_axis_page),
            ("teams", self._build_teams_page),
            ("keys", self._build_keys_page),
            ("prompts", self._build_prompts_page),
            ("vision", self._build_vision_page),
            ("help", self._build_help_page),
            ("about", self._build_about_page),
        )
        for page_id, builder in builders:
            page = tk.Frame(self.page_host, bg=C["bg"])
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[page_id] = page
            builder(page)

    def _build_coach_page(self, parent: tk.Frame) -> None:
        self._build_team_row(parent)
        self._build_workspace(parent)

    def _build_axis_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "完整按键轴", "查看当前队伍的全部启动操作和后续循环操作")
        head = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        head.pack(fill="x", pady=(0, 14))
        self.axis_team_label = _label(head, "", size=12, weight="bold", anchor="w")
        self.axis_team_label.pack(side="left", padx=20, pady=14)
        _label(head, "A = 左键普攻   ·   Z = 长按左键重击", size=9, color=C["muted"]).pack(side="right", padx=20)

        columns = tk.Frame(parent, bg=C["bg"])
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure(0, weight=1, uniform="axis")
        columns.grid_columnconfigure(1, weight=1, uniform="axis")
        columns.grid_rowconfigure(0, weight=1)
        self.axis_texts: list[tk.Text] = []
        self.axis_titles: list[tk.Label] = []
        for column, title in enumerate(("启动轴（仅一次）", "循环轴（自动重复）")):
            card = tk.Frame(columns, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
            title_label = _label(card, title, size=12, weight="bold", anchor="w")
            title_label.pack(fill="x", padx=18, pady=(16, 10))
            self.axis_titles.append(title_label)
            holder = tk.Frame(card, bg=C["panel"])
            holder.pack(fill="both", expand=True, padx=18, pady=(0, 18))
            scrollbar = tk.Scrollbar(holder, orient="vertical", bg=C["panel_alt"], troughcolor=C["panel"], activebackground=C["purple"])
            scrollbar.pack(side="right", fill="y")
            text_widget = tk.Text(
                holder, bg=C["panel_alt"], fg=C["text"], relief="flat", bd=0,
                highlightthickness=1, highlightbackground=C["border"], padx=14, pady=12,
                font=("Microsoft YaHei UI", 10), wrap="word", spacing1=2, spacing3=3,
                yscrollcommand=scrollbar.set, cursor="arrow",
            )
            text_widget.pack(side="left", fill="both", expand=True)
            text_widget.tag_configure("segment", foreground="#BFAAFF", font=("Microsoft YaHei UI", 10, "bold"), spacing1=10, spacing3=4)
            text_widget.tag_configure("step", foreground=C["dim"], font=("Segoe UI", 9, "normal"))
            text_widget.tag_configure("key", foreground=C["text"], font=("Microsoft YaHei UI", 11, "bold"))
            scrollbar.config(command=text_widget.yview)
            self.axis_texts.append(text_widget)
        self._refresh_axis_page()

    def _page_header(self, parent: tk.Frame, title: str, subtitle: str) -> None:
        box = tk.Frame(parent, bg=C["bg"], height=84)
        box.pack(fill="x")
        box.pack_propagate(False)
        _label(box, title, size=20, weight="bold", anchor="w").pack(fill="x", pady=(4, 4))
        _label(box, subtitle, size=10, color=C["muted"], anchor="w").pack(fill="x")

    def _section(self, parent: tk.Widget, *, pady: tuple[int, int] = (0, 16)) -> tk.Frame:
        frame = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        frame.pack(fill="x", pady=pady)
        return frame

    def _button(self, parent: tk.Widget, text: str, command, *, primary: bool = False) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
            bg=C["purple2"] if primary else C["panel_alt"], fg="white" if primary else C["text"],
            activebackground=C["purple"], activeforeground="white", padx=18, pady=9,
            font=("Microsoft YaHei UI", 9, "bold" if primary else "normal"),
        )

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
            self._build_character_strip(avatar, preset.team, size=38)
            text_box = tk.Frame(card, bg=C["panel"])
            text_box.pack(side="left", fill="y", pady=16)
            _label(text_box, preset.name.split(" · ", 1)[0], size=13, weight="bold", anchor="w").pack(anchor="w")
            _label(text_box, "启动轴  →  自动循环", size=10, color="#D8DDEC", anchor="w").pack(anchor="w", pady=(5, 0))
            self._team_cards[preset.id] = card
            self._team_chips[preset.id] = avatar
            self._bind_tree(card, "<Button-1>", lambda _e, pid=preset.id: self._choose_team(pid))

    def _character_photo(self, name: str, size: int) -> ImageTk.PhotoImage | None:
        key = (name, size)
        if key in self.character_photos:
            return self.character_photos[key]
        path = self.character_asset_paths.get(name)
        if not path or not path.exists():
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((1, 1, size - 2, size - 2), fill=255)
            image.putalpha(mask)
            photo = ImageTk.PhotoImage(image)
        except OSError:
            return None
        self.character_photos[key] = photo
        return photo

    def _build_character_strip(self, parent: tk.Widget, team: tuple[str, ...], *, size: int,
                               show_names: bool = False) -> tk.Frame:
        strip = tk.Frame(parent, bg=str(parent.cget("bg")))
        strip.pack(expand=True)
        for name in team:
            item = tk.Frame(strip, bg=str(parent.cget("bg")))
            item.pack(side="left", padx=2)
            photo = self._character_photo(name, size)
            portrait = tk.Label(
                item, image=photo or "", text="" if photo else name[:1], compound="center",
                bg=str(parent.cget("bg")) if photo else C["panel_hot"], fg="#D8D0FF", bd=0,
                font=("Microsoft YaHei UI", max(10, size // 3), "bold"),
                width=size, height=size, highlightthickness=0 if photo else 1,
                highlightbackground=C["border_hot"],
            )
            portrait.pack()
            self._portrait_labels.append((portrait, name, size))
            if show_names:
                _label(item, name, size=9, color="#D8DDEC").pack(pady=(6, 0))
        return strip

    def _refresh_character_portraits(self) -> None:
        self.character_photos.clear()
        for label, name, size in self._portrait_labels:
            photo = self._character_photo(name, size)
            label.config(
                image=photo or "", text="" if photo else name[:1],
                bg=str(label.master.cget("bg")) if photo else C["panel_hot"],
                highlightthickness=0 if photo else 1,
            )

    @staticmethod
    def _bind_tree(widget: tk.Widget, event: str, callback) -> None:
        widget.bind(event, callback)
        for child in widget.winfo_children():
            DashboardApp._bind_tree(child, event, callback)

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
        for text in ("按键序列匹配", "长按输入判定", "锚点同步状态", "角色 HUD 增强"):
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

    # ---------- integrated pages ----------
    def _build_teams_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "队伍选择", "选择启动轴即可；完成后程序会自动接入对应循环轴")
        grid = tk.Frame(parent, bg=C["bg"])
        grid.pack(fill="both", expand=True)
        startups = [preset for preset in self.presets if preset.phase == "启动"]
        for column, preset in enumerate(startups):
            grid.grid_columnconfigure(column, weight=1, uniform="teams")
            card = tk.Frame(grid, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"], cursor="hand2")
            card.grid(row=0, column=column, sticky="nsew", padx=(0, 10) if column == 0 else (10, 0), pady=(0, 18))
            self._team_page_cards[preset.id] = card
            portraits = tk.Frame(card, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
            portraits.pack(fill="x", padx=26, pady=(26, 18), ipady=14)
            self._build_character_strip(portraits, preset.team, size=68, show_names=True)
            _label(card, preset.name.split(" · ", 1)[0], size=24, weight="bold").pack(anchor="w", padx=26)
            _label(card, "启动轴完成后自动循环", size=11, color=C["green"]).pack(anchor="w", padx=26, pady=(8, 24))
            details = tk.Frame(card, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
            details.pack(fill="x", padx=26, pady=(0, 20))
            cycle = self.engine.presets.get(preset.next_preset_id or "")
            _label(details, f"启动轴  {len(preset.cues)} 步", size=10, anchor="w").pack(fill="x", padx=16, pady=(14, 4))
            _label(details, f"循环轴  {len(cycle.cues) if cycle else 0} 步 / 无限循环", size=10, color=C["muted"], anchor="w").pack(fill="x", padx=16, pady=(0, 14))
            _label(card, "按键概览", size=10, color=C["muted"], anchor="w").pack(fill="x", padx=26)
            axis = "  →  ".join(cue.display_key for cue in preset.cues[:10])
            _label(card, axis + ("  …" if len(preset.cues) > 10 else ""), size=11, wraplength=470, justify="left", anchor="w").pack(fill="x", padx=26, pady=(8, 28))
            choose = self._button(card, "使用这套连招", lambda pid=preset.id: self._select_team_from_page(pid), primary=True)
            choose.pack(anchor="w", padx=26, pady=(0, 28))
            self._bind_tree(card, "<Button-1>", lambda _e, pid=preset.id: self._select_team_from_page(pid))

    def _build_keys_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "键位设置", "录入你的游戏键位；程序只读取状态，不会拦截或发送按键")
        card = self._section(parent)
        _label(card, "战斗键位", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(20, 4))
        _label(card, "点击下拉框选择当前在鸣潮中使用的键位", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=22, pady=(0, 14))
        fields = tk.Frame(card, bg=C["panel"])
        fields.pack(fill="x", padx=22)
        actions = (
            ("basic", "普攻"), ("heavy", "重击（与普攻相同时自动识别长按）"),
            ("skill", "共鸣技能 E"), ("echo", "声骸技能 Q"),
            ("liberation", "共鸣解放 R"), ("utility", "交互 / 钩锁 F"),
            ("jump", "跳跃"), ("dodge", "闪避"),
            ("forward", "前进"), ("slot1", "切人 1"),
            ("slot2", "切人 2"), ("slot3", "切人 3"),
        )
        self.key_vars: dict[str, tk.StringVar] = {}
        choices = sorted(VK_CODES, key=lambda value: (len(value), value))
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Dark.TCombobox", fieldbackground=C["panel_alt"], background=C["panel_alt"], foreground=C["text"], arrowcolor=C["muted"], bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"])
        style.map("Dark.TCombobox", fieldbackground=[("readonly", C["panel_alt"])], foreground=[("readonly", C["text"])])
        for index, (action, label) in enumerate(actions):
            row, column = divmod(index, 2)
            cell = tk.Frame(fields, bg=C["panel"])
            cell.grid(row=row, column=column, sticky="ew", padx=(0, 28) if column == 0 else (0, 0), pady=7)
            fields.grid_columnconfigure(column, weight=1, uniform="keys")
            _label(cell, label, size=9, color="#D3D9E5", anchor="w", width=25).pack(side="left")
            var = tk.StringVar(value=str(self.settings["keymap"].get(action, "")))
            self.key_vars[action] = var
            ttk.Combobox(cell, textvariable=var, values=choices, state="readonly", width=18, style="Dark.TCombobox").pack(side="right", fill="x", expand=True)
        foot = tk.Frame(card, bg=C["panel"])
        foot.pack(fill="x", padx=22, pady=(14, 20))
        _label(foot, "长按判定阈值", size=10, anchor="w").pack(side="left")
        self.heavy_hold_var = tk.IntVar(value=int(self.settings.get("heavy_hold_ms", 360)))
        tk.Spinbox(foot, from_=180, to=1000, increment=10, textvariable=self.heavy_hold_var, width=7, bg=C["panel_alt"], fg=C["text"], buttonbackground=C["panel_alt"], relief="flat", insertbackground="white").pack(side="left", padx=(14, 5), ipady=5)
        _label(foot, "毫秒", size=9, color=C["muted"]).pack(side="left")
        self.key_save_status = _label(foot, "", size=9, color=C["green"])
        self.key_save_status.pack(side="right", padx=(0, 14))
        self._button(foot, "保存并重新监听", self._save_keys, primary=True).pack(side="right")

    def _build_prompts_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "提示设置", "控制悬浮窗行为、监听范围和操作反馈")
        general = self._section(parent)
        _label(general, "监听与反馈", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(20, 10))
        self.only_game_var = tk.BooleanVar(value=bool(self.settings.get("only_when_game_active", True)))
        self.sound_var = tk.BooleanVar(value=bool(self.settings.get("sound_enabled", False)))
        self.overlay_enabled_var = tk.BooleanVar(value=bool(self.settings.get("overlay", {}).get("enabled", True)))
        self._check(general, "显示透明战斗悬浮提示", self.overlay_enabled_var, "仅显示当前角色和下一按键，不显示时间或复杂状态").pack(fill="x", padx=22, pady=6)
        self._check(general, "仅在鸣潮位于前台时监听", self.only_game_var, "切出游戏后自动暂停，避免把日常键盘操作当作连招").pack(fill="x", padx=22, pady=6)
        self._check(general, "每次正确推进时播放提示音", self.sound_var, "默认关闭；不会播放语音或持续音效").pack(fill="x", padx=22, pady=6)
        alpha = tk.Frame(general, bg=C["panel"])
        alpha.pack(fill="x", padx=22, pady=(12, 20))
        _label(alpha, "窗口透明度", size=10, anchor="w", width=18).pack(side="left")
        self.opacity_var = tk.DoubleVar(value=float(self.settings.get("opacity", .94)))
        tk.Scale(alpha, from_=.72, to=1.0, resolution=.01, orient="horizontal", showvalue=False, variable=self.opacity_var, command=self._preview_opacity, bg=C["panel"], fg=C["text"], troughcolor=C["panel_alt"], activebackground=C["purple"], highlightthickness=0, bd=0).pack(side="left", fill="x", expand=True, padx=(10, 16))
        self.opacity_value = _label(alpha, f"{self.opacity_var.get():.0%}", size=10, color="#D8D0FF", width=6)
        self.opacity_value.pack(side="right")

        titles = self._section(parent)
        _label(titles, "游戏窗口识别", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(20, 4))
        _label(titles, "每行一个可能的窗口标题关键词", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=22, pady=(0, 10))
        row = tk.Frame(titles, bg=C["panel"])
        row.pack(fill="x", padx=22, pady=(0, 20))
        self.title_text = tk.Text(row, height=3, bg=C["panel_alt"], fg=C["text"], insertbackground="white", relief="flat", highlightthickness=1, highlightbackground=C["border"], font=("Microsoft YaHei UI", 9), padx=10, pady=8)
        self.title_text.pack(side="left", fill="x", expand=True)
        self.title_text.insert("1.0", "\n".join(self.settings.get("game_titles", [])))
        actions = tk.Frame(row, bg=C["panel"])
        actions.pack(side="right", padx=(14, 0))
        self._button(actions, "读取当前窗口", self._pick_game_window).pack(fill="x", pady=(0, 8))
        self.prompt_save_status = _label(actions, "", size=9, color=C["green"])
        self.prompt_save_status.pack(pady=(3, 0))
        self._button(actions, "保存设置", self._save_prompts, primary=True).pack(fill="x", pady=(8, 0))

    def _build_vision_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "画面识别", "可选增强：只辅助确认角色和少量稳定 HUD，不决定连招是否推进")
        card = self._section(parent)
        self.vision_enabled_var = tk.BooleanVar(value=bool(self.settings.get("vision_enabled", True)))
        self._check(card, "启用保守画面识别", self.vision_enabled_var, "关闭后仍可完整使用按键辅助和锚点同步").pack(fill="x", padx=22, pady=(20, 12))
        _label(card, "识别区域（屏幕像素）", size=11, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(6, 10))
        roi = self.settings.get("vision", {}).get("roi", {})
        self.roi_vars = {name: tk.IntVar(value=int(roi.get(name, default))) for name, default in (("left", 0), ("top", 0), ("width", 320), ("height", 180))}
        fields = tk.Frame(card, bg=C["panel"])
        fields.pack(fill="x", padx=22)
        for column, (name, label) in enumerate((("left", "左 X"), ("top", "上 Y"), ("width", "宽度"), ("height", "高度"))):
            cell = tk.Frame(fields, bg=C["panel"])
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 12 if column < 3 else 0))
            fields.grid_columnconfigure(column, weight=1)
            _label(cell, label, size=9, color=C["muted"], anchor="w").pack(fill="x")
            tk.Entry(cell, textvariable=self.roi_vars[name], bg=C["panel_alt"], fg=C["text"], insertbackground="white", relief="flat", highlightthickness=1, highlightbackground=C["border"], font=("Segoe UI", 10), justify="center").pack(fill="x", ipady=7, pady=(5, 0))
        threshold = tk.Frame(card, bg=C["panel"])
        threshold.pack(fill="x", padx=22, pady=(18, 20))
        _label(threshold, "匹配阈值", size=10, anchor="w").pack(side="left")
        self.threshold_var = tk.DoubleVar(value=float(self.settings.get("vision", {}).get("match_threshold", .86)))
        tk.Scale(threshold, from_=.60, to=.98, resolution=.01, orient="horizontal", variable=self.threshold_var, showvalue=True, bg=C["panel"], fg=C["text"], troughcolor=C["panel_alt"], activebackground=C["purple"], highlightthickness=0, bd=0, length=260).pack(side="left", padx=14)
        self._button(threshold, "保存识别设置", self._save_vision, primary=True).pack(side="right")

        capture = self._section(parent)
        _label(capture, "角色 / HUD 模板", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(16, 3))
        _label(capture, "可手动采集当前 ROI，也可从本机 OK-WW 标注导入卡提希娅与穗穗状态模板。", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=22, pady=(0, 10))
        row = tk.Frame(capture, bg=C["panel"])
        row.pack(fill="x", padx=22, pady=(0, 10))
        characters = sorted({character for preset in self.presets for character in preset.team})
        self.template_character_var = tk.StringVar(value=characters[0] if characters else "当前角色")
        ttk.Combobox(row, textvariable=self.template_character_var, values=characters, state="readonly", width=20, style="Dark.TCombobox").pack(side="left", ipady=5)
        self._button(row, "手动采集当前 ROI", self._capture_template).pack(side="left", padx=12)
        self.vision_status = _label(row, "未采集", size=9, color=C["muted"], anchor="w")
        self.vision_status.pack(side="left", fill="x", expand=True)

        okww = tk.Frame(capture, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["border"])
        okww.pack(fill="x", padx=22, pady=(0, 16))
        self.state_vision_enabled_var = tk.BooleanVar(value=bool(self.settings.get("state_vision", {}).get("enabled", False)))
        tk.Checkbutton(okww, variable=self.state_vision_enabled_var, bg=C["panel_alt"], activebackground=C["panel_alt"], selectcolor=C["purple2"], bd=0, highlightthickness=0).pack(side="left", padx=(12, 5))
        _label(okww, "OK-WW HUD 增强", size=9, weight="bold", bg=C["panel_alt"]).pack(side="left", padx=(0, 10))
        self.okww_path_var = tk.StringVar(value=str(self.settings.get("state_vision", {}).get("okww_path", "F:\\Tools\\okww")))
        tk.Entry(okww, textvariable=self.okww_path_var, bg=C["panel"], fg=C["text"], insertbackground="white", relief="flat", highlightthickness=1, highlightbackground=C["border"], font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 10), pady=10)
        self._button(okww, "导入本机模板", self._import_okww_templates, primary=True).pack(side="left", padx=(0, 10), pady=8)
        self.okww_status = _label(okww, self._okww_status_text(), size=8, color=C["muted"], bg=C["panel_alt"], width=16)
        self.okww_status.pack(side="right", padx=(0, 10))

    def _build_help_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "使用帮助", "不需要额外脚本热键，进入战斗后按你原本的方式操作")
        steps = (
            ("1", "开战前选择队伍", "选择卡夏千或秧千穗；程序先执行启动轴，完成后自动进入循环轴。"),
            ("2", "看下一键并正常操作", "中央大字显示下一步按键。正确输入后自动推进，不要求确认。"),
            ("3", "错键时继续打", "普通错键不会停住程序；它会保持低置信度跟随，等待唯一锚点恢复。"),
            ("4", "长按按够时长", "普攻和重击共用鼠标左键时，程序通过按住时长区分。可在键位设置修改阈值。"),
        )
        for number, title, body in steps:
            card = self._section(parent, pady=(0, 12))
            badge = _label(card, number, size=13, weight="bold", color="white", bg=C["purple2"], width=3, pady=7)
            badge.pack(side="left", padx=20, pady=18)
            text = tk.Frame(card, bg=C["panel"])
            text.pack(side="left", fill="x", expand=True, pady=16)
            _label(text, title, size=11, weight="bold", anchor="w").pack(fill="x")
            _label(text, body, size=9, color=C["muted"], anchor="w", wraplength=850, justify="left").pack(fill="x", pady=(5, 0))

    def _build_about_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "关于", "鸣潮连招辅助 · Windows 离线逐键教练")
        card = self._section(parent)
        _label(card, "鸣潮 · 连招教练", size=25, weight="bold", anchor="w").pack(fill="x", padx=28, pady=(28, 7))
        _label(card, "v1.2.0", size=11, color="#D8D0FF", anchor="w").pack(fill="x", padx=28)
        _label(card, "本程序只读取你配置的按键状态，不拦截、不模拟、不修改游戏输入。", size=11, color=C["muted"], anchor="w", wraplength=850, justify="left").pack(fill="x", padx=28, pady=(18, 20))
        for text in ("✓  完全离线运行", "✓  不保存完整按键日志", "✓  截图和识别模板仅保存在本机", "✓  启动轴完成后自动进入循环轴"):
            _label(card, text, size=10, color=C["green"], anchor="w").pack(fill="x", padx=28, pady=4)
        actions = tk.Frame(card, bg=C["panel"])
        actions.pack(fill="x", padx=28, pady=(22, 28))
        self._button(actions, "打开配置目录", self._open_data_dir).pack(side="left")
        self._button(actions, "导出连招数据", self._export_combo_data).pack(side="left", padx=10)
        self.about_status = _label(actions, "", size=9, color=C["green"])
        self.about_status.pack(side="left", padx=8)

    def _check(self, parent: tk.Widget, title: str, variable: tk.BooleanVar, subtitle: str) -> tk.Frame:
        row = tk.Frame(parent, bg=C["panel"])
        tk.Checkbutton(row, variable=variable, bg=C["panel"], activebackground=C["panel"], selectcolor=C["purple2"], bd=0, highlightthickness=0, cursor="hand2").pack(side="left", padx=(0, 10))
        text = tk.Frame(row, bg=C["panel"])
        text.pack(side="left", fill="x", expand=True)
        _label(text, title, size=10, weight="bold", anchor="w").pack(fill="x")
        _label(text, subtitle, size=8, color=C["muted"], anchor="w").pack(fill="x", pady=(2, 0))
        return row

    # ---------- state and rendering ----------
    def _select_initial_preset(self) -> None:
        preset_id = str(self.settings.get("preset_id", "kaxiaqian-startup"))
        if preset_id in self.engine.presets:
            self.engine.select(preset_id)
        self._refresh_axis_page()

    def _choose_team(self, preset_id: str) -> None:
        self.settings["preset_id"] = preset_id
        self.store.save(self.settings)
        self.engine.select(preset_id)
        self._refresh_axis_page()

    def _refresh_axis_page(self) -> None:
        if not hasattr(self, "axis_texts"):
            return
        startup_id = self.engine.preset.id.replace("-cycle", "-startup")
        startup = self.engine.presets[startup_id]
        cycle = self.engine.presets.get(startup.next_preset_id)
        self.axis_team_label.config(text=f"{'  ·  '.join(startup.team)}   /   {startup.name.split(' · ', 1)[0]}")
        for text_widget, preset in zip(self.axis_texts, (startup, cycle)):
            text_widget.config(state="normal")
            text_widget.delete("1.0", "end")
            if preset is None:
                text_widget.insert("end", "暂无循环轴")
            else:
                self._write_axis(text_widget, preset)
            text_widget.config(state="disabled")
            text_widget.yview_moveto(0)

    @staticmethod
    def _write_axis(text_widget: tk.Text, preset: ComboPreset) -> None:
        previous_segment = ""
        for index, cue in enumerate(preset.cues, start=1):
            if cue.segment != previous_segment:
                if previous_segment:
                    text_widget.insert("end", "\n")
                text_widget.insert("end", f"{cue.character} · {cue.segment}\n", "segment")
                previous_segment = cue.segment
            text_widget.insert("end", f"{index:02d}  ", "step")
            text_widget.insert("end", f"{cue.display_key}", "key")
            text_widget.insert("end", f"    {cue.character}\n")

    def _restart_monitors(self) -> None:
        if self.input_monitor:
            self.input_monitor.stop()
        if self.vision_monitor:
            self.vision_monitor.stop()
        if self.state_vision_monitor:
            self.state_vision_monitor.stop()
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
        self.state_vision_monitor = StateVisionMonitor(
            self.store.templates_dir, self.settings,
            callback=lambda signal, score, matched: self.events.put(("state_vision", (signal, score, matched))),
            enabled=enabled,
        )
        if self.settings.get("vision_enabled") and self.settings.get("state_vision", {}).get("enabled"):
            self.state_vision_monitor.start()

    def _ui_loop(self) -> None:
        active = (not self.settings.get("only_when_game_active", True)) or is_game_foreground(self.settings.get("game_titles", []))
        self.engine.set_active(active)
        self._last_active = active
        overlay_enabled = bool(self.settings.get("overlay", {}).get("enabled", True))
        if active and overlay_enabled:
            if self.battle_overlay.state() == "withdrawn":
                self.battle_overlay.deiconify()
                self.battle_overlay.attributes("-topmost", True)
        elif self.battle_overlay.state() != "withdrawn":
            self.battle_overlay.withdraw()
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
            elif kind == "state_vision":
                signal, score, matched = payload  # type: ignore[misc]
                self.state_vision_scores[str(signal)] = (float(score), bool(matched))
                if matched and str(signal).startswith("character:"):
                    self.engine.observe_character(str(signal).split(":", 1)[1])
                elif matched and str(signal).startswith("cartethyia:"):
                    self.engine.observe_character("卡提希娅")
                elif matched and str(signal) == "suisui:forte3":
                    self.engine.observe_character("穗穗")
                if hasattr(self, "okww_status"):
                    any_match = any(active for _value, active in self.state_vision_scores.values())
                    self.okww_status.config(text=self._okww_status_text(), fg=C["green"] if any_match else C["muted"], width=16)
            elif kind == "command":
                command = str(payload)
                if command == "show": self.show_overlay()
                elif command == "settings": self.open_settings()
                elif command == "reset": self.engine.reset()
                elif command == "open_axis": self._open_full_axis_event()
                elif command == "toggle_float": self._toggle_battle_overlay_enabled()
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
            hint = self._state_vision_hint(cue)
            suffix = f"  ·  {hint}" if hint else ""
            self.condition_label.config(text=f"当前角色：{cue.character}  ·  识别后自动进入下一步{suffix}")
            self.segment_label.config(text=f"第 {view.index + 1} / {view.total} 步")
        self.phase_label.config(text="启动轴（仅一次）" if view.phase == "启动" else f"自动循环中  ·  第 {max(1, view.cycle_count)} 轮")
        self.cycle_label.config(text="启动阶段" if view.phase == "启动" else f"第 {max(1, view.cycle_count)} 轮 / ∞")
        self.recognition_rows[0][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        self.recognition_rows[1][1].config(fg=C["green"] if cue and cue.hold_ms else C["dim"])
        self.recognition_rows[2][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        has_state_match = any(matched for _score, matched in self.state_vision_scores.values())
        self.recognition_rows[3][1].config(fg=C["green"] if has_state_match else C["dim"])
        self._update_preview(view)
        self._draw_sequence(view)
        self._draw_battle_overlay(view)

    def _state_vision_hint(self, cue: Cue) -> str:
        matched = {signal for signal, (_score, active) in self.state_vision_scores.items() if active}
        if cue.character == "卡提希娅":
            if "cartethyia:lib_big" in matched:
                return "画面确认：终结 R 可用"
            if "cartethyia:mid_air" in matched:
                return "画面确认：空中攻击可用"
            swords = sum(f"cartethyia:sword{index}" in matched for index in range(1, 4))
            if "cartethyia:small" in matched or swords:
                return f"画面确认：小卡提 · 已识别 {swords}/3 剑"
        if cue.character == "穗穗" and "suisui:forte3" in matched:
            return "画面确认：Forte3 已满"
        return ""

    def _draw_battle_overlay(self, view: EngineView) -> None:
        canvas = self.float_canvas
        canvas.delete("all")
        cue = view.cue
        character = cue.character if cue else "完成"
        key = self._overlay_key(cue) if cue else "✓"
        key_size = 45 if len(key) <= 3 else 32 if len(key) <= 7 else 25

        def shadow_text(x: int, y: int, text: str, *, font, anchor: str = "w", fill: str = C["text"]) -> None:
            canvas.create_text(x + 2, y + 2, text=text, anchor=anchor, fill="#000000", font=font)
            canvas.create_text(x, y, text=text, anchor=anchor, fill=fill, font=font)

        canvas.create_line(14, 18, 14, 99, fill=C["purple"], width=4)
        shadow_text(33, 26, character, font=("Microsoft YaHei UI", 13, "bold"), fill="#D8D0FF")
        shadow_text(33, 76, key, font=("Microsoft YaHei UI", key_size, "bold"))
        canvas.create_rectangle(225, 6, 326, 46, fill=C["panel_alt"], outline=C["purple"], width=2, tags=("axis_button",))
        canvas.create_text(275, 26, text="全部按键", fill=C["text"], font=("Microsoft YaHei UI", 10, "bold"), tags=("axis_button",))
        canvas.tag_bind("axis_button", "<ButtonRelease-1>", self._open_full_axis_event)
        canvas.tag_bind("axis_button", "<Enter>", lambda _event: canvas.config(cursor="hand2"))
        canvas.tag_bind("axis_button", "<Leave>", lambda _event: canvas.config(cursor="fleur"))

    def _overlay_key(self, cue: Cue) -> str:
        if cue.action == "basic":
            return "A"
        if cue.action == "heavy":
            return "Z"
        configured = str(self.settings.get("keymap", {}).get(cue.action, cue.display_key)).upper()
        aliases = {
            "MOUSE_LEFT": "LMB", "MOUSE_RIGHT": "RMB", "MOUSE_MIDDLE": "MMB",
            "MOUSE_X1": "M4", "MOUSE_X2": "M5", "SPACE": "SPACE",
        }
        return aliases.get(configured, configured)

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
        for preset_id, card in self._team_page_cards.items():
            active = preset_id == selected
            card.config(highlightbackground=C["border_hot"] if active else C["border"], highlightthickness=2 if active else 1)

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
    def _show_page(self, page_id: str) -> None:
        page = self.pages.get(page_id)
        if not page:
            return
        self.current_page = page_id
        page.lift()
        for nav_id, (row, accent, icon, text) in self.nav_rows.items():
            active = nav_id == page_id
            bg = C["panel_hot"] if active else C["sidebar"]
            row.config(bg=bg)
            accent.config(bg=C["purple"] if active else bg)
            icon.config(bg=bg, fg=C["purple"] if active else C["muted"])
            text.config(bg=bg, fg=C["text"] if active else "#C1C9D8", font=("Microsoft YaHei UI", 11, "bold" if active else "normal"))
        if page_id in {"coach", "teams"}:
            self._style_team_cards()
        if page_id == "axis":
            self._refresh_axis_page()

    def _select_team_from_page(self, preset_id: str) -> None:
        self._choose_team(preset_id)
        self._show_page("coach")

    def _save_keys(self) -> None:
        self.settings["keymap"] = {action: variable.get() for action, variable in self.key_vars.items()}
        self.settings["heavy_hold_ms"] = max(180, min(1000, int(self.heavy_hold_var.get())))
        self.settings["calibration_completed"] = True
        self.store.save(self.settings)
        self._restart_monitors()
        self.key_save_status.config(text="✓ 已保存")
        self.root.after(2200, lambda: self.key_save_status.config(text=""))

    def _preview_opacity(self, _value: str = "") -> None:
        value = float(self.opacity_var.get())
        self.root.attributes("-alpha", value)
        self.opacity_value.config(text=f"{value:.0%}")

    def _pick_game_window(self) -> None:
        titles = [title for title in enumerate_window_titles() if "鸣潮 · 连招教练" not in title and "鸣潮逐键教练" not in title]
        preferred = next((title for title in titles if "鸣潮" in title or "Wuthering Waves" in title), "")
        if preferred:
            lines = [line.strip() for line in self.title_text.get("1.0", "end").splitlines() if line.strip()]
            if preferred not in lines:
                lines.insert(0, preferred)
            self.title_text.delete("1.0", "end")
            self.title_text.insert("1.0", "\n".join(lines))
            self.prompt_save_status.config(text="已读取")
        else:
            self.prompt_save_status.config(text="未找到鸣潮窗口", fg=C["gold"])

    def _save_prompts(self) -> None:
        self.settings["only_when_game_active"] = bool(self.only_game_var.get())
        self.settings["sound_enabled"] = bool(self.sound_var.get())
        self.settings.setdefault("overlay", {})["enabled"] = bool(self.overlay_enabled_var.get())
        self.settings["opacity"] = float(self.opacity_var.get())
        self.settings["game_titles"] = [line.strip() for line in self.title_text.get("1.0", "end").splitlines() if line.strip()]
        self.settings["calibration_completed"] = True
        self.store.save(self.settings)
        self._restart_monitors()
        self.prompt_save_status.config(text="✓ 已保存", fg=C["green"])
        self.root.after(2200, lambda: self.prompt_save_status.config(text=""))

    def _apply_vision_form(self) -> None:
        vision = self.settings.setdefault("vision", {})
        vision["roi"] = {name: max(0 if name in {"left", "top"} else 1, int(variable.get())) for name, variable in self.roi_vars.items()}
        vision["match_threshold"] = max(.60, min(.98, float(self.threshold_var.get())))
        self.settings["vision_enabled"] = bool(self.vision_enabled_var.get())
        state = self.settings.setdefault("state_vision", {})
        state["enabled"] = bool(self.state_vision_enabled_var.get())
        state["okww_path"] = self.okww_path_var.get().strip()

    def _save_vision(self) -> None:
        self._apply_vision_form()
        self.store.save(self.settings)
        self._restart_monitors()
        self.vision_status.config(text="✓ 识别设置已保存", fg=C["green"])

    def _capture_template(self) -> None:
        try:
            self._apply_vision_form()
            self.store.save(self.settings)
            monitor = self.vision_monitor or VisionMonitor(self.store.templates_dir, self.settings, lambda: "", lambda _s, _v: None)
            character = self.template_character_var.get().strip()
            path = monitor.capture_template(f"character:{character}")
            self._restart_monitors()
            self.vision_status.config(text=f"✓ 已保存：{path.name}", fg=C["green"])
        except Exception as exc:
            self.vision_status.config(text=f"采集失败：{exc}", fg=C["red"])

    def _okww_status_text(self) -> str:
        signals = self.settings.get("state_vision", {}).get("signals", {})
        imported = sum(1 for signal in OKWW_SIGNAL_CATEGORIES if signals.get(signal, {}).get("enabled"))
        matched = sum(1 for signal, (_score, active) in self.state_vision_scores.items() if signal in OKWW_SIGNAL_CATEGORIES and active)
        return f"命中 {matched} / 已导入 {imported}"

    def _import_okww_templates(self) -> None:
        try:
            root = Path(self.okww_path_var.get().strip())
            imported = import_okww_templates(root, self.store.templates_dir)
            self.character_asset_paths = import_okww_portraits(root, self.store.assets_dir)
            self._refresh_character_portraits()
            state = self.settings.setdefault("state_vision", {})
            state["signals"] = imported
            state["enabled"] = True
            state["okww_path"] = self.okww_path_var.get().strip()
            self.state_vision_enabled_var.set(True)
            self.settings["vision_enabled"] = True
            self.vision_enabled_var.set(True)
            self.store.save(self.settings)
            self._restart_monitors()
            self.okww_status.config(
                text=f"✓ 识别素材 {len(imported)} 项 · 头像 {len(self.character_asset_paths)} 个",
                fg=C["green"],
            )
        except Exception as exc:
            self.okww_status.config(text=f"导入失败：{exc}", fg=C["red"], width=34)

    def _auto_import_okww_templates(self) -> None:
        state = self.settings.setdefault("state_vision", {})
        if state.get("signals"):
            return
        root = Path(str(state.get("okww_path", "F:\\Tools\\okww")))
        if not root.exists():
            return
        try:
            imported = import_okww_templates(root, self.store.templates_dir)
        except (OSError, ValueError):
            return
        state["signals"] = imported
        state["enabled"] = True
        self.settings["vision_enabled"] = True
        if hasattr(self, "state_vision_enabled_var"):
            self.state_vision_enabled_var.set(True)
            self.vision_enabled_var.set(True)
            self.okww_status.config(text=f"✓ 自动导入 {len(imported)} 项", fg=C["green"])
        self.store.save(self.settings)

    def _auto_import_okww_portraits(self) -> None:
        self.character_asset_paths = bundled_portrait_paths()
        state = self.settings.setdefault("state_vision", {})
        root = Path(str(state.get("okww_path", "F:\\Tools\\okww")))
        if not root.exists():
            return
        try:
            self.character_asset_paths.update(import_okww_portraits(root, self.store.assets_dir))
        except (OSError, ValueError):
            pass

    def _open_data_dir(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(self.store.root)  # type: ignore[attr-defined]
            self.about_status.config(text="已打开")
        except OSError as exc:
            self.about_status.config(text=f"打开失败：{exc}", fg=C["red"])

    def _export_combo_data(self) -> None:
        path = self.store.export_presets([asdict(preset) for preset in self.presets])
        self.about_status.config(text=f"已导出：{path.name}", fg=C["green"])

    def open_settings(self) -> None:
        self.force_visible = True
        self.show_overlay()
        self._show_page("prompts")

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

    def _start_overlay_drag(self, event: tk.Event) -> None:
        self._overlay_drag_origin = (
            event.x_root - self.battle_overlay.winfo_x(),
            event.y_root - self.battle_overlay.winfo_y(),
        )

    def _drag_overlay(self, event: tk.Event) -> None:
        if self._overlay_drag_origin:
            x = event.x_root - self._overlay_drag_origin[0]
            y = event.y_root - self._overlay_drag_origin[1]
            self.battle_overlay.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _end_overlay_drag(self, _event: tk.Event) -> None:
        self._overlay_drag_origin = None
        overlay = self.settings.setdefault("overlay", {})
        overlay["x"] = self.battle_overlay.winfo_x()
        overlay["y"] = self.battle_overlay.winfo_y()
        self.store.save(self.settings)

    def _show_context_menu(self, event: tk.Event) -> None:
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_full_axis_event(self, _event: tk.Event | None = None) -> str:
        self.show_overlay()
        self._show_page("axis")
        return "break"

    def _toggle_battle_overlay_enabled(self) -> None:
        overlay = self.settings.setdefault("overlay", {})
        overlay["enabled"] = not bool(overlay.get("enabled", True))
        if hasattr(self, "overlay_enabled_var"):
            self.overlay_enabled_var.set(overlay["enabled"])
        if not overlay["enabled"]:
            self.battle_overlay.withdraw()
        self.store.save(self.settings)

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
                pystray.MenuItem("查看完整按键轴", lambda: self.events.put(("command", "open_axis"))),
                pystray.MenuItem("显示 / 隐藏战斗悬浮提示", lambda: self.events.put(("command", "toggle_float"))),
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
        if self.state_vision_monitor:
            self.state_vision_monitor.stop()
        if self._tray:
            self._tray.stop()
        self.store.save(self.settings)
        self.root.destroy()
