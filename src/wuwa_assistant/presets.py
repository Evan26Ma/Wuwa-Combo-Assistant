from __future__ import annotations

from dataclasses import replace
from itertools import count

from .advice import operation_advice
from .models import ComboPreset, Cue


ACTION_LABELS = {
    "basic": "A",
    "heavy": "Z",
    "jump": "跳跃",
    "dodge": "闪避",
    "skill": "E",
    "echo": "Q",
    "liberation": "R",
    "utility": "F",
    "forward": "W",
    "slot1": "切1号位",
    "slot2": "切2号位",
    "slot3": "切3号位",
}

DEFAULT_WINDOWS = {
    "slot1": (0, 80, 850), "slot2": (0, 80, 850), "slot3": (0, 80, 850),
    "basic": (110, 280, 850), "heavy": (180, 480, 1150),
    "jump": (100, 260, 800), "dodge": (80, 220, 650),
    "skill": (120, 340, 1000), "echo": (120, 340, 1100),
    "liberation": (160, 420, 1300), "utility": (100, 260, 850),
    "forward": (80, 220, 650),
}

DEFAULT_CONDITIONS = {
    "basic": "等上一动作命中或后摇可取消时按普攻",
    "heavy": "等角色动作稳定后长按普攻，出现重击动作再松开",
    "jump": "等上一动作可取消时跳跃",
    "dodge": "在动作生效后立刻闪避取消后摇",
    "skill": "等上一击命中或技能图标可用时按 E",
    "echo": "等前一动作生效、声骸可用时按 Q",
    "liberation": "等共鸣解放可用且前一动作生效时按 R",
    "utility": "按视频轴衔接辅助键 F",
    "forward": "轻点前进键一步，不要持续移动",
    "slot1": "前一段确认生效后切到 1 号位",
    "slot2": "前一段确认生效后切到 2 号位",
    "slot3": "前一段确认生效后切到 3 号位",
}


class PresetBuilder:
    def __init__(self, prefix: str, source_at: str = "视频流程") -> None:
        self.prefix = prefix
        self.source_at = source_at
        self._ids = count(1)
        self.cues: list[Cue] = []

    def add(
        self,
        character: str,
        segment: str,
        actions: list[str],
        *,
        overrides: dict[int, dict] | None = None,
        anchor_first: bool = True,
    ) -> None:
        overrides = overrides or {}
        for idx, action in enumerate(actions):
            earliest, recommended, latest = DEFAULT_WINDOWS[action]
            data = {
                "condition": DEFAULT_CONDITIONS[action],
                "earliest_ms": earliest,
                "recommended_ms": recommended,
                "latest_ms": latest,
                "source_at": self.source_at,
                "timing_quality": "参考",
                "anchor": bool(anchor_first and idx == 0 and action.startswith("slot")),
                "hold_ms": 420 if action == "heavy" else 0,
                "vision_signal": f"character:{character}" if action.startswith("slot") else "",
                "advice": operation_advice(character, action),
            }
            data.update(overrides.get(idx, {}))
            self.cues.append(Cue(
                id=f"{self.prefix}-{next(self._ids):03d}",
                character=character,
                segment=segment,
                action=action,
                display_key=ACTION_LABELS[action],
                **data,
            ))


def _card_startup() -> ComboPreset:
    b = PresetBuilder("kxq-s", "简介文字轴 / 01:42–04:59")
    b.add("千咲", "千咲 EA", ["slot1", "skill", "basic"])
    b.add("夏空", "夏空 EQR", ["slot2", "skill", "echo", "liberation"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "卡提希娅 E", ["slot3", "skill"])
    b.add("夏空", "双跳闪重击", ["slot2", "jump", "basic", "basic", "basic", "jump", "basic", "basic", "basic", "jump", "dodge", "heavy"], overrides={11: {"condition": "第三次跳跃后立刻闪避，闪避位移结束瞬间长按普攻", "anchor": True}})
    b.add("千咲", "延奏切千咲 QRE", ["slot1", "echo", "liberation", "skill"], overrides={0: {"condition": "夏空延奏生效、千咲变奏入场时切换", "anchor": True}})
    b.add("卡提希娅", "卡提 AA", ["slot3", "basic", "basic"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "卡提 A", ["slot3", "basic"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "延奏切卡 跳AREE", ["slot3", "jump", "basic", "liberation", "skill", "skill"], overrides={0: {"condition": "千咲延奏图标出现时切卡提希娅", "anchor": True}})
    b.add("夏空", "夏空 AE", ["slot2", "basic", "skill"])
    b.add("千咲", "千咲 EA", ["slot1", "skill", "basic"])
    b.add("卡提希娅", "卡提 A", ["slot3", "basic"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "卡提 ARAA", ["slot3", "basic", "liberation", "basic", "basic"], overrides={2: {"anchor": True}})
    b.add("夏空", "夏空 R", ["slot2", "liberation"], overrides={1: {"anchor": True}})
    b.add("卡提希娅", "卡提 AEZA-R A-R", ["slot3", "basic", "skill", "heavy", "basic", "liberation", "basic", "liberation"], overrides={3: {"condition": "E 动画可取消、角色开始下落时长按普攻；落地伤害出现后接 A", "anchor": True}, 5: {"anchor": True}})
    b.add("夏空", "延奏切夏空", ["slot2"], overrides={0: {"condition": "卡提终结动作与延奏确认后切夏空", "anchor": True}})
    return ComboPreset("kaxiaqian-startup", "卡夏千 · 启动轴", ("千咲", "夏空", "卡提希娅"), "启动", 30000,
        "https://www.bilibili.com/video/BV1i8QpBQEQ4/",
        "千ea-夏eqr-千a-卡e-夏跳aaa跳aaa跳闪z-延千qre-卡aa-千a-卡a-千a-延卡跳aree-夏ae-千ea-卡a-千a-卡araa-夏r-卡aeza-Ra-R-延夏", tuple(b.cues),
        next_preset_id="kaxiaqian-cycle")


def _card_cycle() -> ComboPreset:
    b = PresetBuilder("kxq-c", "简介循环轴 / 04:59–06:08")
    b.add("夏空", "夏空 AAEZ", ["slot2", "basic", "basic", "skill", "heavy"], overrides={4: {"condition": "E 生效、人物落下的一瞬间长按普攻", "anchor": True}})
    b.add("千咲", "延奏切千咲 QRE", ["slot1", "echo", "liberation", "skill"], overrides={0: {"condition": "夏空延奏出现时切千咲", "anchor": True}})
    b.add("卡提希娅", "卡提 AA", ["slot3", "basic", "basic"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "卡提 AE", ["slot3", "basic", "skill"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "延奏切卡 跳AREE", ["slot3", "jump", "basic", "liberation", "skill", "skill"], overrides={0: {"anchor": True}})
    b.add("夏空", "夏空 AE", ["slot2", "basic", "skill"])
    b.add("千咲", "千咲 EA", ["slot1", "skill", "basic"])
    b.add("卡提希娅", "卡提 AA", ["slot3", "basic", "basic"])
    b.add("千咲", "千咲 A", ["slot1", "basic"])
    b.add("卡提希娅", "卡提 ARAA", ["slot3", "basic", "liberation", "basic", "basic"], overrides={2: {"anchor": True}})
    b.add("夏空", "夏空 R", ["slot2", "liberation"], overrides={1: {"anchor": True}})
    b.add("卡提希娅", "卡提 AEZA-R A-R", ["slot3", "basic", "skill", "heavy", "basic", "liberation", "basic", "liberation"], overrides={3: {"condition": "E 动画可取消、人物下落瞬间长按普攻", "anchor": True}, 5: {"anchor": True}})
    b.add("夏空", "延奏切夏空", ["slot2"], overrides={0: {"anchor": True}})
    return ComboPreset("kaxiaqian-cycle", "卡夏千 · 循环轴", ("千咲", "夏空", "卡提希娅"), "循环", 30000,
        "https://www.bilibili.com/video/BV1i8QpBQEQ4/",
        "夏aaez-延千qre-卡aa-千a-卡aE-千a-延卡跳aree-夏ae-千ea-卡aa-千a-卡araa-夏r-卡aeza-Ra-R-延夏", tuple(b.cues), loops=True)


def _feather_startup() -> ComboPreset:
    b = PresetBuilder("yqs-s", "流程图 01:00 / 手法教学")
    b.add("秧秧", "秧秧 E", ["slot1", "skill"])
    b.add("千咲", "千咲 A234E 下落A", ["slot2", "basic", "basic", "basic", "skill", "basic"], overrides={5: {"condition": "E 将角色带起后，接近落地/下落攻击判定出现的一瞬间按普攻", "anchor": True, "earliest_ms": 260, "recommended_ms": 520, "latest_ms": 1050}})
    b.add("穗穗", "穗穗 AEA3", ["slot3", "basic", "skill", "basic"], overrides={0: {"anchor": True}})
    b.add("千咲", "千咲 A123", ["slot2", "basic", "basic", "basic"])
    b.add("穗穗", "穗穗 A4", ["slot3", "basic"])
    b.add("秧秧", "秧秧 AE", ["slot1", "basic", "skill"])
    b.add("千咲", "千咲 A4QR", ["slot2", "basic", "echo", "liberation"], overrides={3: {"condition": "轻云千变奏后：Q 后立刻闪接 R；若未配置独立闪避提示，以游戏动作判断", "anchor": True}})
    b.add("穗穗", "变奏 QRE", ["slot3", "echo", "liberation", "skill"], overrides={0: {"condition": "穗穗变奏入场确认后开始 QRE", "anchor": True}})
    b.add("秧秧", "秧秧 A123", ["slot1", "basic", "basic", "basic"])
    b.add("穗穗", "穗穗 Z", ["slot3", "heavy"], overrides={1: {"condition": "切到穗穗、变奏动作稳定后长按普攻打重击", "anchor": True}})
    b.add("秧秧", "秧秧 A12Q", ["slot1", "basic", "basic", "echo"])
    b.add("穗穗", "穗穗 A", ["slot3", "basic"])
    b.add("秧秧", "变奏 EZREFW-EZ", ["slot1", "skill", "heavy", "liberation", "skill", "utility", "forward", "skill", "heavy"], overrides={0: {"anchor": True}, 6: {"condition": "按视频提示只向前走一步，角色位置修正后立即松开 W"}, 8: {"condition": "最后 E 生效、角色开始下落时长按普攻", "anchor": True}})
    return ComboPreset("yangqiansui-startup", "秧千穗 · 启动轴", ("秧秧", "千咲", "穗穗"), "启动", 28000,
        "https://www.bilibili.com/video/BV1YYGA6hExX/",
        "秧E-千a234E下落a-穗aEa3-千a123-穗a4-秧aE-千a4QR-变穗QRE-秧a123-穗Z-秧a12Q-穗a-变秧EZREFW(前走一步)EZ", tuple(b.cues),
        next_preset_id="yangqiansui-cycle")


def _feather_cycle() -> ComboPreset:
    b = PresetBuilder("yqs-c", "流程图 01:00 / 循环轴")
    b.add("千咲", "变奏下落 A", ["slot2", "basic"], overrides={0: {"condition": "千咲变奏入场后等待下落，在接近落地的一瞬间按普攻", "anchor": True}, 1: {"condition": "变奏下落接近地面时按普攻，确认下落伤害"}})
    b.add("穗穗", "穗穗 AEA3", ["slot3", "basic", "skill", "basic"], overrides={0: {"anchor": True}})
    b.add("千咲", "千咲 A123", ["slot2", "basic", "basic", "basic"])
    b.add("穗穗", "穗穗 A4", ["slot3", "basic"])
    b.add("秧秧", "秧秧 AE", ["slot1", "basic", "skill"])
    b.add("千咲", "千咲 A4(E)QR", ["slot2", "basic", "skill", "echo", "liberation"], overrides={2: {"condition": "E 为奇幻多打时的可选补键；没有触发时可通过锚点继续"}, 4: {"condition": "轻云千变奏后 Q 闪接 R", "anchor": True}})
    b.add("穗穗", "变奏 QRE", ["slot3", "echo", "liberation", "skill"], overrides={0: {"anchor": True}})
    b.add("秧秧", "秧秧 A123", ["slot1", "basic", "basic", "basic"])
    b.add("穗穗", "穗穗 Z", ["slot3", "heavy"], overrides={1: {"anchor": True}})
    b.add("秧秧", "秧秧 A12Q", ["slot1", "basic", "basic", "echo"])
    b.add("穗穗", "穗穗 A", ["slot3", "basic"])
    b.add("秧秧", "变奏 EZREFW-EZ", ["slot1", "skill", "heavy", "liberation", "skill", "utility", "forward", "skill", "heavy"], overrides={0: {"anchor": True}, 6: {"condition": "只向前走一步后松开 W"}, 8: {"condition": "E 生效、角色下落瞬间长按普攻", "anchor": True}})
    return ComboPreset("yangqiansui-cycle", "秧千穗 · 循环轴", ("秧秧", "千咲", "穗穗"), "循环", 25300,
        "https://www.bilibili.com/video/BV1YYGA6hExX/",
        "变千下落a-穗aEa3-千a123-穗a4-秧aE-千a4(E)QR-变穗QRE-秧a123-穗Z-秧a12Q-穗a-变秧EZREFW(前走一步)EZ", tuple(b.cues), loops=True)


def load_builtin_presets() -> tuple[ComboPreset, ...]:
    return (_card_startup(), _card_cycle(), _feather_startup(), _feather_cycle())


def clone_with_timing(preset: ComboPreset, timings: dict[str, dict]) -> ComboPreset:
    cues = []
    for cue in preset.cues:
        values = timings.get(cue.id, {})
        allowed = {k: v for k, v in values.items() if k in {"earliest_ms", "recommended_ms", "latest_ms", "condition"}}
        cues.append(replace(cue, **allowed))
    return replace(preset, cues=tuple(cues))
