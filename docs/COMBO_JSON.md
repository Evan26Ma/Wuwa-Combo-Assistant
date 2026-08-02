# 连招 JSON 结构

内置连招保存在 `src/wuwa_assistant/assets/combos/builtin.json`。界面文字、物理按键和图标不写死在连招步骤中，而由 `assets/action_icons/icon_mappings.json` 独立映射。

## 顶层结构

```json
{
  "version": 1,
  "combos": [
    {
      "id": "combo-id",
      "name": "队伍显示名",
      "source_url": "教学来源",
      "characters": ["角色一", "角色二", "角色三"],
      "startup": { "id": "startup", "name": "启动轴", "steps": [] },
      "cycle": { "id": "cycle", "name": "循环轴", "steps": [] }
    }
  ]
}
```

程序始终先执行一次 `startup`，完成后自动进入 `cycle` 并循环。角色顺序可以在界面拖动调整；步骤中的 `character` 是目标角色名，运行时才换算成当前的 `1 / 2 / 3` 槽位键。

## 步骤字段

| 字段 | 用途 |
|---|---|
| `id` | 连招内稳定且唯一的步骤标识 |
| `character` | 执行动作的目标角色 |
| `segment` | 所属连招小段 |
| `action` | 语义动作，如 `basic`、`heavy`、`skill`、`slot2` |
| `display_text` | 教学轴中的显示文字 |
| `condition` | 操作提示，不作为阻止推进的硬条件 |
| `hold_ms` / `hold_tolerance_ms` | 长按要求与容差 |
| `source_time` | 教学视频参考时间点 |
| `anchor` | 是否可作为保守重同步锚点 |
| `vision` | 可选画面确认信号 |
| `advice` | 从教学与 OK-WW 控制逻辑整理的建议 |

时间字段保留用于数据整理和来源核对；当前版本不根据它宣称判断最佳按下时机。

## 动作与显示映射

`icon_mappings.json` 将语义动作映射为显示记号和图标。例如：

```json
{
  "basic": { "token": "a", "icon": "mouse-left.png" },
  "heavy": { "token": "z", "icon": "mouse-left-hold.png" },
  "skill": { "token": "e", "icon": "skill.png" },
  "slot1": { "token": "i", "icon": "i.png" }
}
```

因此可以只更换图标或记号，而不修改连招轴。

## 视频识别候选文件

“视频识别”页输出 `*.candidate.json`，其中步骤额外带有 `time_ms`、`duration_ms` 和 `confidence`。候选文件固定包含 `review_required: true`，需要人工核对角色、切轴位置和漏检/误检后，才能整理进 `builtin.json`。
