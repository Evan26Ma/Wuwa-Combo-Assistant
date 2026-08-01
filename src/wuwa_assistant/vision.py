from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from pathlib import Path


def _safe_name(signal: str) -> str:
    digest = hashlib.sha1(signal.encode("utf-8")).hexdigest()[:12]
    return f"template-{digest}.png"


def image_similarity(first, second) -> float:
    """Return a conservative 0..1 luminance similarity for equal-sized PIL images."""
    from PIL import ImageChops, ImageStat

    left = first.convert("L")
    right = second.convert("L")
    if right.size != left.size:
        right = right.resize(left.size)
    rms = ImageStat.Stat(ImageChops.difference(left, right)).rms[0]
    return max(0.0, min(1.0, 1.0 - (float(rms) / 255.0)))


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
        return self.templates_dir / _safe_name(signal)

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
