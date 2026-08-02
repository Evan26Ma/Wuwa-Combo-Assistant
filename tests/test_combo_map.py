import pytest

from wuwa_assistant.combo_map import build_combo_segments, current_segment_index, plan_combo_map
from wuwa_assistant.models import Cue, SequenceStep


def step(index, character, segment, state="upcoming", phase="启动"):
    cue = Cue(
        id=f"cue-{index}", character=character, segment=segment, action="basic",
        display_key="A", condition="test", earliest_ms=0, recommended_ms=0, latest_ms=0,
    )
    return SequenceStep(cue, phase, index, state)


def test_map_groups_semantic_runs_and_splits_long_runs_at_six_actions():
    source = tuple(step(i, "甲", "长连段", "current" if i == 7 else "upcoming") for i in range(13))
    segments = build_combo_segments(source, "启动")
    assert [len(segment.steps) for segment in segments] == [6, 6, 1]
    assert segments[1].label.endswith("2/3")
    assert current_segment_index(segments) == 1


def test_map_keeps_character_changes_as_separate_portrait_nodes():
    source = (
        step(0, "甲", "技能", "completed"),
        step(1, "甲", "技能", "completed"),
        step(2, "乙", "技能", "current"),
    )
    segments = build_combo_segments(source, "启动")
    assert [segment.character for segment in segments] == ["甲", "乙"]
    assert [segment.state for segment in segments] == ["completed", "current"]


@pytest.mark.parametrize("mode", ["horizontal", "vertical", "waterfall"])
@pytest.mark.parametrize("screen", [(1366, 768), (1920, 1080), (2560, 1440)])
def test_map_viewport_contains_current_and_stays_on_screen(mode, screen):
    source = tuple(
        step(index, ("甲", "乙", "丙")[index % 3], f"段{index}", "current" if index == 9 else "upcoming")
        for index in range(20)
    )
    segments = build_combo_segments(source, "启动")
    plan = plan_combo_map(segments, mode, *screen, move_bar_height=30)
    indices = {placement.segment_index for placement in plan.placements}
    assert 9 in indices
    assert len(indices) <= 3
    assert plan.hidden_before + len(indices) + plan.hidden_after == len(segments)
    assert plan.width <= screen[0] - 48
    assert plan.height <= screen[1] - 72
    assert all(
        placement.x >= 0 and placement.y >= 30
        and placement.x + placement.width <= plan.width
        and placement.y + placement.height <= plan.height
        for placement in plan.placements
    )
