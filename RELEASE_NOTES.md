# GPU Selector 2.0.2-beta

**公开测试版 · 2026-09-07 · Windows x64**

基于 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) 改编，保留上游归属，按 **AGPL-3.0** 发布。

下载 **GPUSelector-v2.0.2-beta-windows-x64.exe** 即可运行，无需安装 Python；便携 ZIP 另附说明和许可证。Qt / PySide 源码附件供开发者使用。

## 本次更新

- 应用列表增加 **“清除所选路径…”**：完整删除选中路径的图形设置记录，包括 GPU 偏好、Auto HDR 和窗口化优化。不删除 EXE 或文件夹。
- 清除前显示完整路径及修改预览，自动备份，清除后读回验证；可在“备份与日志”恢复。
- 修复删除最后一行后自动选中另一条记录的问题，防止连续点击误清；输入新路径会取消列表选择。
- 列表中的原始路径按精确注册表名称读取、校验和修改，避免规范化后操作另一条记录。
- 增加 [Windows 10 兼容性说明](https://github.com/Freeze7y/gpu-selector/blob/v2.0.2-beta/docs/WINDOWS10_COMPATIBILITY.md)。Win10 优先验证目标为 22H2 x64；暂未发现必须另做专用版的依据，仍使用统一构建。

“文件不存在”可能是移动或卸载程序留下的旧设置，也可能是对应磁盘暂不可用。请检查所选完整路径后确认清除。“恢复自动选择”继续保留 HDR 等非 GPU 参数，和完整清除的用途不同。

## 验证范围

**150 项自动化测试全部通过**，验证清除、取消、刷新选择、备份恢复及现有功能；源码与打包 EXE 的 32 / 64 位 OpenGL、Direct3D 11 三个探针和离线许可证烟雾检查均通过，退出码为 0。完成普通窗口与 640×520 小窗口下的按钮布局检查。

**尚未在 Windows 10 实机或虚拟机运行本版；实际 GPU 设置切换、UAC 和重启后的切换效果也未实机验证。**注册表修改使用内存模拟测试，未清除测试电脑的真实应用设置。依赖支持 Win10 不等于实际功能已验证，因此仍标记为 beta。探针结果仅代表探针进程，应用偏好由 Windows 和应用决定具体 GPU。

## English

Adds complete removal of selected per-EXE graphics settings, including HDR options, with preview, backup and read-back verification. Application files are never deleted. Fixes unintended row selection after deletion and preserves exact registry value names when operating on listed entries.

Windows 10 execution, actual GPU switching, UAC and post-reboot behavior remain untested. A single x64 build is provided; see the compatibility notes for dependencies and limitations.

Adapted from [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU), under **AGPL-3.0**. Third-party licenses and corresponding source archives are retained.
