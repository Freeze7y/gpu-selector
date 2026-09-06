# GPU Selector 2.1.1

**正式版 · 2026-09-07 · Windows x64**

基于 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) 改编，作者 **Freeze7y**，按 **AGPL-3.0** 发布。

## 本次修改

- **备份清除支持多选**：使用 Ctrl / Shift 多选，或在列表内按 Ctrl+A 全选；确认数量与文件清单后逐项移到 Windows 回收站，并显示成功与失败结果。恢复备份仍需单选。
- **清除所选路径支持多选**：多条路径合并为一次修改预览，沿用自动备份、读回校验及失败恢复。只清除所选路径的图形设置记录，不删除应用文件。多选时禁用单应用偏好操作。
- 刷新保留仍存在的所选条目，清除后不自动选中其他条目。

2.1.0 用户可在“外观与说明 → 检查更新”安装本版，也可下载 **GPUSelector-v2.1.1-windows-x64.exe** 手动覆盖。设置、方案、备份和日志继续使用原数据目录。

## 发布范围

本次直接构建并发布，**未运行自动化测试、界面烟雾测试或实际清除测试**。仓库中的 255 项通过记录属于 2.1.0，不代表本次新增多选功能已通过测试。Windows 10 实机兼容性仍未验证。

便携 ZIP 附带说明与许可证；源码及 Qt / PySide 对应源码附件供开发者使用。在线更新说明见 [UPDATING.md](https://github.com/Freeze7y/gpu-selector/blob/v2.1.1/docs/UPDATING.md)。

## English

Stable release adding Ctrl / Shift / Ctrl+A multi-selection for backup cleanup and application-path removal. Backup cleanup uses the Windows Recycle Bin; application-path removal uses a combined preview and backup. Backup restoration and preference editing remain single-selection operations. No tests were run for this release; the 2.1.0 validation record does not cover the new multi-selection behavior.

Adapted from [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU), under **AGPL-3.0**. Third-party licenses and corresponding source archives are retained.
