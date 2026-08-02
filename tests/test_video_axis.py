import json

import numpy as np

from wuwa_assistant.video_axis import (
    FrameSample,
    VideoKeyEvent,
    export_candidate_timeline,
    is_recognition_cyan,
    recognition_runs,
)


def sample(active: bool) -> FrameSample:
    return FrameSample(active, active, .9 if active else 0.0)


def test_cyan_classifier_accepts_overlay_blue_and_rejects_neutral():
    pixels = np.array([[[36, 188, 224], [210, 210, 210], [180, 64, 48]]], dtype=np.uint8)
    assert is_recognition_cyan(pixels).tolist() == [[True, False, False]]


def test_recognition_rejects_noise_and_preserves_basic_tap_gaps():
    assert recognition_runs([sample(False), sample(True), sample(False)], 30, merge_repeated_hold=False, preserve_tap_gaps=False) == []
    runs = recognition_runs(
        [sample(True), sample(True), sample(False), sample(True), sample(True)],
        30, merge_repeated_hold=False, preserve_tap_gaps=True,
    )
    assert len(runs) == 2


def test_candidate_timeline_splits_startup_cycle_and_tracks_target_character(tmp_path):
    events = (
        VideoKeyEvent("switch-2", "slot2", 100, 80, .9),
        VideoKeyEvent("skill", "skill", 300, 80, .8),
        VideoKeyEvent("switch-3", "slot3", 1000, 80, .9),
        VideoKeyEvent("basic", "basic", 1200, 80, .85),
    )
    path = export_candidate_timeline(
        tmp_path / "candidate.json", tmp_path / "video.mp4", events,
        ("甲", "乙", "丙"),
        {"slot2": {"token": "ii"}, "slot3": {"token": "iii"}, "skill": {"token": "e"}, "basic": {"token": "a"}},
        cycle_start_ms=1000,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [step["character"] for step in data["startup"]["steps"]] == ["乙", "乙"]
    assert data["cycle"]["steps"][0]["character"] == "丙"
    assert data["cycle"]["steps"][1]["display_text"] == "a"
    assert data["review_required"] is True
