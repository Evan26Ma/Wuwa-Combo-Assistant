from wuwa_assistant.engine import ComboEngine
from wuwa_assistant.models import ComboPreset, Cue, InputEvent


def cue(index: int, action: str, *, anchor: bool = False, character: str = "甲") -> Cue:
    return Cue(
        id=f"c{index}", character=character, segment=f"段{index}", action=action,
        display_key=action, condition="test", earliest_ms=100,
        recommended_ms=200, latest_ms=500, anchor=anchor,
        hold_ms=350 if action == "heavy" else 0,
    )


def preset(*cues: Cue) -> ComboPreset:
    return ComboPreset("test", "测试轴", ("甲", "乙", "丙"), "启动", 1000, "", "", cues)


def test_correct_input_advances_without_timing_judgement():
    engine = ComboEngine((preset(cue(1, "skill"), cue(2, "basic")),))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("skill", 10.05))
    assert engine.index == 1
    assert engine.message == "已识别 skill"


def test_wrong_input_keeps_current_step():
    engine = ComboEngine((preset(cue(1, "skill"), cue(2, "basic")),))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("echo", 10.2))
    assert engine.index == 0
    assert engine.confidence < 0.5


def test_short_hold_does_not_advance_heavy():
    engine = ComboEngine((preset(cue(1, "heavy")),))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("heavy", 10.5, held_ms=200))
    assert engine.index == 0
    assert "长按不足" in engine.message


def test_unique_anchor_resyncs_conservatively():
    combo = preset(
        cue(1, "basic"), cue(2, "skill"), cue(3, "echo"),
        cue(4, "slot2", anchor=True, character="乙"), cue(5, "liberation"),
    )
    engine = ComboEngine((combo,))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("slot2", 10.4))
    assert engine.index == 4
    assert "已恢复" in engine.message


def test_ambiguous_anchor_does_not_jump():
    combo = preset(
        cue(1, "basic"),
        cue(2, "slot2", anchor=True, character="乙"),
        cue(3, "basic"),
        cue(4, "slot2", anchor=True, character="乙"),
    )
    engine = ComboEngine((combo,))
    engine.process(InputEvent("slot2", engine.cue_started_at + 0.3))
    assert engine.index == 0


def test_visual_character_observation_strengthens_anchor_match():
    combo = preset(cue(1, "basic", character="甲"), cue(2, "skill", anchor=True, character="乙"))
    engine = ComboEngine((combo,))
    engine.observe_character("乙")
    engine.process(InputEvent("skill", engine.cue_started_at + 0.2))
    assert engine.index == 2
    assert "已恢复" in engine.message


def test_startup_automatically_enters_and_repeats_cycle():
    startup = ComboPreset(
        "team-startup", "队伍 · 启动轴", ("甲", "乙", "丙"), "启动", 1000,
        "", "", (cue(1, "skill"),), next_preset_id="team-cycle",
    )
    cycle = ComboPreset(
        "team-cycle", "队伍 · 循环轴", ("甲", "乙", "丙"), "循环", 1000,
        "", "", (cue(2, "basic"),), loops=True,
    )
    engine = ComboEngine((startup, cycle))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("skill", 10.2))
    assert engine.preset.id == "team-cycle"
    assert engine.index == 0
    assert engine.cycle_count == 1
    assert "自动进入循环" in engine.message

    engine.process(InputEvent("basic", 10.5))
    assert engine.preset.id == "team-cycle"
    assert engine.index == 0
    assert engine.cycle_count == 2


def test_reset_from_cycle_returns_to_startup():
    startup = ComboPreset(
        "team-startup", "队伍 · 启动轴", ("甲", "乙", "丙"), "启动", 1000,
        "", "", (cue(1, "skill"),), next_preset_id="team-cycle",
    )
    cycle = ComboPreset(
        "team-cycle", "队伍 · 循环轴", ("甲", "乙", "丙"), "循环", 1000,
        "", "", (cue(2, "basic"),), loops=True,
    )
    engine = ComboEngine((startup, cycle))
    engine.cue_started_at = 10.0
    engine.process(InputEvent("skill", 10.2))
    engine.reset()
    assert engine.preset.id == "team-startup"
    assert engine.cycle_count == 0
