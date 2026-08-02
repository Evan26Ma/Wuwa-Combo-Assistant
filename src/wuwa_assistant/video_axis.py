from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np


CANVAS_WIDTH = 620
CANVAS_HEIGHT = 514


@dataclass(frozen=True)
class Hotspot:
    id: str
    action: str
    x_percent: float
    y_percent: float
    radius_percent: float
    hold_action: str = ""
    hold_threshold_ms: int = 0
    merge_repeated_hold: bool = False
    preserve_tap_gaps: bool = False
    sensitivity: float = 1.0


@dataclass(frozen=True)
class FrameSample:
    active: bool
    weak_active: bool
    confidence: float


@dataclass(frozen=True)
class VideoKeyEvent:
    hotspot_id: str
    action: str
    start_ms: int
    duration_ms: int
    confidence: float


# Percent positions match wwcombo's public keyboard mapping panel.
DEFAULT_HOTSPOTS = (
    Hotspot("switch-1", "slot1", 16.37, 18.77, 5.56, sensitivity=.68),
    Hotspot("switch-2", "slot2", 34.27, 18.77, 5.56, sensitivity=.68),
    Hotspot("switch-3", "slot3", 51.53, 18.77, 5.56, sensitivity=.68),
    Hotspot("basic", "basic", 19.27, 45.33, 8.84, "heavy", 200, False, True),
    Hotspot("jump", "jump", 43.23, 52.92, 6.21),
    Hotspot("utility", "utility", 63.23, 52.82, 6.21),
    Hotspot("dodge", "dodge", 19.27, 78.02, 8.84),
    Hotspot("skill", "skill", 42.90, 77.72, 6.21, "skill", 300, True),
    Hotspot("liberation", "liberation", 63.23, 77.72, 6.21, "liberation", 300, True),
    Hotspot("echo", "echo", 83.71, 77.63, 6.21, "echo", 300, True),
)


def is_recognition_cyan(frame: np.ndarray) -> np.ndarray:
    red = frame[..., 0].astype(np.int16)
    green = frame[..., 1].astype(np.int16)
    blue = frame[..., 2].astype(np.int16)
    return (green > 110) & (blue > 110) & (np.minimum(green - red, blue - red) > 35) & (np.abs(green - blue) < 105)


def _hotspot_masks(hotspot: Hotspot) -> tuple[slice, slice, np.ndarray, np.ndarray]:
    x = hotspot.x_percent / 100 * CANVAS_WIDTH
    y = hotspot.y_percent / 100 * CANVAS_HEIGHT
    radius = max(3.0, hotspot.radius_percent / 100 * CANVAS_WIDTH)
    outer_inner = radius + max(radius * .18, 2.0)
    outer_radius = radius + max(radius * .55, 4.0)
    left = max(0, int(np.floor(x - outer_radius)))
    right = min(CANVAS_WIDTH, int(np.ceil(x + outer_radius)) + 1)
    top = max(0, int(np.floor(y - outer_radius)))
    bottom = min(CANVAS_HEIGHT, int(np.ceil(y + outer_radius)) + 1)
    grid_y, grid_x = np.ogrid[top:bottom, left:right]
    distance = (grid_x - x) ** 2 + (grid_y - y) ** 2
    inner = distance <= radius ** 2
    outer = (distance >= outer_inner ** 2) & (distance <= outer_radius ** 2)
    return slice(top, bottom), slice(left, right), inner, outer


def measure_hotspot(frame: np.ndarray, hotspot: Hotspot, masks=None) -> FrameSample:
    y_slice, x_slice, inner, outer = masks or _hotspot_masks(hotspot)
    cyan = is_recognition_cyan(frame[y_slice, x_slice])
    inner_ratio = float(cyan[inner].mean()) if inner.any() else 0.0
    outer_ratio = float(cyan[outer].mean()) if outer.any() else 0.0
    contrast = inner_ratio - outer_ratio
    confidence = min(1.0, max(0.0, inner_ratio * .6 + max(0.0, contrast) * .4))
    sensitivity = min(1.0, max(.65, hotspot.sensitivity))
    return FrameSample(
        active=inner_ratio >= .34 * sensitivity and contrast >= .14 * sensitivity and confidence >= .26 * sensitivity,
        weak_active=inner_ratio >= .24 * sensitivity and contrast >= .08 * sensitivity and confidence >= .18 * sensitivity,
        confidence=confidence,
    )


def recognition_runs(samples: list[FrameSample], fps: int, *, merge_repeated_hold: bool, preserve_tap_gaps: bool) -> list[tuple[int, int, float]]:
    if not samples or fps <= 0:
        return []
    active = [sample.active for sample in samples]
    confidence = [sample.confidence for sample in samples]
    tracking = False
    for index, sample in enumerate(samples):
        if sample.active:
            tracking = True
        elif tracking and sample.weak_active:
            active[index] = True
        else:
            tracking = False
    max_hole = 0 if preserve_tap_gaps else max(1, int(np.ceil(fps * .05))) if merge_repeated_hold else 1
    index = 0
    while index < len(active):
        if active[index]:
            index += 1
            continue
        start = index
        while index < len(active) and not active[index]:
            index += 1
        if start > 0 and index < len(active) and index - start <= max_hole and active[start - 1] and active[index]:
            for gap_index in range(start, index):
                active[gap_index] = True
                confidence[gap_index] = (confidence[start - 1] + confidence[index]) / 2
    runs: list[tuple[int, int, float]] = []
    index = 0
    while index < len(active):
        if not active[index]:
            index += 1
            continue
        start = index
        while index < len(active) and active[index]:
            index += 1
        if index - start >= 2:
            runs.append((start, index, sum(confidence[start:index]) / (index - start)))
    if merge_repeated_hold and len(runs) >= 3:
        merged: list[tuple[int, int, float]] = []
        run_index = 0
        max_gap = max(1, int(np.ceil(fps * .4)))
        minimum_hold = max(2, int(np.ceil(fps * .3)))
        while run_index < len(runs):
            group_start = run_index
            run_index += 1
            while run_index < len(runs) and runs[run_index][0] - runs[run_index - 1][1] <= max_gap:
                run_index += 1
            group = runs[group_start:run_index]
            span = group[-1][1] - group[0][0]
            if len(group) >= 3 and span >= minimum_hold:
                frames = sum(end - start for start, end, _score in group)
                score = sum(score * (end - start) for start, end, score in group) / max(1, frames)
                merged.append((group[0][0], group[-1][1], score))
            else:
                merged.extend(group)
        runs = merged
    return runs


def find_ffmpeg(configured: str = "") -> Path | None:
    system_ffmpeg = shutil.which("ffmpeg")
    candidates = [
        Path(configured) if configured else None,
        Path(r"F:\GAM3\wwcombo 正式版 0.6 便携版\wwcombo 正式版 0.6 便携版\ffmpeg.exe"),
        Path(system_ffmpeg) if system_ffmpeg else None,
    ]
    return next((path for path in candidates if path and path.is_file()), None)


def _read_exact(stream, size: int) -> bytes:
    """Read one complete raw-video frame from a pipe.

    Pipe reads are allowed to return fewer bytes than requested even when more
    data is on the way, so a single ``read(size)`` is not a frame boundary.
    """
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def analyze_video_key_panel(
    video_path: Path,
    ffmpeg_path: Path,
    bounds_percent: dict[str, float],
    *,
    fps: int = 30,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[VideoKeyEvent, ...]:
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    fps = max(10, min(60, int(fps)))
    x = max(0.0, min(100.0, float(bounds_percent.get("x", 0))))
    y = max(0.0, min(100.0, float(bounds_percent.get("y", 0))))
    width = max(4.0, min(100.0 - x, float(bounds_percent.get("width", 26))))
    height = max(4.0, min(100.0 - y, float(bounds_percent.get("height", 22))))
    crop = (
        f"crop=trunc(iw*{width / 100:.8f}/2)*2:trunc(ih*{height / 100:.8f}/2)*2:"
        f"trunc(iw*{x / 100:.8f}/2)*2:trunc(ih*{y / 100:.8f}/2)*2,"
        f"scale={CANVAS_WIDTH}:{CANVAS_HEIGHT},fps={fps}"
    )
    command = [
        str(ffmpeg_path), "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-vf", crop, "-an", "-sn", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.stdout is None:
        raise RuntimeError("无法读取 ffmpeg 输出")
    frame_bytes = CANVAS_WIDTH * CANVAS_HEIGHT * 3
    samples = {hotspot.id: [] for hotspot in DEFAULT_HOTSPOTS}
    masks = {hotspot.id: _hotspot_masks(hotspot) for hotspot in DEFAULT_HOTSPOTS}
    frame_index = 0
    while True:
        payload = _read_exact(process.stdout, frame_bytes)
        if not payload:
            break
        if len(payload) != frame_bytes:
            process.kill()
            raise RuntimeError("视频帧数据不完整")
        frame = np.frombuffer(payload, dtype=np.uint8).reshape((CANVAS_HEIGHT, CANVAS_WIDTH, 3))
        for hotspot in DEFAULT_HOTSPOTS:
            samples[hotspot.id].append(measure_hotspot(frame, hotspot, masks[hotspot.id]))
        frame_index += 1
        if on_progress and frame_index % max(1, fps) == 0:
            on_progress(frame_index)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    code = process.wait()
    if code != 0:
        raise RuntimeError(stderr.strip() or f"ffmpeg 退出码 {code}")
    events: list[VideoKeyEvent] = []
    for hotspot in DEFAULT_HOTSPOTS:
        for start, end, confidence in recognition_runs(
            samples[hotspot.id], fps,
            merge_repeated_hold=hotspot.merge_repeated_hold,
            preserve_tap_gaps=hotspot.preserve_tap_gaps,
        ):
            duration = round((end - start) * 1000 / fps)
            action = hotspot.hold_action if hotspot.hold_action and duration >= hotspot.hold_threshold_ms else hotspot.action
            events.append(VideoKeyEvent(
                hotspot_id=hotspot.id,
                action=action,
                start_ms=round(start * 1000 / fps),
                duration_ms=duration,
                confidence=round(confidence, 4),
            ))
    events.sort(key=lambda event: (event.start_ms, event.hotspot_id))
    return tuple(events)


def export_candidate_timeline(
    path: Path,
    video_path: Path,
    events: tuple[VideoKeyEvent, ...],
    team_order: tuple[str, str, str],
    icon_mappings: dict[str, dict[str, str]],
    *,
    cycle_start_ms: int = 0,
) -> Path:
    current_slot = 0
    steps = []
    for index, event in enumerate(events, 1):
        if event.action.startswith("slot"):
            current_slot = int(event.action[-1]) - 1
        mapping = icon_mappings.get(event.action, {})
        steps.append({
            "id": f"video-{index:04d}",
            "time_ms": event.start_ms,
            "duration_ms": event.duration_ms,
            "character": team_order[current_slot],
            "action": event.action,
            "display_text": mapping.get("token", event.action),
            "confidence": event.confidence,
        })
    split = max(0, int(cycle_start_ms))
    startup = [step for step in steps if not split or step["time_ms"] < split]
    cycle = [dict(step, time_ms=step["time_ms"] - split) for step in steps if split and step["time_ms"] >= split]
    data = {
        "version": 1,
        "kind": "video-key-recognition-candidate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_video": str(video_path),
        "characters": list(team_order),
        "startup": {"steps": startup},
        "cycle": {"start_ms": split, "steps": cycle},
        "review_required": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
