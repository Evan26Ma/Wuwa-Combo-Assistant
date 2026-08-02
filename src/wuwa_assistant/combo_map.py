from __future__ import annotations

from dataclasses import dataclass

from .models import SequenceStep


@dataclass(frozen=True)
class ComboMapSegment:
    id: str
    character: str
    label: str
    phase: str
    steps: tuple[SequenceStep, ...]
    state: str
    chunk_index: int = 1
    chunk_total: int = 1


@dataclass(frozen=True)
class SegmentPlacement:
    segment_index: int
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ComboMapPlan:
    width: int
    height: int
    placements: tuple[SegmentPlacement, ...]
    hidden_before: int
    hidden_after: int


def build_combo_segments(
    steps: tuple[SequenceStep, ...],
    phase: str,
    *,
    max_actions: int = 6,
) -> tuple[ComboMapSegment, ...]:
    """Group one phase into portrait-led action capsules.

    Segment names define semantic runs; long runs are split at six actions to
    match the information density used by wwcombo's merged role capsules.
    """
    max_actions = max(1, int(max_actions))
    filtered = [step for step in steps if step.phase == phase]
    raw_runs: list[list[SequenceStep]] = []
    for step in filtered:
        key = (step.phase, step.cue.character, step.cue.segment)
        previous = raw_runs[-1] if raw_runs else []
        previous_key = (
            previous[-1].phase, previous[-1].cue.character, previous[-1].cue.segment
        ) if previous else None
        if previous and previous_key == key:
            previous.append(step)
        else:
            raw_runs.append([step])

    result: list[ComboMapSegment] = []
    for run in raw_runs:
        chunks = [run[index:index + max_actions] for index in range(0, len(run), max_actions)]
        for chunk_index, chunk in enumerate(chunks, 1):
            states = {step.state for step in chunk}
            state = (
                "error" if "error" in states else
                "current" if "current" in states else
                "completed" if states == {"completed"} else
                "upcoming"
            )
            cue = chunk[0].cue
            label = cue.segment
            if len(chunks) > 1:
                label = f"{label} · {chunk_index}/{len(chunks)}"
            result.append(ComboMapSegment(
                id=f"{cue.id}:chunk{chunk_index}",
                character=cue.character,
                label=label,
                phase=chunk[0].phase,
                steps=tuple(chunk),
                state=state,
                chunk_index=chunk_index,
                chunk_total=len(chunks),
            ))
    return tuple(result)


def segment_width(segment: ComboMapSegment) -> int:
    return max(210, min(390, 108 + len(segment.steps) * 43))


def current_segment_index(segments: tuple[ComboMapSegment, ...]) -> int:
    for index, segment in enumerate(segments):
        if segment.state in {"current", "error"}:
            return index
    if segments and all(segment.state == "completed" for segment in segments):
        return len(segments) - 1
    return 0


def _visible_indices(
    segments: tuple[ComboMapSegment, ...], current: int, budget: int, *, max_items: int
) -> list[int]:
    if not segments:
        return []
    gap = 14
    selected = [max(0, min(current, len(segments) - 1))]
    used = segment_width(segments[selected[0]])
    left = selected[0] - 1
    right = selected[0] + 1
    left_blocked = left < 0
    right_blocked = right >= len(segments)
    while len(selected) < max_items:
        added = False
        for side in ("left", "right"):
            if side == "left":
                if left_blocked:
                    continue
                candidate = left
            else:
                if right_blocked:
                    continue
                candidate = right
            if candidate < 0 or candidate >= len(segments):
                if side == "left":
                    left_blocked = True
                else:
                    right_blocked = True
                continue
            width = segment_width(segments[candidate])
            if used + gap + width <= budget:
                selected.append(candidate)
                used += gap + width
                added = True
                if side == "left":
                    left -= 1
                    left_blocked = left < 0
                else:
                    right += 1
                    right_blocked = right >= len(segments)
            else:
                if side == "left":
                    left_blocked = True
                else:
                    right_blocked = True
            if len(selected) >= max_items:
                break
        if not added:
            break
    return sorted(selected)


def plan_combo_map(
    segments: tuple[ComboMapSegment, ...],
    mode: str,
    screen_width: int,
    screen_height: int,
    *,
    move_bar_height: int = 0,
) -> ComboMapPlan:
    max_width = max(420, min(screen_width - 48, int(screen_width * 0.95)))
    max_height = max(260, min(screen_height - 72, int(screen_height * 0.86)))
    margin = 12
    gap = 14
    capsule_height = 98
    map_bar_height = 26
    top = margin + max(0, move_bar_height) + map_bar_height
    current = current_segment_index(segments)

    if mode == "vertical":
        per_item = capsule_height + 8
        max_items = max(1, min(3, (max_height - top - margin) // per_item))
        indices = _visible_indices(segments, current, 100_000, max_items=max_items)
        width = min(max_width, max((segment_width(segments[index]) for index in indices), default=360) + margin * 2)
        placements = tuple(
            SegmentPlacement(index, margin, top + order * per_item,
                             min(width - margin * 2, segment_width(segments[index])), capsule_height)
            for order, index in enumerate(indices)
        )
        height = min(max_height, top + len(indices) * per_item - 8 + margin)
    elif mode == "waterfall":
        indices = _visible_indices(segments, current, max_width - margin * 2 - 46, max_items=3)
        width = min(max_width, max((segment_width(segments[index]) for index in indices), default=360) + 70)
        step_y = 76
        placements = tuple(
            SegmentPlacement(index, margin + (order % 2) * 42, top + order * step_y,
                             min(width - margin * 2 - 42, segment_width(segments[index])), capsule_height)
            for order, index in enumerate(indices)
        )
        height = min(max_height, top + max(0, len(indices) - 1) * step_y + capsule_height + margin)
    else:
        indices = _visible_indices(segments, current, max_width - margin * 2, max_items=3)
        content_width = sum(segment_width(segments[index]) for index in indices) + gap * max(0, len(indices) - 1)
        width = min(max_width, content_width + margin * 2)
        placements_list: list[SegmentPlacement] = []
        x = margin
        for index in indices:
            item_width = min(segment_width(segments[index]), width - margin * 2)
            placements_list.append(SegmentPlacement(index, x, top, item_width, capsule_height))
            x += item_width + gap
        placements = tuple(placements_list)
        height = top + capsule_height + margin

    first = min((placement.segment_index for placement in placements), default=0)
    last = max((placement.segment_index for placement in placements), default=-1)
    return ComboMapPlan(
        width=width,
        height=height,
        placements=placements,
        hidden_before=max(0, first),
        hidden_after=max(0, len(segments) - last - 1),
    )
