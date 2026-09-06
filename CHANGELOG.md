# 更新记录 / Changelog

## 2.0.1-beta — 2026-09-06

首个公开测试版。基于 [nethe-GitHub/select_default_GPU](https://github.com/nethe-GitHub/select_default_GPU) 改编，源码直接位于仓库根目录。

### 功能

- 保留 Windows 图形选项、DirectX 默认高性能 GPU、OpenGL ICD 选择和 BAT 导出。
- 增加桌面 EXE 自动 / 节能 / 高性能偏好与当前配置读取，保留其他应用参数。
- 增加独立的 32 / 64 位 OpenGL 探针和 Direct3D 11 离屏清色、像素回读测试。
- 增加修改前后预览、预览期间外部变化检查、备份列表和恢复资格检查。
- 增加 OpenGL 重启状态、JSONL 操作日志及导出、驱动版本与设备问题代码。
- 增加命名方案、显卡和驱动匹配校验、深浅主题、字体调整及窗口记忆。

### 修复与公开发布准备

- 修复 EXE 路径分隔符导致现有偏好误显示为自动的问题。
- 修复未知、重复和异常应用偏好可能被当作有效设置的问题；自动恢复同时清除相关显卡指定项。
- 保留刷新前的待选项和检查结果，更新可见应用列表，改善窄窗口与大字体下的操作布局。
- 检查配置方案的硬件变化、重复应用路径和驱动有效性，避免应用到不匹配的设备。
- 保持 x86 探针运行时独立打包，避免混入 x64 依赖分析。
- 将内部版本误写的 GPL-3.0 标注更正为原项目的 **AGPL-3.0**，保留上游归属和第三方许可证。
- 发布文档不包含本机账户路径、机器标识、真实日志备份或硬件测试报告。

### 验证

**122 项自动化测试全部通过。**源码和打包 EXE 的 `--smoke-all` 均通过 32 位 OpenGL、64 位 OpenGL、Direct3D 11 探针；D3D11 像素回读通过，成品退出码为 0。完成小窗口、主题和字体适配检查。

**未实机测试真实 GPU 配置切换、UAC 和重启后的切换效果。**注册表写入、回滚和恢复使用模拟数据验证。运行时探针只能说明自身进程使用的设备，不能推断所有应用的显卡选择。

### English

First public beta: Python GUI, app preferences, isolated OpenGL/D3D11 probes, preview and backup management, profiles, diagnostics and appearance settings. Corrects the license label to AGPL-3.0. All 122 automated tests and packaged probe smoke tests passed; real GPU switching, UAC and post-reboot switching remain untested.
