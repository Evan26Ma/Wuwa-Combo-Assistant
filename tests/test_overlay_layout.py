import pytest

from wuwa_assistant.overlay_layout import plan_overlay_layout


@pytest.mark.parametrize("mode", ["horizontal", "vertical", "waterfall"])
@pytest.mark.parametrize("screen", [(1366, 768), (1920, 1080), (2560, 1440)])
def test_overlay_modes_place_every_combo_block(mode, screen):
    screen_width, screen_height = screen
    plan = plan_overlay_layout(120, mode, screen_width, screen_height, move_bar_height=30)
    assert len(plan.blocks) == 120
    assert [block.index for block in plan.blocks] == list(range(120))
    assert plan.width <= screen_width - 48
    assert plan.height <= screen_height - 72
    assert all(
        block.x >= 0 and block.y >= 30
        and block.x + block.width <= plan.width
        and block.y + block.height <= plan.height
        for block in plan.blocks
    )


def test_horizontal_layout_wraps_instead_of_truncating():
    plan = plan_overlay_layout(68, "horizontal", 1366, 768)
    assert len({block.y for block in plan.blocks}) > 1
    assert len(plan.blocks) == 68
