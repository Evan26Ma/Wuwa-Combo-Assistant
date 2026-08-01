---
name: wuwa-teaching-link-to-combo
description: Analyze Wuthering Waves/鸣潮 teaching video links and implement complete read-only combo coaching presets. Use when a user supplies a Bilibili or other tutorial link and asks to extract key sequences, startup and loop rotations, character/slot mapping, action conditions, OK-WW-derived advice, visual recognition anchors, tests, or a rebuilt EXE for the 鸣潮连招辅助 project.
---

# 鸣潮教学链接转逐键轴

把教学链接转换为“只监听、不发送输入”的启动轴与循环轴，并完成代码、识图锚点、测试和打包。

## 工作流

1. 读取 [video-analysis.md](references/video-analysis.md)，用现有 Chrome/浏览器会话打开链接，收集标题、简介文字轴、字幕、章节和关键画面。优先作者文字轴，其次字幕解释，再次逐帧观察；不要猜测看不清的按键。
2. 读取 [project-integration.md](references/project-integration.md)，检查目标仓库当前模型、键位记号、预设和识图信号。默认项目为 `F:\鸣潮连招辅助`；路径不存在时再询问用户。
3. 明确队伍顺序与槽位，分别整理只执行一次的启动轴和自动重复的循环轴。若视频没有区分，标注证据并询问或保守地只创建一个非循环轴。
4. 将中间结果写成 JSON 规格并运行：

   `python scripts/validate_combo_spec.py <combo-spec.json>`

5. 使用 `apply_patch` 更新项目。保持 `A=左键普攻`、`Z=长按左键重击`；每个节点必须有角色、小段、动作、操作条件和来源。只给稳定 HUD 状态配置 `vision_signal`，识图不得阻止按键推进。
6. 对项目已有 OK-WW 角色，结合控制代码补资源与优先级建议；视频顺序始终优先于 OK-WW 通用轮转。发生冲突时明确写“按当前视频轴执行”。
7. 更新预设测试，至少验证：轴存在、启动接循环、按键原文保留、槽位正确、关键落地/长按/变奏条件、识图信号合法。运行全量测试、构建 EXE并做启动冒烟测试。
8. 汇报新增队伍、启动/循环步数、无法验证的节点、测试结果和 EXE 路径。只有用户已授权当前仓库推送时才提交并推送。

## 硬约束

- 只生成提示和监听逻辑；禁止加入输入模拟、连点、宏或自动施法。
- 不恢复时间窗、过早/偏晚判断，除非用户重新明确要求且提供可验证依据。
- 启动轴必须在循环轴之前，启动完成后才能自动进入循环。
- 普通错键不停止；锚点只能在角色、顺序、组合和合理上下文唯一时重同步。
- 不把字幕推测写成已验证事实。对模糊节点使用“参考/待核对”说明。
