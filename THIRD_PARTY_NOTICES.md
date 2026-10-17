# 用到了哪些公开资料

业务规则和界面是在项目里重新整理的。下面列出参考过的公开资料，以及需要保留的第三方许可。

- `reference/EquipmentEventTypeCode.java`、`reference/ShipmentEventTypeCode.java` 和 DCSA 合成事件来自 [DCSA Track & Trace 项目](https://github.com/dcsaorg/DCSA-TNT/tree/af619ff6abefe1bf6d668cf88477c1c2ee20cd08)，按其 Apache-2.0 条款使用。许可证副本在 `reference/LICENSE-DCSA.txt`。原样材料、整理后的映射、本项目自己的业务规则分别记录在 `reference/sources.json`。
- 少量地点结构参考 UNECE UN/LOCODE 2025-1 发布资料；仓库没有收录完整地点数据库。出处和版本见 `reference/sources.json`。
- 讨论到港期限时，参考了公开的 Maersk 条款与历史资料链接。它们不能替代当前合同或实时费用，也不是业务建议；仓库没有收录 PDF 正文。
- 前端依赖 React、Vite、Lucide 等及 Python 包按各自许可证分发；版本固定在 `frontend/pnpm-lock.yaml` 和 `requirements.txt`。
- 调整界面层级和信息密度时，参考了 [Taste](https://github.com/Leonxlnx/taste-skill) 和 [Impeccable](https://github.com/pbakaus/impeccable) 的公开设计方法。仓库没有收录这两个 skill 包，也没有做它们的完整检查。
- Windows 演示程序使用 [PyInstaller 6.22.3](https://pyinstaller.org/en/v6.22.3/license.html) 打包。其 bootloader 采用 GPL-2.0-or-later 并附带打包分发例外；打包进去的 Python 依赖继续受各自许可证约束。

本仓库根目录 `LICENSE` 只说明本项目原创部分的授权状态，不更改以上第三方权利。
