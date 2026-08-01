# 内置 HUD 识图模板

本目录的 12 张小图从用户本机 OK-WW 的 `assets/coco_annotations.json` 标注裁切得到，包含 5 个队伍角色 HUD、卡提希娅三剑/形态/空中攻击/终结解放和穗穗 Forte3。

- 上游项目：<https://cnb.cool/ok-oldking/ok-wuthering-waves>
- 上游提交：`ab38a5eeed9466f7da238261c0a3cb3e8e42e62b`
- 图像数据许可：GNU GPL Version 3
- 许可证副本：[`../../../../third_party/GPL-3.0.txt`](../../../../third_party/GPL-3.0.txt)

识图采用固定 HUD 比例区域与连续两帧确认，只用于提示、角色判断和锚点加分；匹配失败不会阻止连招推进。
