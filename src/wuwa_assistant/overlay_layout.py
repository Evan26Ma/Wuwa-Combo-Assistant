from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class BlockPlacement:
    index: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class OverlayLayoutPlan:
    width: int
    height: int
    blocks: tuple[BlockPlacement, ...]


def plan_overlay_layout(
    count: int,
    mode: str,
    screen_width: int,
    screen_height: int,
    *,
    move_bar_height: int = 0,
) -> OverlayLayoutPlan:
    count = max(0, int(count))
    max_width = max(320, min(int(screen_width * 0.95), screen_width - 48))
    max_height = max(220, min(int(screen_height * 0.92), screen_height - 72))
    margin = 12
    # Keep every action readable at game-viewing distance. A 52 px card made
    # three-character names and switch targets collapse into visual noise.
    block_width = 72
    block_height = 70
    gap_x = 6
    gap_y = 6
    content_top = margin + max(0, move_bar_height)
    if count == 0:
        return OverlayLayoutPlan(280, content_top + block_height + margin, ())

    if mode == "vertical":
        rows = max(1, (max_height - content_top - margin + gap_y) // (block_height + gap_y))
        columns = ceil(count / rows)
        width = min(max_width, margin * 2 + columns * block_width + max(0, columns - 1) * gap_x)
        blocks = tuple(
            BlockPlacement(
                index,
                margin + (index // rows) * (block_width + gap_x),
                content_top + (index % rows) * (block_height + gap_y),
                block_width,
                block_height,
            )
            for index in range(count)
        )
        height = min(max_height, content_top + min(rows, count) * (block_height + gap_y) - gap_y + margin)
        return OverlayLayoutPlan(width, height, blocks)

    if mode == "waterfall":
        step_y = 50
        diagonal = 12
        rows = max(1, (max_height - content_top - block_height - margin) // step_y + 1)
        columns = ceil(count / rows)
        column_width = block_width + diagonal + 10
        width = min(max_width, margin * 2 + columns * column_width)
        blocks = tuple(
            BlockPlacement(
                index,
                margin + (index // rows) * column_width + (index % rows) % 2 * diagonal,
                content_top + (index % rows) * step_y,
                block_width,
                block_height,
            )
            for index in range(count)
        )
        height = min(max_height, content_top + min(rows, count) * step_y - step_y + block_height + margin)
        return OverlayLayoutPlan(width, height, blocks)

    columns = max(1, (max_width - margin * 2 + gap_x) // (block_width + gap_x))
    rows = ceil(count / columns)
    visible_columns = min(columns, count)
    width = margin * 2 + visible_columns * block_width + max(0, visible_columns - 1) * gap_x
    height = content_top + rows * block_height + max(0, rows - 1) * gap_y + margin
    return OverlayLayoutPlan(min(max_width, width), min(max_height, height), tuple(
        BlockPlacement(
            index,
            margin + (index % columns) * (block_width + gap_x),
            content_top + (index // columns) * (block_height + gap_y),
            block_width,
            block_height,
        )
        for index in range(count)
    ))
