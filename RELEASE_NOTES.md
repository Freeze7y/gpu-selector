# GPU Selector 2.1.0

**正式版 · 2026-09-07 · Windows x64**

基于 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) 改编，保留上游归属，按 **AGPL-3.0** 发布。作者：**Freeze7y**。

下载 **GPUSelector-v2.1.0-windows-x64.exe** 即可运行，无需安装 Python。便携 ZIP 附带说明和许可证，源码与 Qt / PySide 对应源码附件供开发者使用。

## 本次新增

- **清除所选备份**：在“备份与日志 → 备份管理”选中文件并确认，将其移到 Windows 回收站，不更改 GPU 设置。不自动把暂时无法恢复的备份当成无用文件；清除最近备份后同步禁用对应撤销按钮。
- **检查更新**：“外观与说明”增加按钮，从本 GitHub 仓库查找新版。下载后验证文件大小与 SHA-256，再退出、覆盖原 EXE 并重新启动；安装失败尝试恢复保留的旧程序。
- **启动检查开关**：首次正常启动询问并保存选择。开启后每次启动检查，发现新版仍先确认，之后才下载安装。正式版只提示新的正式版本，不自动降级或切换到测试版。
- **作者与仓库**：软件右上角显示 Freeze7y 和可点击的 GitHub 仓库地址。

更新保留原数据目录中的设置、方案、备份和日志。2.0.x 版本尚无在线更新功能，需要先手动下载一次本版。源码运行不会被原位替换成 EXE。

## 验证与限制

**255 项自动化测试通过**，覆盖备份清除、确认取消、文件变化拦截、更新版本比较、下载校验、安装与恢复、界面交互和已有 GPU 功能。使用专用测试文件验证回收站操作，实际网络下载核对 GitHub 大小与 SHA-256；用户的真实备份和 GPU 配置未用于破坏性测试。

源码与最终 EXE 的 32 / 64 位 OpenGL、Direct3D 11 和许可证烟雾检查均通过，退出码为 0。隔离的旧版副本已完成真实更新：覆盖中文及空格路径、文件占用重试、原位替换与新界面启动，配置方案、备份和日志测试文件保持不变。

故意阻止新版启动确认的实测中，更新程序已自动恢复并重新启动旧版；配置方案与备份保持原样，原日志完整保留并追加故障记录。

**Windows 10 实机运行、真实 GPU 配置切换、UAC 及重启后的切换效果尚未实机验证。**Win10 兼容性静态检查及官方依据见 [兼容性说明](https://github.com/Freeze7y/gpu-selector/blob/v2.1.0/docs/WINDOWS10_COMPATIBILITY.md)。探针结果只代表探针进程，注册表读回成功不代表所有软件都已使用指定显卡。

更新流程及故障处理见 [在线更新说明](https://github.com/Freeze7y/gpu-selector/blob/v2.1.0/docs/UPDATING.md)。

## English

Stable release with manual backup cleanup via the Windows Recycle Bin, GitHub update checks, verified in-place EXE replacement, opt-in startup checks and a visible author/repository link. Each available update requires confirmation; stable installations only offer newer stable releases. Existing GPU settings, profiles, backups and logs are preserved.

Windows 10 execution, actual GPU switching, UAC and post-reboot GPU switching remain untested. See the compatibility and update documentation for the verified scope and limitations.

Adapted from [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU), under **AGPL-3.0**. Third-party licenses and corresponding source archives are retained.
