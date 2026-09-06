# GPU Selector 2.0.1-beta

**首个公开测试版 · 2026-09-06 · Windows x64**

本项目基于 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) 改编，保留原项目归属，按 **AGPL-3.0** 发布。

普通用户下载 **GPUSelector-v2.0.1-beta-windows-x64.exe** 即可运行，无需安装 Python；也可选择包含说明和许可证的同名便携 ZIP。Qt / PySide 源码附件供开发者使用。源码、依赖版本、构建脚本和测试随仓库提供。

本版保留原工具的 Windows 图形设置、DirectX 默认高性能 GPU、OpenGL ICD 选择与 BAT 导出，并加入：

- 按 EXE 设置自动 / 节能 / 高性能偏好，显示当前状态。
- 32 / 64 位 OpenGL 实际渲染器探针与 Direct3D 11 离屏清色、像素回读。
- 修改预览、外部变化检查、自动备份、读回校验、失败回滚及历史恢复列表。
- 重启状态、操作日志、显卡驱动和设备问题信息。
- 配置方案、深浅主题、字体调整与窗口记忆。

**验证结果：122 项自动化测试全部通过；源码与打包 EXE 的三个实际探针均通过，成品烟雾测试退出码为 0。**

**测试边界：尚未在实机执行真实 GPU 配置切换、UAC 授权和重启后的切换验证。**注册表修改、回滚和恢复使用模拟数据测试。因此本版标记为 beta，不承诺所有驱动或应用都遵循设置。

应用偏好由 Windows 决定具体 GPU；运行时探针仅代表探针进程。OpenGL 原方法有驱动和兼容包限制，首次使用需要重启。修改前请检查预览，修改后重新启动目标应用并验证。

本项目于 **2026-09-06** 改编自 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU)，按 **AGPL-3.0** 发布。内部版本曾误标为 GPL-3.0，现已更正；原项目归属及随附第三方许可证均保留。

## English

First public beta for 64-bit Windows. The standalone EXE needs no Python installation. Includes per-app GPU preferences, isolated 32/64-bit OpenGL and Direct3D 11 probes, change previews, backups, profiles, logs and appearance settings.

All **122 automated tests** and all three real probes passed for source and packaged smoke tests. **Actual GPU switching, UAC and post-reboot switching were not tested on a real system.** Probe results apply only to their own processes.

Adapted from [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) on 2026-09-06, under **AGPL-3.0**. Third-party licenses are retained.
