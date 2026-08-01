from __future__ import annotations


OKWW_OPERATION_ADVICE: dict[str, dict[str, str]] = {
    "卡提希娅": {
        "slot": "变奏入场可先补一轮普攻；若仍是小卡提形态，先确认落地再进入后续。",
        "basic": "小卡提普攻用于补第二把剑；变奏入场的连续普攻也能稳定资源循环。",
        "heavy": "重击用于补第一把剑：先落地，再按住普攻直到重击动作和剑标记确认。",
        "skill": "E 用于补第三把剑；三剑齐全后再进入变身或终结段更稳定。",
        "liberation": "小卡提的 R 用于变身；大形态终结 R 可用时，R 后继续接 E。",
        "echo": "空中攻击段可以在跳起后穿插 Q，再接普攻完成空中动作。",
    },
    "夏空": {
        "slot": "卡提队中小卡提仍在场时采用快切；变奏入场则先用普攻建立资源。",
        "basic": "变奏入场先连续普攻建立协奏；非快切状态可用跳 A 补资源。",
        "jump": "资源未满时用跳 A 补充；空中段结束后确认落地再接地面动作。",
        "heavy": "三格或满特殊能量再打重击；人在地面时先起跳，再长按普攻。",
        "skill": "E 成功后无需额外补跳 A，可直接为重击或解放衔接做准备。",
        "liberation": "E 或重击刚生效时先等动作稳定再 R；卡提队增益期间不要过早切走。",
        "echo": "Q 可用时优先前置；若没有前置，可在主要技能段结束后补 Q。",
    },
    "千咲": {
        "slot": "变奏入场会建立支援增益；可优先 Q 后快切，本视频段要求 QRE 时按轴走完。",
        "echo": "支援态优先前置 Q；变奏已触发时，Q 生效后即可准备后续 R/E 或切人。",
        "liberation": "R 会记录并刷新支援增益；成功释放后不要无意义久留。",
        "skill": "R 不可用时用 E 补支援；若还在空中且 E/R 都不可用，先落地。",
        "heavy": "满特殊能量时先落地，长按 E 消耗资源后再衔接重击。",
    },
    "穗穗": {
        "slot": "Forte3 轮转完成后切出会进入锁定期；下一次变奏成熟再回场更稳。",
        "basic": "持续普攻积累 Forte3；E 亮时可穿插 E，随后继续普攻。",
        "skill": "普攻过程中 E 亮就穿插，目标是继续积累 Forte3 与协奏能量。",
        "liberation": "确认 Forte3 可用后再 R；R 后继续 A/E，协奏满了再切人。",
        "heavy": "这一下 Z 来自视频轴；OK-WW 的 Forte3 轮转不以重击为核心，按当前轴执行即可。",
        "echo": "Q 属于视频变奏段的前置动作，确认入场稳定后再接 R/E。",
    },
    "秧秧": {
        "slot": "变奏入场是较长站场段，准备持续按住普攻并在过程中穿插技能。",
        "basic": "OK-WW 会在整段持续按住普攻，让普通攻击和重击自然衔接。",
        "heavy": "Z 表示持续长按普攻形成的重击；技能释放后继续保持长按逻辑。",
        "skill": "长按过程中 E 亮稳定后再触发；若 R 同时可用，优先 R。",
        "liberation": "长按过程中 R 优先于 E；R 成功后继续保持攻击并完成剩余技能段。",
    },
}


def operation_advice(character: str, action: str) -> str:
    role_rules = OKWW_OPERATION_ADVICE.get(character, {})
    if action.startswith("slot"):
        return role_rules.get("slot", "")
    return role_rules.get(action, "")
