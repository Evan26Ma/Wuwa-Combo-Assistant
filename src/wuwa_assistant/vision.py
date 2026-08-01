from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from itertools import permutations
from pathlib import Path


OKWW_SIGNAL_CATEGORIES = {
    "character:卡提希娅": ("char_cartethyia", "卡提希娅角色", 0.86),
    "character:夏空": ("char_ciaccona", "夏空角色", 0.86),
    "character:秧秧": ("yangyang_sp", "秧秧角色", 0.86),
    "character:穗穗": ("char_suisui", "穗穗角色", 0.86),
    "character:千咲": ("char_chisa", "千咲角色", 0.86),
    "cartethyia:small": ("forte_cartethyia_sword3", "小卡提形态", 0.82),
    "cartethyia:sword1": ("forte_cartethyia_sword1", "卡提第一把剑", 0.86),
    "cartethyia:sword2": ("forte_cartethyia_sword2", "卡提第二把剑", 0.86),
    "cartethyia:sword3": ("forte_cartethyia_sword3", "卡提第三把剑", 0.86),
    "cartethyia:mid_air": ("forte_cartethyia_space", "卡提空中攻击", 0.84),
    "cartethyia:lib_big": ("lib_cartethyia_big", "芙露德莉斯终结大招", 0.86),
    "suisui:forte3": ("suisui_forte3", "穗穗 Forte3", 0.84),
}

BUNDLED_SIGNAL_ROIS = {
    "character:卡提希娅": [0.9236979167, 0.2152777778, 0.0239583333, 0.0425925926],
    "character:夏空": [0.92265625, 0.2092592593, 0.0234375, 0.0416666667],
    "character:秧秧": [0.9239583333, 0.2101851852, 0.0208333333, 0.05],
    "character:穗穗": [0.9234375, 0.2138888889, 0.0223958333, 0.0370370370],
    "character:千咲": [0.9244791667, 0.2115740741, 0.0221354167, 0.0314814815],
    "cartethyia:small": [0.5385416667, 0.9171296296, 0.0114583333, 0.0115740741],
    "cartethyia:sword1": [0.4411458333, 0.9166666667, 0.0109375, 0.0217592593],
    "cartethyia:sword2": [0.4893229167, 0.9185185185, 0.0122395833, 0.0180555556],
    "cartethyia:sword3": [0.5385416667, 0.9171296296, 0.0114583333, 0.0194444444],
    "cartethyia:mid_air": [0.5979166667, 0.9222222222, 0.0166666667, 0.0115740741],
    "cartethyia:lib_big": [0.9354166667, 0.8740740741, 0.0229166667, 0.0388888889],
    "suisui:forte3": [0.5395833333, 0.9083333333, 0.0088541667, 0.0203703704],
}

OKWW_PORTRAIT_CATEGORIES = {
    "卡提希娅": "char_cartethyia",
    "夏空": "char_ciaccona",
    "千咲": "char_chisa",
    "秧秧": "yangyang_sp",
    "穗穗": "char_suisui",
}

BUNDLED_PORTRAIT_FILES = {
    "卡提希娅": "cartethyia.png",
    "夏空": "ciaccona.png",
    "千咲": "chisa.png",
    "秧秧": "yangyang-sp.png",
    "穗穗": "suisui.png",
}

CHARACTER_SIGNALS = {
    "卡提希娅": "character:卡提希娅",
    "夏空": "character:夏空",
    "千咲": "character:千咲",
    "秧秧": "character:秧秧",
    "穗穗": "character:穗穗",
}

# Normalized from OK-WW's box_char_1 / box_char_2 / box_char_3 annotations.
TEAM_SLOT_BOXES = (
    (0.9154, 0.1935, 0.0340, 0.0727),
    (0.9154, 0.3176, 0.0340, 0.0699),
    (0.9156, 0.4417, 0.0346, 0.0690),
)


def _safe_name(signal: str) -> str:
    digest = hashlib.sha1(signal.encode("utf-8")).hexdigest()[:12]
    return f"template-{digest}.png"


def template_path(templates_dir: Path, signal: str) -> Path:
    return templates_dir / _safe_name(signal)


def bundled_portrait_paths() -> dict[str, Path]:
    directory = Path(__file__).resolve().parent / "assets" / "portraits"
    return {
        name: directory / filename
        for name, filename in BUNDLED_PORTRAIT_FILES.items()
        if (directory / filename).exists()
    }


def install_bundled_state_templates(templates_dir: Path) -> dict[str, dict]:
    """Install packaged OK-WW crops into the writable per-user template directory."""
    import shutil

    source_dir = Path(__file__).resolve().parent / "assets" / "state_templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    installed: dict[str, dict] = {}
    for signal, (_category, label, threshold) in OKWW_SIGNAL_CATEGORIES.items():
        source = template_path(source_dir, signal)
        ratio = BUNDLED_SIGNAL_ROIS.get(signal)
        if not source.exists() or not ratio:
            continue
        destination = template_path(templates_dir, signal)
        if not destination.exists():
            shutil.copy2(source, destination)
        installed[signal] = {
            "label": label,
            "enabled": True,
            "threshold": threshold,
            "roi_ratio": list(ratio),
            "source": "bundled OK-WW template",
        }
    return installed


def _find_okww_repo(root: Path) -> Path:
    candidates = (
        root,
        root / "repo",
        root / "data" / "apps" / "ok-ww" / "repo",
        root / "data" / "apps" / "ok-ww" / "working",
    )
    for candidate in candidates:
        if (candidate / "assets" / "coco_annotations.json").exists():
            return candidate
    raise FileNotFoundError("未在所选目录找到 OK-WW 的 assets/coco_annotations.json")


def import_okww_portraits(okww_root: Path, assets_dir: Path) -> dict[str, Path]:
    """Create local UI portrait crops without redistributing OK-WW source assets."""
    from PIL import Image

    repo = _find_okww_repo(okww_root)
    data = json.loads((repo / "assets" / "coco_annotations.json").read_text(encoding="utf-8"))
    categories = {item["name"]: item["id"] for item in data.get("categories", [])}
    images = {item["id"]: item for item in data.get("images", [])}
    wanted = {name: categories.get(category) for name, category in OKWW_PORTRAIT_CATEGORIES.items()}
    best: dict[int, dict] = {}
    for annotation in data.get("annotations", []):
        category_id = annotation.get("category_id")
        if category_id not in wanted.values():
            continue
        area = float(annotation["bbox"][2]) * float(annotation["bbox"][3])
        current = best.get(category_id)
        if current is None or area > float(current["bbox"][2]) * float(current["bbox"][3]):
            best[category_id] = annotation

    assets_dir.mkdir(parents=True, exist_ok=True)
    imported: dict[str, Path] = {}
    opened: dict[Path, Image.Image] = {}
    try:
        for name, category_id in wanted.items():
            annotation = best.get(category_id) if category_id is not None else None
            if not annotation:
                continue
            image_info = images.get(annotation["image_id"])
            if not image_info:
                continue
            source = repo / "assets" / image_info["file_name"]
            if source not in opened:
                opened[source] = Image.open(source).convert("RGB")
            image = opened[source]
            x, y, width, height = (int(round(value)) for value in annotation["bbox"])
            side = max(width, height)
            center_x, center_y = x + width // 2, y + height // 2
            left = max(0, min(image.width - side, center_x - side // 2))
            top = max(0, min(image.height - side, center_y - side // 2))
            crop = image.crop((left, top, left + side, top + side)).resize((192, 192), Image.Resampling.LANCZOS)
            destination = assets_dir / f"portrait-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}.png"
            crop.save(destination, optimize=True)
            imported[name] = destination
    finally:
        for image in opened.values():
            image.close()
    if not imported:
        raise ValueError("OK-WW 标注文件中没有找到支持的角色头像")
    return imported


def import_okww_templates(okww_root: Path, templates_dir: Path) -> dict[str, dict]:
    """Import locally installed OK-WW crops without bundling its AGPL assets."""
    from PIL import Image

    repo = _find_okww_repo(okww_root)
    annotations_path = repo / "assets" / "coco_annotations.json"
    data = json.loads(annotations_path.read_text(encoding="utf-8"))
    categories = {item["name"]: item["id"] for item in data.get("categories", [])}
    images = {item["id"]: item for item in data.get("images", [])}
    wanted_ids = {category: categories.get(category) for category, _, _ in OKWW_SIGNAL_CATEGORIES.values()}
    by_category: dict[int, dict] = {}
    for annotation in data.get("annotations", []):
        category_id = annotation.get("category_id")
        if category_id in wanted_ids.values() and category_id not in by_category:
            by_category[category_id] = annotation

    templates_dir.mkdir(parents=True, exist_ok=True)
    imported: dict[str, dict] = {}
    opened: dict[Path, Image.Image] = {}
    try:
        for signal, (category, label, threshold) in OKWW_SIGNAL_CATEGORIES.items():
            category_id = wanted_ids.get(category)
            annotation = by_category.get(category_id) if category_id is not None else None
            if not annotation:
                continue
            image_info = images.get(annotation["image_id"])
            if not image_info:
                continue
            source = repo / "assets" / image_info["file_name"]
            if source not in opened:
                opened[source] = Image.open(source).convert("RGB")
            x, y, width, height = (int(round(value)) for value in annotation["bbox"])
            if signal == "cartethyia:small":
                height = max(1, int(height * 0.6))
            crop = opened[source].crop((x, y, x + width, y + height))
            crop.save(template_path(templates_dir, signal))
            imported[signal] = {
                "label": label,
                "enabled": True,
                "threshold": threshold,
                "roi_ratio": [
                    x / float(image_info["width"]), y / float(image_info["height"]),
                    width / float(image_info["width"]), height / float(image_info["height"]),
                ],
                "source": "OK-WW local assets",
            }
    finally:
        for image in opened.values():
            image.close()
    if not imported:
        raise ValueError("OK-WW 标注文件中没有找到支持的角色 HUD 模板")
    return imported


def image_similarity(first, second) -> float:
    """Return a conservative 0..1 luminance similarity for equal-sized PIL images."""
    from PIL import ImageChops, ImageStat

    left = first.convert("L")
    right = second.convert("L")
    if right.size != left.size:
        right = right.resize(left.size)
    rms = ImageStat.Stat(ImageChops.difference(left, right)).rms[0]
    return max(0.0, min(1.0, 1.0 - (float(rms) / 255.0)))


def state_image_similarity(first, second) -> float:
    """Blend luminance, color and edge similarity for tiny fixed-position HUD crops."""
    from PIL import ImageChops, ImageFilter, ImageStat

    right = second.convert("RGB")
    left = first.convert("RGB").resize(right.size)
    color_rms = sum(ImageStat.Stat(ImageChops.difference(left, right)).rms) / 3
    color_score = 1.0 - color_rms / 255.0
    gray_score = image_similarity(left, right)
    left_edge = left.convert("L").filter(ImageFilter.FIND_EDGES)
    right_edge = right.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_score = image_similarity(left_edge, right_edge)
    return max(0.0, min(1.0, gray_score * 0.45 + color_score * 0.25 + edge_score * 0.30))


class VisionMonitor:
    """Conservative ROI template matcher. Signals never gate input progression."""

    def __init__(
        self,
        templates_dir: Path,
        settings: dict,
        expected_signal: Callable[[], str],
        callback: Callable[[str, float], None],
    ) -> None:
        self.templates_dir = templates_dir
        self.settings = settings
        self.expected_signal = expected_signal
        self.callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def available() -> bool:
        try:
            import mss  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except ImportError:
            return False

    def start(self) -> None:
        if not self.available() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def template_path(self, signal: str) -> Path:
        return template_path(self.templates_dir, signal)

    def capture_template(self, signal: str) -> Path:
        import mss
        from PIL import Image

        self.templates_dir.mkdir(parents=True, exist_ok=True)
        roi = self.settings["vision"]["roi"]
        with mss.mss() as capture:
            frame = capture.grab({k: int(roi[k]) for k in ("left", "top", "width", "height")})
        path = self.template_path(signal)
        Image.frombytes("RGB", frame.size, frame.rgb).save(path)
        return path

    def _run(self) -> None:
        import mss
        from PIL import Image

        last_signal = ""
        while not self._stop.is_set():
            signal = self.expected_signal()
            if not signal:
                if last_signal:
                    self.callback("", 0.0)
                    last_signal = ""
                time.sleep(0.25)
                continue
            path = self.template_path(signal)
            if not path.exists():
                self.callback(signal, -1.0)
                time.sleep(0.4)
                continue
            try:
                template = Image.open(path).convert("L")
            except OSError:
                self.callback(signal, -1.0)
                time.sleep(0.4)
                continue
            roi = self.settings["vision"]["roi"]
            try:
                with mss.mss() as capture:
                    frame = capture.grab({k: int(roi[k]) for k in ("left", "top", "width", "height")})
                gray = Image.frombytes("RGB", frame.size, frame.rgb).convert("L")
                score = image_similarity(gray, template)
                self.callback(signal, max(0.0, min(1.0, score)))
                last_signal = signal
            except Exception:
                self.callback(signal, -2.0)
            time.sleep(0.25)


class StateVisionMonitor:
    """Cycles through optional character HUD signals; results never gate inputs."""

    def __init__(self, templates_dir: Path, settings: dict,
                 callback: Callable[[str, float, bool], None],
                 enabled: Callable[[], bool] | None = None) -> None:
        self.templates_dir = templates_dir
        self.settings = settings
        self.callback = callback
        self.enabled = enabled or (lambda: True)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._streaks: dict[str, int] = {}

    def start(self) -> None:
        if not VisionMonitor.available() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="state-vision-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    @staticmethod
    def _roi(config: dict, monitor: dict) -> dict[str, int]:
        left, top, width, height = (float(value) for value in config["roi_ratio"])
        return {
            "left": int(monitor["left"] + left * monitor["width"]),
            "top": int(monitor["top"] + top * monitor["height"]),
            "width": max(1, int(width * monitor["width"])),
            "height": max(1, int(height * monitor["height"])),
        }

    def _run(self) -> None:
        import mss
        from PIL import Image

        while not self._stop.is_set():
            configs = self.settings.get("state_vision", {}).get("signals", {})
            available = [
                (signal, config) for signal, config in configs.items()
                if config.get("enabled") and config.get("roi_ratio") and template_path(self.templates_dir, signal).exists()
            ]
            if not available or not self.enabled():
                self._stop.wait(0.35)
                continue
            try:
                with mss.mss() as capture:
                    monitor_index = int(self.settings.get("vision", {}).get("monitor_index", 1))
                    monitor_index = max(1, min(monitor_index, len(capture.monitors) - 1))
                    monitor = capture.monitors[monitor_index]
                    for signal, config in available:
                        if self._stop.is_set() or not self.enabled():
                            break
                        try:
                            frame = capture.grab(self._roi(config, monitor))
                            current = Image.frombytes("RGB", frame.size, frame.rgb)
                            with Image.open(template_path(self.templates_dir, signal)) as source:
                                score = state_image_similarity(current, source)
                            threshold = float(config.get("threshold", 0.82))
                            if score >= threshold:
                                self._streaks[signal] = self._streaks.get(signal, 0) + 1
                            else:
                                self._streaks[signal] = 0
                            self.callback(signal, score, self._streaks[signal] >= 2)
                        except Exception:
                            self.callback(signal, -2.0, False)
                        if self._stop.wait(0.07):
                            break
            except Exception:
                self._stop.wait(0.4)


class TeamVisionMonitor:
    """Identify all three right-side party slots using OK-WW character crops."""

    def __init__(self, templates_dir: Path, settings: dict,
                 expected_team: Callable[[], tuple[str, str, str]],
                 callback: Callable[[tuple[str, str, str], dict[str, float], bool], None],
                 enabled: Callable[[], bool] | None = None) -> None:
        self.templates_dir = templates_dir
        self.settings = settings
        self.expected_team = expected_team
        self.callback = callback
        self.enabled = enabled or (lambda: True)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_order: tuple[str, str, str] | None = None
        self._streak = 0

    def start(self) -> None:
        if not VisionMonitor.available() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="team-vision-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    @staticmethod
    def _box_roi(monitor: dict, slot_index: int) -> dict[str, int]:
        left, top, width, height = TEAM_SLOT_BOXES[slot_index]
        return {
            "left": int(monitor["left"] + left * monitor["width"]),
            "top": int(monitor["top"] + top * monitor["height"]),
            "width": max(1, int(width * monitor["width"])),
            "height": max(1, int(height * monitor["height"])),
        }

    @staticmethod
    def _best_box_score(slot_image, template, target_size: tuple[int, int]) -> float:
        """Search a tight character feature inside one OK-WW party-slot box."""
        target_width = max(1, min(slot_image.width, int(target_size[0])))
        target_height = max(1, min(slot_image.height, int(target_size[1])))
        feature = template.convert("RGB").resize((target_width, target_height))
        max_x = max(0, slot_image.width - target_width)
        max_y = max(0, slot_image.height - target_height)
        step_x = max(1, target_width // 8)
        step_y = max(1, target_height // 8)
        xs = list(range(0, max_x + 1, step_x))
        ys = list(range(0, max_y + 1, step_y))
        if not xs or xs[-1] != max_x:
            xs.append(max_x)
        if not ys or ys[-1] != max_y:
            ys.append(max_y)
        best = 0.0
        best_xy = (0, 0)
        for y in ys:
            for x in xs:
                candidate = slot_image.crop((x, y, x + target_width, y + target_height))
                score = state_image_similarity(candidate, feature)
                if score > best:
                    best = score
                    best_xy = (x, y)
        center_x, center_y = best_xy
        for y in range(max(0, center_y - step_y), min(max_y, center_y + step_y) + 1):
            for x in range(max(0, center_x - step_x), min(max_x, center_x + step_x) + 1):
                candidate = slot_image.crop((x, y, x + target_width, y + target_height))
                best = max(best, state_image_similarity(candidate, feature))
        return best

    @staticmethod
    def best_order(team: tuple[str, str, str], scores: dict[tuple[int, str], float]
                   ) -> tuple[tuple[str, str, str], dict[str, float], float]:
        ranked: list[tuple[float, tuple[str, str, str]]] = []
        for order in permutations(team):
            ranked.append((sum(scores.get((slot, character), 0.0) for slot, character in enumerate(order)), order))
        ranked.sort(reverse=True)
        best_total, best = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        chosen = {f"slot{slot + 1}": scores.get((slot, character), 0.0) for slot, character in enumerate(best)}
        return best, chosen, best_total - runner_up

    def _run(self) -> None:
        import mss
        from PIL import Image

        while not self._stop.is_set():
            team = tuple(self.expected_team())
            configs = self.settings.get("state_vision", {}).get("signals", {})
            signals = {name: CHARACTER_SIGNALS.get(name, "") for name in team}
            ready = all(
                signal and configs.get(signal, {}).get("enabled")
                and configs.get(signal, {}).get("roi_ratio")
                and template_path(self.templates_dir, signal).exists()
                for signal in signals.values()
            )
            if len(team) != 3 or not ready or not self.enabled():
                self._stop.wait(0.5)
                continue
            try:
                with mss.mss() as capture:
                    monitor_index = int(self.settings.get("vision", {}).get("monitor_index", 1))
                    monitor_index = max(1, min(monitor_index, len(capture.monitors) - 1))
                    monitor = capture.monitors[monitor_index]
                    templates = {
                        name: Image.open(template_path(self.templates_dir, signal)).convert("RGB")
                        for name, signal in signals.items()
                    }
                    try:
                        scores: dict[tuple[int, str], float] = {}
                        slot_images = []
                        for slot in range(3):
                            frame = capture.grab(self._box_roi(monitor, slot))
                            slot_images.append(Image.frombytes("RGB", frame.size, frame.rgb))
                        for slot, slot_image in enumerate(slot_images):
                            for name, signal in signals.items():
                                _left, _top, width, height = configs[signal]["roi_ratio"]
                                target_size = (int(float(width) * monitor["width"]),
                                               int(float(height) * monitor["height"]))
                                scores[(slot, name)] = self._best_box_score(
                                    slot_image, templates[name], target_size
                                )
                    finally:
                        for image in templates.values():
                            image.close()
                order, chosen, margin = self.best_order(team, scores)
                minimum = min(chosen.values())
                average = sum(chosen.values()) / 3
                confident = minimum >= 0.74 and average >= 0.80 and margin >= 0.08
                if confident and order == self._last_order:
                    self._streak += 1
                elif confident:
                    self._last_order = order
                    self._streak = 1
                else:
                    self._last_order = None
                    self._streak = 0
                self.callback(order, chosen, self._streak >= 2)
            except Exception:
                self._last_order = None
                self._streak = 0
            self._stop.wait(0.45)
