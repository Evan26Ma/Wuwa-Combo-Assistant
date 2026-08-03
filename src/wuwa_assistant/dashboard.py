from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageDraw, ImageTk

from .animation_guard import AnimationInputGuard
from .combo_data import ASSET_ROOT, load_icon_mappings
from .combo_map import build_combo_segments, current_segment_index, plan_combo_map
from .engine import ComboEngine
from .foreground import enumerate_window_titles, is_game_foreground
from .input_monitor import InputMonitor, VK_CODES
from .models import ComboPreset, Cue, EngineView, InputEvent
from .settings import SettingsStore
from .vision import (
    OKWW_SIGNAL_CATEGORIES,
    StateVisionMonitor,
    TeamVisionMonitor,
    VisionMonitor,
    bundled_portrait_paths,
    import_okww_portraits,
    import_okww_templates,
    install_bundled_state_templates,
)
from .video_axis import analyze_video_key_panel, export_candidate_timeline, find_ffmpeg


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
    "LOCKED": ("动作锁定", C["gold"]),
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
        self.input_guard = AnimationInputGuard(self.settings)
        self.input_monitor: InputMonitor | None = None
        self.vision_monitor: VisionMonitor | None = None
        self.state_vision_monitor: StateVisionMonitor | None = None
        self.team_vision_monitor: TeamVisionMonitor | None = None
        self.vision_signal = ""
        self.vision_score = -1.0
        self.state_vision_scores: dict[str, tuple[float, bool]] = {}
        self.force_visible = True
        self._tray = None
        self._drag_origin: tuple[int, int] | None = None
        self._overlay_drag_origin: tuple[int, int] | None = None
        self._overlay_size: tuple[int, int] = (0, 0)
        self._last_rendered_index = -1
        self._last_active: bool | None = None
        self._team_cards: dict[str, tk.Frame] = {}
        self._team_chips: dict[str, tk.Frame] = {}
        self._team_page_cards: dict[str, tk.Frame] = {}
        self._team_order_cards: list[tk.Frame] = []
        self._team_order_name_labels: list[tk.Label] = []
        self._team_order_portrait_labels: list[tk.Label] = []
        self._team_order_drag_index: int | None = None
        self._last_team_order_editor: tuple[str, ...] = ()
        self.pages: dict[str, tk.Frame] = {}
        self.nav_rows: dict[str, tuple[tk.Frame, tk.Frame, tk.Label, tk.Label]] = {}
        self.current_page = "coach"
        self._restore_geometry = ""
        self.character_asset_paths: dict[str, Path] = {}
        self.character_photos: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self._portrait_labels: list[tuple[tk.Label, str, int]] = []
        self.video_analysis_running = False
        self.overlay_icon_mappings = load_icon_mappings()
        self.overlay_icon_photos: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self._overlay_draw_scale = 1.0

        self._auto_import_okww_portraits()
        self._install_bundled_state_templates()
        self._build_window()
        self.root.after(60, self._register_taskbar_window)
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
        self.context_menu.add_command(label="切换悬浮窗移动模式", command=self._toggle_overlay_move_mode)
        layout_menu = tk.Menu(self.context_menu, tearoff=False, bg=C["panel_alt"], fg=C["text"])
        for value, label in (("horizontal", "横向分段地图"), ("vertical", "纵向分段地图"), ("waterfall", "瀑布分段地图")):
            layout_menu.add_command(label=label, command=lambda mode=value: self._set_overlay_layout(mode))
        self.context_menu.add_cascade(label="悬浮窗布局", menu=layout_menu)
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

        width, height = 650, 132
        overlay_settings = self.settings.get("overlay", {})
        x = overlay_settings.get("x")
        if x is None:
            x = self.root.winfo_screenwidth() - width - 48
        y = int(overlay_settings.get("y", 72))
        x = min(max(0, int(x)), max(0, self.root.winfo_screenwidth() - width))
        y = min(max(0, y), max(0, self.root.winfo_screenheight() - height))
        self.battle_overlay.geometry(f"{width}x{height}+{x}+{y}")

        self.float_canvas = tk.Canvas(
            self.battle_overlay, width=width, height=height, bg=transparent,
            highlightthickness=0, bd=0, cursor="fleur",
        )
        self.float_canvas.pack(fill="both", expand=True)
        self.float_canvas.bind("<ButtonPress-1>", self._start_overlay_drag)
        self.float_canvas.bind("<B1-Motion>", self._drag_overlay)
        self.float_canvas.bind("<ButtonRelease-1>", self._end_overlay_drag)
        self.float_canvas.bind("<Button-3>", self._show_context_menu)
        self._load_overlay_icons()
        self.battle_overlay.update_idletasks()
        self._apply_overlay_interaction_style()
        self.battle_overlay.withdraw()

    def _load_overlay_icons(self) -> None:
        for entry in self.overlay_icon_mappings.values():
            self._overlay_icon_photo(entry["icon"], 28)

    def _overlay_icon_photo(self, filename: str, size: int) -> ImageTk.PhotoImage | None:
        size = max(12, int(size))
        key = (filename, size)
        if key in self.overlay_icon_photos:
            return self.overlay_icon_photos[key]
        path = ASSET_ROOT / "action_icons" / filename
        try:
            image = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
        except (OSError, ValueError):
            return None
        self.overlay_icon_photos[key] = photo
        return photo

    def _hud_font(self, family: str, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return family, max(5, round(size * self._overlay_draw_scale)), weight

    def _hud_width(self, width: int) -> int:
        return max(1, round(width * self._overlay_draw_scale))

    @staticmethod
    def _overlay_scale_value(value: object) -> float:
        try:
            return max(.65, min(1.5, float(value)))
        except (TypeError, ValueError):
            return 1.0

    def _apply_overlay_interaction_style(self) -> None:
        try:
            import ctypes
            hwnd = self.battle_overlay.winfo_id()
            get_style = ctypes.windll.user32.GetWindowLongW
            set_style = ctypes.windll.user32.SetWindowLongW
            style = get_style(hwnd, -20)
            style |= 0x08000000 | 0x00000080  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if self.settings.get("overlay", {}).get("move_mode", False):
                style &= ~0x00000020  # interactive while moving
                self.float_canvas.config(cursor="fleur")
            else:
                style |= 0x00000020  # WS_EX_TRANSPARENT: mouse passes to the game
                self.float_canvas.config(cursor="arrow")
            set_style(hwnd, -20, style)
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)
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
        self._header_button(controls, "—", self._minimize_to_taskbar, width=3).pack(side="left")
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
            ("video", "▶", "视频识别"),
            ("help", "?", "使用帮助"),
            ("about", "i", "关于"),
        )
        for page_id, icon, text in nav:
            row = tk.Frame(side, bg=C["sidebar"], height=50, cursor="hand2")
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
        _label(status, "v1.5.0  |  完全离线", size=9, color=C["muted"], anchor="w").pack(fill="x", padx=14)
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
            ("video", self._build_video_page),
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
            text_widget.tag_configure("condition", foreground="#C7CFDD", font=("Microsoft YaHei UI", 9, "normal"), lmargin1=34, lmargin2=34)
            text_widget.tag_configure("advice", foreground=C["green"], font=("Microsoft YaHei UI", 9, "normal"), lmargin1=34, lmargin2=34, spacing3=5)
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
        self.advice_label = _label(card, "", size=9, color=C["green"], wraplength=650, justify="center")
        self.advice_label.pack(padx=26, pady=(0, 8))
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
        for text in ("按键序列匹配", "长按输入判定", "锚点同步状态", "角色 HUD 增强", "队伍槽位自动识别"):
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
        self._page_header(parent, "队伍选择", "选择启动轴即可；程序会识别游戏内实际的 1 / 2 / 3 号位")
        self.team_order_label = _label(
            parent, "队伍位置：等待画面识别", size=10, color=C["gold"], anchor="w",
            bg=C["panel_alt"], padx=14, pady=9, highlightthickness=1,
            highlightbackground=C["border"],
        )
        self.team_order_label.pack(fill="x", pady=(0, 12))
        editor = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        editor.pack(fill="x", pady=(0, 12))
        editor_head = tk.Frame(editor, bg=C["panel"])
        editor_head.pack(fill="x", padx=16, pady=(12, 8))
        _label(editor_head, "拖动调整实际角色顺序", size=11, weight="bold", anchor="w").pack(side="left")
        _label(editor_head, "切人步骤按角色目标保存，不与固定数字位绑定", size=8, color=C["muted"], anchor="e").pack(side="right")
        order_strip = tk.Frame(editor, bg=C["panel"])
        order_strip.pack(fill="x", padx=16, pady=(0, 14))
        for index in range(3):
            card = tk.Frame(
                order_strip, bg=C["panel_alt"], cursor="fleur",
                highlightthickness=1, highlightbackground=C["border"], height=62,
            )
            card.pack(side="left", fill="x", expand=True, padx=(0, 8 if index < 2 else 0))
            card.pack_propagate(False)
            _label(card, f"{index + 1}", size=13, color=C["purple"], weight="bold", width=3).pack(side="left", padx=(8, 2))
            portrait = tk.Label(card, bg=C["panel_alt"], fg=C["text"], bd=0, width=4, height=2)
            portrait.pack(side="left", padx=(0, 9), pady=9)
            name = _label(card, "—", size=11, weight="bold", anchor="w", bg=C["panel_alt"])
            name.pack(side="left", fill="x", expand=True)
            _label(card, "⋮⋮", size=11, color=C["dim"], bg=C["panel_alt"]).pack(side="right", padx=9)
            self._team_order_cards.append(card)
            self._team_order_portrait_labels.append(portrait)
            self._team_order_name_labels.append(name)
            self._bind_tree(card, "<ButtonPress-1>", lambda _event, slot=index: self._start_team_order_drag(slot))
            self._bind_tree(card, "<ButtonRelease-1>", self._finish_team_order_drag)
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
            saved_order = self.settings.get("team_orders", {}).get(self._team_signature(preset.team), preset.team)
            axis = "  →  ".join(self._cue_display_for_order(cue, tuple(saved_order)) for cue in preset.cues[:10])
            _label(card, axis + ("  …" if len(preset.cues) > 10 else ""), size=11, wraplength=470, justify="left", anchor="w").pack(fill="x", padx=26, pady=(8, 28))
            choose = self._button(card, "使用这套连招", lambda pid=preset.id: self._select_team_from_page(pid), primary=True)
            choose.pack(anchor="w", padx=26, pady=(0, 28))
            self._bind_tree(card, "<Button-1>", lambda _e, pid=preset.id: self._select_team_from_page(pid))
        self._refresh_team_order_editor(force=True)

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
            ("forward", "前进"), ("slot1", "队伍槽位 1"),
            ("slot2", "队伍槽位 2"), ("slot3", "队伍槽位 3"),
            ("reset_primary", "重置连招（主键）"),
            ("reset_secondary", "重置连招（备用）"),
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
        self.overlay_move_var = tk.BooleanVar(value=bool(self.settings.get("overlay", {}).get("move_mode", False)))
        self.overlay_layout_var = tk.StringVar(value=str(self.settings.get("overlay", {}).get("layout", "horizontal")))
        self.overlay_scale_var = tk.DoubleVar(
            value=self._overlay_scale_value(self.settings.get("overlay", {}).get("scale", 1.0)),
        )
        guard = self.settings.get("input_guard", {})
        self.input_guard_enabled_var = tk.BooleanVar(value=bool(guard.get("enabled", True)))
        self._check(general, "显示透明战斗悬浮提示", self.overlay_enabled_var, "头像分段地图仅展开当前附近轴段，顶部节点显示整轴位置").pack(fill="x", padx=22, pady=6)
        self._check(general, "悬浮窗移动模式", self.overlay_move_var, "开启后可拖动；关闭后鼠标穿透，不影响游戏操作").pack(fill="x", padx=22, pady=6)
        self._check(general, "仅在鸣潮位于前台时监听", self.only_game_var, "切出游戏后自动暂停，避免把日常键盘操作当作连招").pack(fill="x", padx=22, pady=6)
        self._check(general, "每次正确推进时播放提示音", self.sound_var, "默认关闭；不会播放语音或持续音效").pack(fill="x", padx=22, pady=6)
        self._check(
            general, "动作期间暂停连招推进", self.input_guard_enabled_var,
            "大招优先观察队伍 HUD 消失/恢复；普攻使用短保护，重置键始终有效",
        ).pack(fill="x", padx=22, pady=6)
        layout_row = tk.Frame(general, bg=C["panel"])
        layout_row.pack(fill="x", padx=22, pady=(12, 2))
        _label(layout_row, "连段排列", size=10, anchor="w", width=18).pack(side="left")
        ttk.Combobox(
            layout_row, textvariable=self.overlay_layout_var,
            values=("horizontal", "vertical", "waterfall"), state="readonly",
            width=18, style="Dark.TCombobox",
        ).pack(side="left", ipady=4, padx=(10, 12))
        _label(layout_row, "horizontal 横向地图 · vertical 纵向地图 · waterfall 瀑布地图", size=8, color=C["muted"], anchor="w").pack(side="left")
        scale_row = tk.Frame(general, bg=C["panel"])
        scale_row.pack(fill="x", padx=22, pady=(10, 2))
        _label(scale_row, "悬浮窗大小", size=10, anchor="w", width=18).pack(side="left")
        tk.Scale(
            scale_row, from_=.65, to=1.5, resolution=.05, orient="horizontal", showvalue=False,
            variable=self.overlay_scale_var, command=self._preview_overlay_scale,
            bg=C["panel"], fg=C["text"], troughcolor=C["panel_alt"], activebackground=C["purple"],
            highlightthickness=0, bd=0,
        ).pack(side="left", fill="x", expand=True, padx=(10, 16))
        self.overlay_scale_value = _label(
            scale_row, f"{self.overlay_scale_var.get():.0%}", size=10, color="#D8D0FF", width=6,
        )
        self.overlay_scale_value.pack(side="right")
        guard_row = tk.Frame(general, bg=C["panel"])
        guard_row.pack(fill="x", padx=22, pady=(10, 2))
        self.basic_lock_var = tk.IntVar(value=int(guard.get("basic_lock_ms", 110)))
        self.liberation_fallback_var = tk.IntVar(value=int(guard.get("liberation_fallback_ms", 3000)))
        _label(guard_row, "普攻保护", size=9, color=C["muted"]).pack(side="left")
        tk.Spinbox(guard_row, from_=0, to=500, increment=10, textvariable=self.basic_lock_var, width=6,
                   bg=C["panel_alt"], fg=C["text"], buttonbackground=C["panel_alt"], relief="flat",
                   insertbackground="white").pack(side="left", padx=(8, 4), ipady=3)
        _label(guard_row, "ms", size=8, color=C["muted"]).pack(side="left")
        _label(guard_row, "无 HUD 识别时的大招保护", size=9, color=C["muted"]).pack(side="left", padx=(24, 0))
        tk.Spinbox(guard_row, from_=800, to=7000, increment=100, textvariable=self.liberation_fallback_var, width=7,
                   bg=C["panel_alt"], fg=C["text"], buttonbackground=C["panel_alt"], relief="flat",
                   insertbackground="white").pack(side="left", padx=(8, 4), ipady=3)
        _label(guard_row, "ms", size=8, color=C["muted"]).pack(side="left")
        alpha = tk.Frame(general, bg=C["panel"])
        alpha.pack(fill="x", padx=22, pady=(10, 20))
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

    def _build_video_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "视频按键识别", "从教学视频的按键显示区域提取候选时间轴；结果必须人工复核")
        source = self._section(parent)
        _label(source, "视频与 FFmpeg", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(18, 8))
        config = self.settings.get("video_recognition", {})
        self.video_path_var = tk.StringVar(value=str(config.get("video_path", "")))
        self.ffmpeg_path_var = tk.StringVar(value=str(config.get("ffmpeg_path", "")))
        for label, variable, command in (
            ("教学视频", self.video_path_var, self._pick_video_file),
            ("FFmpeg", self.ffmpeg_path_var, None),
        ):
            row = tk.Frame(source, bg=C["panel"])
            row.pack(fill="x", padx=22, pady=5)
            _label(row, label, size=9, color=C["muted"], anchor="w", width=12).pack(side="left")
            tk.Entry(
                row, textvariable=variable, bg=C["panel_alt"], fg=C["text"], insertbackground="white",
                relief="flat", highlightthickness=1, highlightbackground=C["border"], font=("Segoe UI", 9),
            ).pack(side="left", fill="x", expand=True, ipady=7)
            if command:
                self._button(row, "选择视频", command).pack(side="left", padx=(10, 0))
        _label(
            source,
            "识别 wwcombo 标准按键面板的青色高亮；其他作者的按键皮肤需先校准热点，当前输出只作为候选轴。",
            size=8, color=C["gold"], anchor="w", wraplength=900, justify="left",
        ).pack(fill="x", padx=22, pady=(8, 16))

        region = self._section(parent)
        _label(region, "按键区域与轴分段", size=13, weight="bold", anchor="w").pack(fill="x", padx=22, pady=(16, 4))
        _label(region, "区域使用视频宽高百分比；循环开始为 0 时全部写入启动轴。", size=8, color=C["muted"], anchor="w").pack(fill="x", padx=22, pady=(0, 10))
        bounds = config.get("bounds_percent", {})
        self.video_bounds_vars = {
            name: tk.DoubleVar(value=float(bounds.get(name, default)))
            for name, default in (("x", 0), ("y", 0), ("width", 26), ("height", 22))
        }
        fields = tk.Frame(region, bg=C["panel"])
        fields.pack(fill="x", padx=22)
        for column, (name, label) in enumerate((("x", "左 X%"), ("y", "上 Y%"), ("width", "宽 W%"), ("height", "高 H%"))):
            cell = tk.Frame(fields, bg=C["panel"])
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 10))
            fields.grid_columnconfigure(column, weight=1)
            _label(cell, label, size=8, color=C["muted"], anchor="w").pack(fill="x")
            tk.Entry(cell, textvariable=self.video_bounds_vars[name], bg=C["panel_alt"], fg=C["text"], insertbackground="white", relief="flat", highlightthickness=1, highlightbackground=C["border"], justify="center").pack(fill="x", ipady=6, pady=(4, 0))
        extra = tk.Frame(fields, bg=C["panel"])
        extra.grid(row=0, column=4, sticky="ew")
        fields.grid_columnconfigure(4, weight=1)
        _label(extra, "循环开始 ms", size=8, color=C["muted"], anchor="w").pack(fill="x")
        self.video_cycle_start_var = tk.IntVar(value=int(config.get("cycle_start_ms", 0)))
        tk.Entry(extra, textvariable=self.video_cycle_start_var, bg=C["panel_alt"], fg=C["text"], insertbackground="white", relief="flat", highlightthickness=1, highlightbackground=C["border"], justify="center").pack(fill="x", ipady=6, pady=(4, 0))
        actions = tk.Frame(region, bg=C["panel"])
        actions.pack(fill="x", padx=22, pady=(16, 18))
        self.video_analyze_button = self._button(actions, "开始辅助识别", self._start_video_analysis, primary=True)
        self.video_analyze_button.pack(side="left")
        self._button(actions, "打开结果目录", self._open_video_analysis_dir).pack(side="left", padx=10)
        self.video_analysis_status = _label(actions, "等待选择视频", size=9, color=C["muted"], anchor="w")
        self.video_analysis_status.pack(side="left", fill="x", expand=True, padx=10)

    def _build_about_page(self, parent: tk.Frame) -> None:
        self._page_header(parent, "关于", "鸣潮连招辅助 · Windows 离线逐键教练")
        card = self._section(parent)
        _label(card, "鸣潮 · 连招教练", size=25, weight="bold", anchor="w").pack(fill="x", padx=28, pady=(28, 7))
        _label(card, "v1.5.0", size=11, color="#D8D0FF", anchor="w").pack(fill="x", padx=28)
        _label(card, "本程序只读取你配置的按键状态，不拦截、不模拟、不修改游戏输入。", size=11, color=C["muted"], anchor="w", wraplength=850, justify="left").pack(fill="x", padx=28, pady=(18, 20))
        _label(card, "测试阶段 · 仅供学习交流 · 完全免费 · 禁止商业售卖", size=11, color=C["gold"], weight="bold", anchor="w").pack(fill="x", padx=28, pady=(0, 14))
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
        self._apply_saved_team_order()
        self._refresh_axis_page()

    def _choose_team(self, preset_id: str) -> None:
        self.settings["preset_id"] = preset_id
        self.store.save(self.settings)
        self.engine.select(preset_id)
        self._apply_saved_team_order()
        self._refresh_axis_page()

    @staticmethod
    def _team_signature(team: tuple[str, str, str]) -> str:
        return "|".join(sorted(team))

    def _apply_saved_team_order(self) -> None:
        signature = self._team_signature(self.engine.preset.team)
        order = self.settings.get("team_orders", {}).get(signature)
        if isinstance(order, list):
            self.engine.set_team_order(order, confirmed=False)
        self._refresh_team_order_editor(force=True)

    def _save_team_order(self) -> None:
        signature = self._team_signature(self.engine.preset.team)
        orders = self.settings.setdefault("team_orders", {})
        order = list(self.engine.team_order)
        if orders.get(signature) != order:
            orders[signature] = order
            self.store.save(self.settings)

    def _configured_key(self, action: str) -> str:
        configured = str(self.settings.get("keymap", {}).get(action, action)).upper()
        aliases = {
            "MOUSE_LEFT": "LMB", "MOUSE_RIGHT": "RMB", "MOUSE_MIDDLE": "MMB",
            "MOUSE_X1": "M4", "MOUSE_X2": "M5", "SPACE": "SPACE",
        }
        return aliases.get(configured, configured)

    def _cue_display(self, cue: Cue) -> str:
        return self._cue_display_for_order(cue, self.engine.team_order)

    def _cue_display_for_order(self, cue: Cue, order: tuple[str, ...]) -> str:
        if cue.action.startswith("slot"):
            action = f"slot{order.index(cue.character) + 1}" if cue.character in order else cue.action
            return f"切{self._configured_key(action)}"
        return cue.display_key

    def _cue_condition(self, cue: Cue) -> str:
        if not cue.action.startswith("slot"):
            return cue.condition
        key = self._configured_key(self.engine.action_for(cue))
        condition = re.sub(r"切到\s*[123]\s*号位", f"按 {key} 切到 {cue.character}", cue.condition)
        if condition == cue.condition:
            condition = f"{condition} · 按 {key} 切到 {cue.character}"
        return condition

    def _refresh_axis_page(self) -> None:
        if not hasattr(self, "axis_texts"):
            return
        startup_id = self.engine.preset.id.replace("-cycle", "-startup")
        startup = self.engine.presets[startup_id]
        cycle = self.engine.presets.get(startup.next_preset_id)
        order = self.engine.team_order
        self.axis_team_label.config(
            text=f"{'  ·  '.join(f'{index + 1} {name}' for index, name in enumerate(order))}"
                 f"   /   {startup.name.split(' · ', 1)[0]}"
        )
        for text_widget, preset in zip(self.axis_texts, (startup, cycle)):
            text_widget.config(state="normal")
            text_widget.delete("1.0", "end")
            if preset is None:
                text_widget.insert("end", "暂无循环轴")
            else:
                self._write_axis(text_widget, preset)
            text_widget.config(state="disabled")
            text_widget.yview_moveto(0)

    def _write_axis(self, text_widget: tk.Text, preset: ComboPreset) -> None:
        previous_segment = ""
        for index, cue in enumerate(preset.cues, start=1):
            if cue.segment != previous_segment:
                if previous_segment:
                    text_widget.insert("end", "\n")
                text_widget.insert("end", f"{cue.character} · {cue.segment}\n", "segment")
                previous_segment = cue.segment
            text_widget.insert("end", f"{index:02d}  ", "step")
            text_widget.insert("end", self._cue_display(cue), "key")
            text_widget.insert("end", f"    {cue.character}\n")
            text_widget.insert("end", f"操作：{self._cue_condition(cue)}\n", "condition")
            if cue.advice:
                text_widget.insert("end", f"OK-WW 建议：{cue.advice}\n", "advice")

    def _restart_monitors(self) -> None:
        if self.input_monitor:
            self.input_monitor.stop()
        if self.vision_monitor:
            self.vision_monitor.stop()
        if self.state_vision_monitor:
            self.state_vision_monitor.stop()
        if self.team_vision_monitor:
            self.team_vision_monitor.stop()
        enabled = lambda: (not self.settings.get("only_when_game_active", True)) or is_game_foreground(self.settings.get("game_titles", []))
        self.input_monitor = InputMonitor(
            self.settings["keymap"], self._handle_input_event,
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
        self.team_vision_monitor = TeamVisionMonitor(
            self.store.templates_dir, self.settings,
            expected_team=lambda: tuple(self.engine.preset.team),
            callback=lambda order, scores, matched: self.events.put(
                ("team_vision", (order, scores, matched))
            ),
            enabled=enabled,
        )
        if self.settings.get("vision_enabled"):
            self.team_vision_monitor.start()

    def _handle_input_event(self, event: InputEvent) -> None:
        if event.action in {"reset_primary", "reset_secondary"}:
            if hasattr(self, "input_guard"):
                self.input_guard.reset()
            self.events.put(("command", "reset"))
            return
        if hasattr(self, "input_guard") and not self.input_guard.allows(event):
            self._sync_input_guard()
            return
        self.engine.process(event)
        if hasattr(self, "input_guard"):
            self.input_guard.record(event)
            self._sync_input_guard()

    def _sync_input_guard(self) -> None:
        state = self.input_guard.state()
        self.engine.set_input_lock(state.locked, state.reason)

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
            elif kind == "team_vision":
                order, scores, matched = payload  # type: ignore[misc]
                self.input_guard.observe_party_hud(scores)
                self._sync_input_guard()
                if matched and self.engine.set_team_order(order, confirmed=True):
                    self._save_team_order()
                    self._refresh_axis_page()
            elif kind == "video_analysis":
                status, message = payload  # type: ignore[misc]
                if hasattr(self, "video_analysis_status"):
                    color = C["green"] if status == "done" else C["red"] if status == "error" else C["gold"]
                    self.video_analysis_status.config(text=str(message), fg=color)
                if status in {"done", "error"}:
                    self.video_analysis_running = False
                    if hasattr(self, "video_analyze_button"):
                        self.video_analyze_button.config(state="normal", text="开始辅助识别")
            elif kind == "command":
                command = str(payload)
                if command == "show": self.show_overlay()
                elif command == "settings": self.open_settings()
                elif command == "reset": self.engine.reset()
                elif command == "open_axis": self._open_full_axis_event()
                elif command == "toggle_float": self._toggle_battle_overlay_enabled()
                elif command == "toggle_move": self._toggle_overlay_move_mode()
                elif command.startswith("layout:"): self._set_overlay_layout(command.split(":", 1)[1])
                elif command == "quit": self.shutdown(); return
        self.input_guard.tick()
        self._sync_input_guard()
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
        self._refresh_team_order_editor()
        cue = view.cue
        state_text, state_color = STATE.get(view.timing_state, (view.timing_state, C["muted"]))
        self.state_label.config(text=f"●  {state_text}", fg=state_color)
        self.key_box.config(highlightbackground=state_color)
        if cue is None:
            self.key_label.config(text="✓", fg=C["green"], font=("Segoe UI", 38, "bold"))
            self.condition_title.config(text="本轮完成")
            self.condition_label.config(text="等待重置或选择另一支队伍")
            self.advice_label.config(text="")
            self.segment_label.config(text="")
        else:
            display = self._cue_display(cue)
            size = 38 if len(display) <= 2 else 29 if len(display) == 3 else 23
            self.key_label.config(text=display, fg=C["text"], font=("Microsoft YaHei UI", size, "bold"))
            self.condition_title.config(text="动作锁定" if view.input_locked else cue.segment)
            hint = self._state_vision_hint(cue)
            suffix = f"  ·  {hint}" if hint else ""
            self.condition_label.config(
                text=view.lock_reason if view.input_locked else f"操作：{self._cue_condition(cue)}{suffix}"
            )
            self.advice_label.config(text=f"OK-WW 建议：{cue.advice}" if cue.advice else "")
            self.segment_label.config(text=f"第 {view.index + 1} / {view.total} 步")
        self.phase_label.config(text="启动轴（仅一次）" if view.phase == "启动" else f"自动循环中  ·  第 {max(1, view.cycle_count)} 轮")
        self.cycle_label.config(text="启动阶段" if view.phase == "启动" else f"第 {max(1, view.cycle_count)} 轮 / ∞")
        self.recognition_rows[0][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        self.recognition_rows[1][1].config(fg=C["green"] if cue and cue.hold_ms else C["dim"])
        self.recognition_rows[2][1].config(fg=C["green"] if view.confidence >= .7 else C["gold"])
        has_state_match = any(matched for _score, matched in self.state_vision_scores.values())
        self.recognition_rows[3][1].config(fg=C["green"] if has_state_match else C["dim"])
        self.recognition_rows[4][1].config(fg=C["green"] if self.engine.team_order_confirmed else C["gold"])
        if hasattr(self, "team_order_label"):
            order_text = "  ·  ".join(f"{index + 1} {name}" for index, name in enumerate(self.engine.team_order))
            prefix = "已识别" if self.engine.team_order_confirmed else "等待确认 · 暂用"
            self.team_order_label.config(
                text=f"队伍位置：{prefix}  {order_text}",
                fg=C["green"] if self.engine.team_order_confirmed else C["gold"],
            )
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
        overlay = self.settings.get("overlay", {})
        scale = self._overlay_scale_value(overlay.get("scale", 1.0))
        self._overlay_draw_scale = scale
        move_mode = bool(overlay.get("move_mode", False))
        mode = str(overlay.get("layout", "horizontal"))
        segments = build_combo_segments(self.engine.sequence_steps(), view.phase)
        plan = plan_combo_map(
            segments, mode,
            max(420, round(self.root.winfo_screenwidth() / scale)),
            max(260, round(self.root.winfo_screenheight() / scale)),
            move_bar_height=30 if move_mode else 0,
        )
        self._resize_battle_overlay(round(plan.width * scale), round(plan.height * scale))

        if move_mode:
            canvas.create_line(8, 30, plan.width - 8, 30, fill="#090B12", width=self._hud_width(4))
            canvas.create_line(8, 30, plan.width - 8, 30, fill=C["purple"], width=self._hud_width(1))
            self._canvas_text_with_halo(
                canvas,
                14, 17, anchor="w",
                text=f"移动模式  ·  {self._overlay_layout_label(mode)}  ·  拖动空白区域定位",
                fill="#E2DAFF", font=self._hud_font("Microsoft YaHei UI", 9, "bold"),
            )
            self._canvas_text_with_halo(
                canvas,
                plan.width - 14, 17, anchor="e", text=f"{view.phase}轴 · 第 {view.index + 1}/{view.total} 步",
                fill=C["muted"], font=self._hud_font("Microsoft YaHei UI", 8),
            )

        self._draw_combo_map_overview(canvas, segments, plan.width, 42 if move_mode else 12)
        for placement in plan.placements:
            segment = segments[placement.segment_index]
            self._draw_combo_map_segment(canvas, segment, placement, view, overlay)

        if plan.hidden_before:
            self._canvas_text_with_halo(
                canvas, 5, plan.height // 2, anchor="w", text=f"‹ {plan.hidden_before}",
                fill=C["muted"], font=self._hud_font("Segoe UI", 9, "bold"),
            )
        if plan.hidden_after:
            self._canvas_text_with_halo(
                canvas, plan.width - 5, plan.height // 2, anchor="e", text=f"{plan.hidden_after} ›",
                fill=C["muted"], font=self._hud_font("Segoe UI", 9, "bold"),
            )
        if scale != 1.0:
            canvas.scale("all", 0, 0, scale, scale)

    def _draw_combo_map_overview(self, canvas: tk.Canvas, segments, width: int, y: int) -> None:
        """Render the entire phase as a quiet node map above the local capsules."""
        if not segments:
            return
        left, right = 52, max(53, width - 52)
        current = current_segment_index(segments)
        canvas.create_line(left, y + 8, right, y + 8, fill="#090B12", width=self._hud_width(5))
        canvas.create_line(left, y + 8, right, y + 8, fill="#71809A", width=self._hud_width(2))
        role_colors = (C["purple"], C["red"], C["blue"])
        for index, segment in enumerate(segments):
            x = left if len(segments) == 1 else left + (right - left) * index / (len(segments) - 1)
            try:
                role_index = self.engine.team_order.index(segment.character)
            except ValueError:
                role_index = 0
            color = role_colors[role_index % len(role_colors)]
            radius = 5 if index == current else 3
            if segment.state == "error":
                color, radius = C["red"], 6
            elif segment.state == "completed":
                color = "#397359"
            canvas.create_oval(x - radius, y + 8 - radius, x + radius, y + 8 + radius,
                               fill=color, outline="#FFFFFF" if index == current else "", width=self._hud_width(2))
        self._canvas_text_with_halo(
            canvas, 12, y + 8, anchor="w",
            text="启动" if segments[0].phase == "启动" else "循环",
            fill=C["gold"] if segments[0].phase == "启动" else C["blue"],
            font=self._hud_font("Microsoft YaHei UI", 8, "bold"),
        )
        self._canvas_text_with_halo(
            canvas, width - 12, y + 8, anchor="e", text=f"段 {current + 1}/{len(segments)}",
            fill="#D6DCE8", font=self._hud_font("Microsoft YaHei UI", 8, "bold"),
        )

    def _draw_combo_map_segment(self, canvas: tk.Canvas, segment, placement, view: EngineView,
                                overlay: dict) -> None:
        x, y, width, height = placement.x, placement.y, placement.width, placement.height
        capsule_left = x + 34
        capsule_top = y + 8
        capsule_bottom = y + 70
        style = {
            "error": (C["red"], "#FFD9DE"),
            "current": ("#F4F0FF", "#FFFFFF"),
            "completed": ("#397359", "#A8C8B9"),
            "upcoming": ("#65738A", "#E9EDF7"),
        }
        outline, text_color = style.get(segment.state, style["upcoming"])
        if segment.state == "current" and view.input_locked:
            outline, text_color = C["gold"], "#FFF4D3"
        # The canvas background is color-keyed by Windows.  Keep every HUD
        # surface unfilled so only portraits, keys, labels and status strokes
        # remain visible over the game.
        canvas.create_polygon(
            self._rounded_rectangle_points(capsule_left, capsule_top, x + width, capsule_bottom, 22),
            smooth=True, splinesteps=24, fill="", outline="#080A10", width=self._hud_width(6),
        )
        canvas.create_polygon(
            self._rounded_rectangle_points(capsule_left, capsule_top, x + width, capsule_bottom, 22),
            smooth=True, splinesteps=24, fill="", outline=outline,
            width=self._hud_width(3 if segment.state in {"current", "error"} else 2),
        )
        accent = C["gold"] if segment.phase == "启动" else C["blue"]
        canvas.create_line(capsule_left + 32, capsule_bottom - 3, x + width - 20, capsule_bottom - 3,
                           fill="#080A10", width=self._hud_width(5))
        canvas.create_line(capsule_left + 32, capsule_bottom - 3, x + width - 20, capsule_bottom - 3,
                           fill=accent, width=self._hud_width(2))

        portrait_center_x, portrait_center_y = x + 43, y + 39
        portrait_size = 64
        canvas.create_oval(portrait_center_x - 35, portrait_center_y - 35,
                           portrait_center_x + 35, portrait_center_y + 35,
                           fill="", outline="#080A10", width=self._hud_width(7))
        canvas.create_oval(portrait_center_x - 35, portrait_center_y - 35,
                           portrait_center_x + 35, portrait_center_y + 35,
                           fill="", outline=outline, width=self._hud_width(3))
        portrait = self._character_photo(
            segment.character, round(portrait_size * self._overlay_draw_scale),
        )
        if portrait:
            canvas.create_image(portrait_center_x, portrait_center_y, image=portrait, anchor="center")
        else:
            self._canvas_text_with_halo(
                canvas, portrait_center_x, portrait_center_y, text=segment.character[:1],
                fill="#FFFFFF", font=self._hud_font("Microsoft YaHei UI", 20, "bold"),
            )

        action_left = x + 88
        available = max(1, width - 100)
        spacing = min(44, available / max(1, len(segment.steps)))
        for index, step in enumerate(segment.steps):
            center_x = action_left + spacing * index + spacing / 2
            cue = step.cue
            action = self.engine.action_for(cue)
            mapping = self.overlay_icon_mappings.get(action) or self.overlay_icon_mappings.get(cue.action)
            photo = self._overlay_icon_photo(
                mapping["icon"], round(28 * self._overlay_draw_scale),
            ) if mapping and overlay.get("show_icons", True) else None
            is_current = step.state in {"current", "error"}
            if is_current:
                key_outline = C["red"] if step.state == "error" else C["gold"] if view.input_locked else "#FFFFFF"
                canvas.create_rectangle(center_x - 18, y + 18, center_x + 18, y + 56,
                                        fill="", outline="#080A10", width=self._hud_width(5))
                canvas.create_rectangle(center_x - 18, y + 18, center_x + 18, y + 56,
                                        fill="", outline=key_outline, width=self._hud_width(2))
            if photo:
                canvas.create_image(center_x, y + 37, image=photo, anchor="center")
            else:
                token = mapping["token"] if mapping else cue.display_key
                self._canvas_text_with_halo(
                    canvas, center_x, y + 37, text=token.upper(), fill=text_color,
                    font=self._hud_font("Microsoft YaHei UI", 17, "bold"),
                )
            self._canvas_text_with_halo(
                canvas, center_x + 15, y + 18, anchor="ne", text=self._overlay_key(cue),
                fill=C["red"] if step.state == "error" else "#F0EBFF",
                font=self._hud_font("Microsoft YaHei UI", 6, "bold"), halo_width=1,
            )

        label = segment.label
        if len(label) > 18:
            label = label[:17] + "…"
        self._canvas_text_with_halo(
            canvas, x + width / 2, y + height - 8, text=label, fill=text_color,
            font=self._hud_font("Microsoft YaHei UI", 10, "bold"), anchor="s",
        )

    @staticmethod
    def _canvas_text_with_halo(canvas: tk.Canvas, x: float, y: float, *, halo_width: int = 2,
                               halo_fill: str = "#080A10", **kwargs) -> int:
        """Draw readable HUD text without introducing an opaque backing panel."""
        for dx, dy in ((-halo_width, 0), (halo_width, 0), (0, -halo_width), (0, halo_width)):
            shadow = dict(kwargs)
            shadow["fill"] = halo_fill
            canvas.create_text(x + dx, y + dy, **shadow)
        return canvas.create_text(x, y, **kwargs)

    @staticmethod
    def _rounded_rectangle_points(x1: float, y1: float, x2: float, y2: float, radius: float) -> tuple[float, ...]:
        radius = max(1.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
        return (
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        )

    @staticmethod
    def _overlay_layout_label(mode: str) -> str:
        return {"horizontal": "横排", "vertical": "竖排", "waterfall": "瀑布流"}.get(mode, "横排")

    def _resize_battle_overlay(self, width: int, height: int) -> None:
        size = (max(220, int(width)), max(90, int(height)))
        if size == self._overlay_size:
            return
        self._overlay_size = size
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        current_x = self.battle_overlay.winfo_x()
        current_y = self.battle_overlay.winfo_y()
        x = min(max(0, current_x), max(0, screen_width - size[0]))
        y = min(max(0, current_y), max(0, screen_height - size[1]))
        self.float_canvas.config(width=size[0], height=size[1])
        self.battle_overlay.geometry(f"{size[0]}x{size[1]}+{x}+{y}")

    def _overlay_key(self, cue: Cue) -> str:
        if cue.action == "basic":
            return "A"
        if cue.action == "heavy":
            return "Z"
        configured = self._configured_key(self.engine.action_for(cue))
        return f"切{configured}" if cue.action.startswith("slot") else configured

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

    def _start_team_order_drag(self, index: int) -> None:
        self._team_order_drag_index = index
        for card_index, card in enumerate(self._team_order_cards):
            card.config(highlightbackground=C["purple"] if card_index == index else C["border"])

    def _finish_team_order_drag(self, event: tk.Event) -> str:
        source = self._team_order_drag_index
        self._team_order_drag_index = None
        if source is None or not self._team_order_cards:
            return "break"
        centers = [card.winfo_rootx() + card.winfo_width() / 2 for card in self._team_order_cards]
        target = min(range(len(centers)), key=lambda index: abs(event.x_root - centers[index]))
        self.engine.move_team_member(source, target)
        self._save_team_order()
        self._refresh_axis_page()
        self._refresh_team_order_editor(force=True)
        return "break"

    def _refresh_team_order_editor(self, *, force: bool = False) -> None:
        if not self._team_order_cards:
            return
        order = tuple(self.engine.team_order)
        if not force and order == self._last_team_order_editor:
            return
        self._last_team_order_editor = order
        for index, character in enumerate(order):
            card = self._team_order_cards[index]
            card.config(highlightbackground=C["border"])
            self._team_order_name_labels[index].config(text=character)
            portrait = self._team_order_portrait_labels[index]
            photo = self._character_photo(character, 42)
            portrait.config(
                image=photo or "", text="" if photo else character[:1],
                font=("Microsoft YaHei UI", 13, "bold"),
                highlightthickness=0 if photo else 1,
                highlightbackground=C["border_hot"],
            )
            portrait.image = photo

    def _draw_action_rule(self, _event=None) -> None:
        c = self.action_rule
        w = max(1, c.winfo_width())
        c.delete("all")
        c.create_line(0, 1, w, 1, fill=C["border"])
        c.create_line(w * .36, 1, w * .64, 1, fill=C["purple"], width=2)
        c.create_oval(w / 2 - 3, -1, w / 2 + 3, 5, fill="#C9B8FF", outline="")

    def _update_preview(self, view: EngineView) -> None:
        upcoming = list(self.engine.cue_window(4)[1:4])
        for index, label in enumerate(self.preview_labels):
            if index < len(upcoming):
                item = upcoming[index]
                label.config(text=f"{self._cue_display(item)}\n{item.character}", fg=C["text"])
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
            text = "✓" if completed else self._cue_display(cue)[:2]
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

    def _preview_overlay_scale(self, _value: str = "") -> None:
        value = self._overlay_scale_value(self.overlay_scale_var.get())
        self.settings.setdefault("overlay", {})["scale"] = value
        self.overlay_scale_value.config(text=f"{value:.0%}")
        self._draw_battle_overlay(self.engine.view())

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
        overlay = self.settings.setdefault("overlay", {})
        overlay["enabled"] = bool(self.overlay_enabled_var.get())
        overlay["move_mode"] = bool(self.overlay_move_var.get())
        overlay["layout"] = self.overlay_layout_var.get() if self.overlay_layout_var.get() in {"horizontal", "vertical", "waterfall"} else "horizontal"
        overlay["scale"] = self._overlay_scale_value(self.overlay_scale_var.get())
        guard = self.settings.setdefault("input_guard", {})
        guard["enabled"] = bool(self.input_guard_enabled_var.get())
        guard["basic_lock_ms"] = max(0, min(500, int(self.basic_lock_var.get())))
        guard["liberation_fallback_ms"] = max(800, min(7000, int(self.liberation_fallback_var.get())))
        self.input_guard.configure(self.settings)
        if not guard["enabled"]:
            self.input_guard.reset()
        self._sync_input_guard()
        self.settings["opacity"] = float(self.opacity_var.get())
        self.settings["game_titles"] = [line.strip() for line in self.title_text.get("1.0", "end").splitlines() if line.strip()]
        self.settings["calibration_completed"] = True
        self.store.save(self.settings)
        self._apply_overlay_interaction_style()
        self._draw_battle_overlay(self.engine.view())
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

    def _pick_video_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="选择教学视频",
            filetypes=(("视频文件", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v"), ("所有文件", "*.*")),
        )
        if path:
            self.video_path_var.set(path)
            self.video_analysis_status.config(text=Path(path).name, fg=C["muted"])

    def _start_video_analysis(self) -> None:
        if self.video_analysis_running:
            return
        video_path = Path(self.video_path_var.get().strip())
        if not video_path.is_file():
            self.video_analysis_status.config(text="视频文件不存在", fg=C["red"])
            return
        ffmpeg = find_ffmpeg(self.ffmpeg_path_var.get().strip())
        if not ffmpeg:
            self.video_analysis_status.config(text="未找到 ffmpeg.exe", fg=C["red"])
            return
        bounds = {name: float(variable.get()) for name, variable in self.video_bounds_vars.items()}
        cycle_start_ms = max(0, int(self.video_cycle_start_var.get()))
        config = self.settings.setdefault("video_recognition", {})
        config.update({
            "video_path": str(video_path), "ffmpeg_path": str(ffmpeg), "fps": 30,
            "cycle_start_ms": cycle_start_ms, "bounds_percent": bounds,
        })
        self.store.save(self.settings)
        self.video_analysis_running = True
        self.video_analyze_button.config(state="disabled", text="正在识别…")
        self.video_analysis_status.config(text="正在读取视频帧…", fg=C["gold"])
        threading.Thread(
            target=self._run_video_analysis,
            args=(video_path, ffmpeg, bounds, cycle_start_ms),
            name="video-key-recognition", daemon=True,
        ).start()

    def _run_video_analysis(self, video_path: Path, ffmpeg: Path, bounds: dict[str, float], cycle_start_ms: int) -> None:
        try:
            events = analyze_video_key_panel(
                video_path, ffmpeg, bounds, fps=30,
                on_progress=lambda frames: self.events.put(("video_analysis", ("progress", f"已分析 {frames} 帧"))),
            )
            safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", video_path.stem).strip("-") or "video"
            output = self.store.root / "video-analysis" / f"{safe_name}.candidate.json"
            export_candidate_timeline(
                output, video_path, events, self.engine.team_order, self.overlay_icon_mappings,
                cycle_start_ms=cycle_start_ms,
            )
            self.events.put(("video_analysis", ("done", f"识别 {len(events)} 个候选动作 · {output.name}")))
        except Exception as exc:
            self.events.put(("video_analysis", ("error", f"识别失败：{exc}")))

    def _open_video_analysis_dir(self) -> None:
        path = self.store.root / "video-analysis"
        path.mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            self.video_analysis_status.config(text=f"打开失败：{exc}", fg=C["red"])

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

    def _install_bundled_state_templates(self) -> None:
        installed = install_bundled_state_templates(self.store.templates_dir)
        if not installed:
            return
        state = self.settings.setdefault("state_vision", {})
        existing = state.get("signals", {})
        state["signals"] = {**installed, **existing}
        state["enabled"] = True
        self.settings["vision_enabled"] = True
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

    def _main_window_handle(self) -> int:
        import ctypes

        self.root.update_idletasks()
        child = int(self.root.winfo_id())
        hwnd = int(ctypes.windll.user32.GetAncestor(child, 2))
        return hwnd or child

    def _apply_taskbar_style(self) -> bool:
        """Expose the custom-framed dashboard as a normal Windows app window."""
        try:
            import ctypes

            hwnd = self._main_window_handle()
            user32 = ctypes.windll.user32
            style = int(user32.GetWindowLongW(hwnd, -20))
            style = (style & ~0x00000080) | 0x00040000  # remove TOOLWINDOW, add APPWINDOW
            user32.SetWindowLongW(hwnd, -20, style)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)  # FRAMECHANGED without move/resize/activate
            return True
        except Exception:
            return False

    def _register_taskbar_window(self) -> None:
        if not self._apply_taskbar_style():
            return
        # Re-show once after changing the native style so Explorer creates the taskbar button.
        self.root.withdraw()
        self.root.after(20, self._restore_after_taskbar_registration)

    def _restore_after_taskbar_registration(self) -> None:
        self.root.deiconify()
        self._apply_taskbar_style()
        self.root.lift()

    def _minimize_to_taskbar(self) -> None:
        try:
            import ctypes

            ctypes.windll.user32.ShowWindow(self._main_window_handle(), 6)  # SW_MINIMIZE
        except Exception:
            self.root.iconify()

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin:
            self.root.geometry(f"+{event.x_root - self._drag_origin[0]}+{event.y_root - self._drag_origin[1]}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._drag_origin = None

    def _start_overlay_drag(self, event: tk.Event) -> None:
        if not self.settings.get("overlay", {}).get("move_mode", False):
            return
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

    def _set_overlay_layout(self, mode: str) -> None:
        if mode not in {"horizontal", "vertical", "waterfall"}:
            return
        self.settings.setdefault("overlay", {})["layout"] = mode
        if hasattr(self, "overlay_layout_var"):
            self.overlay_layout_var.set(mode)
        self.store.save(self.settings)
        self._draw_battle_overlay(self.engine.view())

    def _toggle_overlay_move_mode(self) -> None:
        overlay = self.settings.setdefault("overlay", {})
        overlay["move_mode"] = not bool(overlay.get("move_mode", False))
        if hasattr(self, "overlay_move_var"):
            self.overlay_move_var.set(overlay["move_mode"])
        self.store.save(self.settings)
        self._apply_overlay_interaction_style()
        self._draw_battle_overlay(self.engine.view())

    def hide_overlay(self) -> None:
        self.root.withdraw()

    def show_overlay(self) -> None:
        self.force_visible = True
        self.root.deiconify()
        self.root.after_idle(self._apply_taskbar_style)
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
                pystray.MenuItem("切换悬浮窗移动模式", lambda: self.events.put(("command", "toggle_move"))),
                pystray.MenuItem("横排布局", lambda: self.events.put(("command", "layout:horizontal"))),
                pystray.MenuItem("竖排布局", lambda: self.events.put(("command", "layout:vertical"))),
                pystray.MenuItem("瀑布流布局", lambda: self.events.put(("command", "layout:waterfall"))),
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
        if self.team_vision_monitor:
            self.team_vision_monitor.stop()
        if self._tray:
            self._tray.stop()
        self.store.save(self.settings)
        self.root.destroy()
