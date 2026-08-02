# 第三方声明与致谢

## OK-WW / ok-wuthering-waves

- 上游项目：<https://cnb.cool/ok-oldking/ok-wuthering-waves>
- 本项目分析时对应的上游提交：`ab38a5eeed9466f7da238261c0a3cb3e8e42e62b`
- 上游图像标注数据声明的许可：GNU General Public License Version 3
- 许可证副本：[`third_party/GPL-3.0.txt`](third_party/GPL-3.0.txt)

本项目感谢 OK-WW 项目及其贡献者提供的开源实现和图像标注数据。

本仓库中的五张角色 HUD 头像和十二张状态识图模板，是从用户本机安装的 OK-WW `assets/coco_annotations.json` 标注数据中裁切、缩放得到的。具体文件与分类映射见：

- [`src/wuwa_assistant/assets/portraits/README.md`](src/wuwa_assistant/assets/portraits/README.md)
- [`src/wuwa_assistant/assets/state_templates/README.md`](src/wuwa_assistant/assets/state_templates/README.md)

连招提示中的部分操作建议参考了 OK-WW 角色控制代码对资源状态、动作优先级和切人条件的处理。具体分析文件见 [`docs/OKWW_OPERATION_RULES.md`](docs/OKWW_OPERATION_RULES.md)。本项目没有复制或启用 OK-WW 的输入发送流程。

## 教学视频

当前内置连招依据下列公开视频人工整理：

- [卡夏千 30s 标准双下落进阶轴](https://www.bilibili.com/video/BV1i8QpBQEQ4/)
- [秧千穗双羽轴教学](https://www.bilibili.com/video/BV1YYGA6hExX/)

视频版权归原作者及相应权利人所有。本项目仅保存整理后的按键步骤和来源链接，不重新分发视频内容。

## WW Combo Trainer / wwcombo

- 上游项目：<https://github.com/NovaWallace/wwcombo>
- 上游作者：NovaWallace
- 上游许可证：MIT License
- 许可证副本：[`third_party/WWCOMBO-MIT.txt`](third_party/WWCOMBO-MIT.txt)

本项目悬浮连段使用的通用动作与键鼠图标取自 wwcombo 的 `public/combo-assets/button-icons`。角色头像压在分段胶囊上的轴地图结构、同角色动作合并上限、结构化动作映射和视频按键区域识别思路亦参考其公开实现，并针对本项目的 Python/Tkinter 架构重新实现。

本项目未导入 wwcombo 的 Live2D、主题角色图、角色底图或其他游戏美术素材。

## 非官方声明

《鸣潮》、游戏角色、图标及相关素材的权利归其各自权利人所有。本项目与库洛游戏、OK-WW 或教学视频作者不存在隶属、赞助或官方合作关系。

## 项目发布声明

本项目仍处于测试阶段，仅供学习与非商业交流。仓库与项目直接提供的 EXE 不收取任何费用，禁止第三方将本项目打包售卖、用作收费服务或冒充官方付费版本。

上述项目声明不改变 OK-WW 衍生资源及其他第三方内容原有的许可证；第三方内容继续以其各自许可证和权利声明为准。
