from wuwa_assistant.presets import load_builtin_presets


def test_all_four_presets_exist_and_have_cues():
    presets = load_builtin_presets()
    assert [preset.id for preset in presets] == [
        "kaxiaqian-startup",
        "kaxiaqian-cycle",
        "yangqiansui-startup",
        "yangqiansui-cycle",
    ]
    assert all(preset.cues for preset in presets)
    assert sum(len(preset.cues) for preset in presets) == 215


def test_startup_flows_into_repeating_cycle():
    presets = {preset.id: preset for preset in load_builtin_presets()}
    assert presets["kaxiaqian-startup"].next_preset_id == "kaxiaqian-cycle"
    assert presets["yangqiansui-startup"].next_preset_id == "yangqiansui-cycle"
    assert presets["kaxiaqian-cycle"].loops
    assert presets["yangqiansui-cycle"].loops


def test_timing_windows_are_ordered():
    for preset in load_builtin_presets():
        for cue in preset.cues:
            assert 0 <= cue.earliest_ms <= cue.recommended_ms <= cue.latest_ms
            assert cue.display_key
            assert cue.condition


def test_known_video_axes_and_targets_are_preserved():
    presets = {preset.id: preset for preset in load_builtin_presets()}
    assert "跳aaa跳aaa跳闪z" in presets["kaxiaqian-startup"].raw_axis
    assert "EZREFW" in presets["yangqiansui-cycle"].raw_axis
    assert presets["yangqiansui-startup"].target_total_ms == 28000
    assert presets["yangqiansui-cycle"].target_total_ms == 25300


def test_landing_and_q_dodge_r_cues_are_present():
    text = "\n".join(cue.condition for preset in load_builtin_presets() for cue in preset.cues)
    assert "下落" in text
    assert "落地" in text
    assert "Q 后立刻闪接 R" in text or "Q 闪接 R" in text


def test_attack_notation_uses_a_and_z():
    labels = {cue.action: cue.display_key for preset in load_builtin_presets() for cue in preset.cues}
    assert labels["basic"] == "A"
    assert labels["heavy"] == "Z"
