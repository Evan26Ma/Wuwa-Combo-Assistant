# 项目接入规范

## 关键文件

- `src/wuwa_assistant/models.py`：`Cue` 与 `ComboPreset`。
- `src/wuwa_assistant/presets.py`：内置启动轴与循环轴。
- `src/wuwa_assistant/advice.py`：OK-WW 操作建议。
- `src/wuwa_assistant/vision.py`：识图信号和内置模板。
- `tests/test_presets.py`、`tests/test_vision.py`：数据与识图验证。
- `build.ps1`：测试并打包单文件 EXE。

## 动作与显示

| action | 显示 | 含义 |
|---|---|---|
| `basic` | A | 左键普攻 |
| `heavy` | Z | 长按左键重击 |
| `jump` | 跳跃 | 跳跃 |
| `dodge` | 闪避 | 闪避/取消 |
| `skill` | E | 共鸣技能 |
| `echo` | Q | 声骸技能 |
| `liberation` | R | 共鸣解放 |
| `utility` | F | 辅助/交互键 |
| `forward` | W | 短按前进 |
| `slot1/2/3` | 切1/2/3号位 | 切人 |

## 可用识图信号

- `character:卡提希娅`、`character:夏空`、`character:千咲`、`character:秧秧`、`character:穗穗`
- `cartethyia:small`
- `cartethyia:sword1`、`cartethyia:sword2`、`cartethyia:sword3`
- `cartethyia:mid_air`
- `cartethyia:lib_big`
- `suisui:forte3`

新角色没有稳定模板时只保留角色/输入锚点，不伪造 `vision_signal`。

## JSON 中间规格

```json
{
  "id": "team-id",
  "name": "队伍名",
  "team": ["1号位", "2号位", "3号位"],
  "source_url": "https://...",
  "startup": {"raw_axis": "...", "cues": []},
  "cycle": {"raw_axis": "...", "cues": []}
}
```

每个 cue 至少包含 `character`、`segment`、`action`、`condition`；可选 `anchor`、`vision_signal`、`source_at`、`advice`。

## 验证命令

```powershell
python -m pytest -q
.\build.ps1
```
