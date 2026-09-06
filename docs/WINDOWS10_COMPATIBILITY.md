# Windows 10 兼容性审计

以下保留 v2.1.0 的审计记录。v2.1.1 仅增加清除列表多选交互，未重新运行兼容性测试或二进制审计；历史结果不代表 v2.1.1 已在 Windows 10 实机验证。

审计日期：2026-09-07。对象：v2.1.0 的 Python 源码、`GPUSelector.spec`、新生成的 x64 EXE，以及本次构建清单中的运行时依赖。先读取 EXE 内嵌的 `app_version.VERSION` 确认其为 2.1.0，再逐项提取 64 个依赖 PE 文件核对 SHA-256 和架构，并重新检查新 EXE 的导入表与 manifest。

**目前没有发现要求 Windows 11 才能启动的明确二进制依赖；现有版本应优先在 Windows 10 22H2 x64（build 19045）上验证。Qt 6.11 的官方框架支持下限是 Windows 10 1809 x64（build 17763），但这不等于本程序全部显卡设置功能已在这些系统上验证。当前没有证据需要另做一份 Windows 10 专用 EXE。**

这是源码和 PE 依赖静态审计，并结合当前主机的运行记录，**不是 Windows 10 实机兼容性认证**。后续若在真实 Windows 10 上发现问题，应先记录系统 build、驱动、错误和具体功能，再决定修复通用版本还是提供单独版本。

## 已确认的运行环境与架构

测试主机为 Windows 11 25H2，不是 Windows 10。[微软 Windows 11 版本信息](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information)

已检查的主程序是 AMD64 / x64 PE；内嵌 manifest 包含 Windows 10 的 `supportedOS` GUID。主程序不支持 32 位 Windows。`probe32` 只是供 x64 系统启动的独立 32 位 OpenGL 检测进程，不会使主程序变成 x86 版本。Windows ARM64 和模拟运行环境不在本次验证范围内。

当前 Windows 11 主机上的冻结 EXE 启动、GUI 和三项探针运行记录，只能作为该主机的验证证据；不能替代 Windows 10 测试。

## 运行时与 DLL 检查

| 部分 | 本次检查结果 | Windows 10 判断 |
| --- | --- | --- |
| PySide6 / Qt 6.11.2 | QtCore、QtGui、QtWidgets；MSVC 2022 构建；使用 Widgets / Fusion 界面 | Qt 6.11 官方支持 Windows 10 1809 及以上 x64。这是当前框架下限。[Qt 官方平台说明](https://doc.qt.io/qt-6/windows.html) |
| 主 Python 3.12.14 x64 | 随 EXE 分发；来自本次构建环境的运行时 | Python 3.12 的 Windows 文档覆盖 Windows 10；但 3.12.14 发布页是源码发行，不能将本次 x64 运行时称为该版本的 python.org 官方安装器二进制。[Python 3.12 Windows 文档](https://docs.python.org/3.12/using/windows.html)、[3.12.14 发布页](https://www.python.org/downloads/release/python-31214/) |
| Python 3.13.15 x86 | `probe32` 使用 python.org 的 Windows embeddable 包；目录独立打包 | Windows 10 在 Python 3.13 的 Windows 平台范围内；需在目标系统确认 32 位驱动 ICD 和辅助进程能正常加载。[Python 3.13 Windows 文档](https://docs.python.org/3.13/using/windows.html) |
| PyInstaller 6.22.2 | 主程序为原生 x64 bootloader；probe32 作为 DATA 保持 x86 文件不变 | 官方要求 Windows 8 或更新；不会单独把本包下限提高到 Windows 11。其他依赖的较高下限仍然适用。[PyInstaller 要求](https://pyinstaller.org/en/stable/requirements.html) |
| Qt 系统 ICU | `Qt6Core.dll` 导入 `icuuc.dll` 的 20 个传统字符转换 C 接口；未导入新合并的 `icu.dll` | 微软从 Windows 10 1703 内置 `icuuc.dll` / `icuin.dll`；`icu.dll` 则从 1903 才有。当前导入形式没有造成 1809 的已知 DLL 缺失问题，未发现 Win11 专用 ICU 入口。[微软 ICU 说明](https://learn.microsoft.com/en-us/windows/win32/intl/international-components-for-unicode--icu-) |
| UCRT、API-set、VC Runtime | UCRT / API-set 由系统提供；所需 VC Runtime 随包分发；x86 运行时独立 | 需要完整、正常更新的 Windows 安装。没有将构建机 Windows 11 的 ICU、UCRT 或 API-set 转发 DLL 复制进主程序包。 |
| 在线更新的 WinHTTP | 通过 ctypes 从 System32 加载系统 `winhttp.dll`；使用 TLS 1.2、系统证书校验和系统代理 | 所用自动代理模式从 Windows 8.1 起受支持，不会把当前 Qt 的 Windows 10 1809 下限提高到 Windows 11。未为在线更新新增 QtNetwork 或 x64 OpenSSL。[WinHttpOpen 与自动代理](https://learn.microsoft.com/en-us/windows/win32/api/winhttp/nf-winhttp-winhttpopen) |
| 备份回收站 | 调用 QtCore 的 `QFile.moveToTrash()`，使用操作系统回收站机制；失败时报告错误，不退回永久删除 | Qt 说明该操作通过当前系统的回收站机制完成；具体路径、权限和回收站设置仍需在目标 Windows 10 上验证。[QFile 回收站 API](https://doc.qt.io/qt-6/qfile.html#moveToTrash) |

新 EXE 内嵌的 **64 个依赖 PE 文件：35 个 AMD64 文件和 29 个位于 `probe32` 的 x86 文件**，其 SHA-256 全部符合 `third-party/BUNDLED_COMPONENTS.json`，与前次审计相比没有新增、删除或改变 PE 文件。35 个主运行时依赖与本次 Analysis 清单中的源文件哈希一致；29 个 x86 文件仍通过 Analysis 之后的独立 DATA 注入打包。新主 EXE 的导入表与前次审计一致，manifest 仍包含 Windows 10 支持声明。PE 头的最高 OS / subsystem 字段是 6.0；这个字段不能证明 Windows Vista 或旧 Windows 10 版本兼容，真正下限还受 DLL 导出、运行时动态加载和框架要求限制。

SHA-256 等摘要实现所需的 `_sha2`、`_sha1`、`_md5`、`_sha3`、`_blake2` 已内建于本次使用的 CPython 主运行时，无需新增独立 x64 PE 模块。现有 CPython 与 HACL 许可文本已随包分发；本次未识别出新增的第三方许可组件。系统 WinHTTP 本身没有复制进发行包。

重点检查中发现的较新入口仍属于 Windows 10 或更早版本：

- Qt 导入 `SetThreadDescription`。微软标注 Windows 10 1607 起可用，但 1607 / LTSB 2016 只能从 KernelBase 动态获取；因此不能据此承诺旧版 1607 支持。当前框架要求的 1809 高于这个版本。[SetThreadDescription](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setthreaddescription)
- Qt 窗口插件涉及 `SetProcessDpiAwarenessContext` 等 DPI 接口，其中该接口最低为 Windows 10 1703。[DPI 接口要求](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)
- QtGui 也导入 D3D12 的 `D3D12SerializeVersionedRootSignature`，虽然本程序本身采用 Widgets 界面。微软说明该入口在 Windows 10 Anniversary Update / build 14393 引入。[D3D12 接口说明](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-d3d12serializeversionedrootsignature)

这些检查没有找出 Windows 11 独占静态入口，但没有逐个在 Windows 10 系统 DLL 上验证全部导出，也没有涵盖全部动态加载路径。最有价值的下一步仍是目标系统实际启动测试。

## 必须区分的三种 GPU 功能

### 按应用设置节能 / 高性能偏好

微软的 Windows 10 图形设置文档介绍了系统默认、节能和高性能的按应用选项，并明确说明应用仍可以自行选择 GPU。微软的 `IDXGIFactory6::EnumAdapterByGpuPreference` API 最低支持 Windows 10 1803。[Windows 10 图形偏好介绍](https://blogs.windows.com/windows-insider/2018/02/07/announcing-windows-10-insider-preview-build-17093-pc/)、[DXGI API 要求](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_6/nf-dxgi1_6-idxgifactory6-enumadapterbygpupreference)

本程序实际通过 `HKCU\Software\Microsoft\DirectX\UserGpuPreferences` 中的 `GpuPreference` 字段设置应用偏好，并未调用上述 DXGI 枚举 API。这里引用 DXGI 文档用于说明平台能力，不能把它当作注册表格式的公开稳定契约。配置写入后应先在 Windows 图形设置页核对，再重启目标应用并观察实际 GPU。

### 指定全局默认高性能 GPU

`HighPerfAdapter`、`DefaultHighPerfGPUApplicable` 和 `SpecificGPUOptionApplicable` 是本程序继承的全局配置方式。微软在 **Windows 10 Insider Dev build 20190** 的发布说明中介绍了“指定默认高性能 GPU”和按应用指定具体 GPU。[微软 build 20190 说明](https://blogs.windows.com/windows-insider/2020/08/12/announcing-windows-10-insider-preview-build-20190/)

这条 Insider 文档不能证明稳定版 Windows 10 1809 或 22H2 实现了同一配置协议，也不能用 Qt 的 1809 框架下限推导全局功能下限。没有找到承诺上述原始注册表字段在所有这些稳定版本生效的微软公开 API 文档。**全局设置在 Windows 10 上应标为待实机验证；注册表读回一致只能表示配置存在。** 不应显示或宣传“所有程序已切到指定 GPU”。

### OpenGL 注册表设置和实际渲染检测

OpenGL 的 `wglCreateContext` 是长期提供的 Windows API，D3D11 探针采用的 `D3D11CreateDevice` 在 Windows 7 已有；这些接口本身不会要求 Windows 11。设备枚举的 `CM_GETIDLIST_FILTER_PRESENT` 标志在 Windows 7 已提供。[WGL 要求](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-wglcreatecontext)、[D3D11 要求](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-d3d11createdevice)、[设备枚举要求](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_get_device_id_listw)

但 `OpenGLDrivers\MSOGL` 以及驱动类键的调整是原程序继承的驱动注册表方案，不能因为 WGL API 可用，就推导不同 Windows 10、显卡厂商和驱动版本都支持该调整。必须在对应 GPU / 驱动的 Windows 10 环境检查备份、设置、重启后实际渲染和恢复。

三项探针结果表示各自检测进程在当时创建上下文或设备时实际使用的 GPU。D3D11 探针还执行离屏清屏和像素读回。这些结果不代表所有其他程序，也不能用虚拟机的虚拟 GPU 测试代替实体多显卡的设置效果测试。

## 待进行的 Windows 10 验证

优先目标是 Windows 10 22H2 x64 / build 19045，另用 1809 x64 检查框架下限。当前未取得这些系统上的实测结果。

1. 在未安装开发环境或 Python 的干净系统，测试 EXE 启动、中文路径、普通用户和提权后启动、许可证查看、退出清理。记录 DLL / Qt 插件加载错误。
2. 测试窗口缩放、100% / 150% / 200% DPI、不同分辨率、跨显示器移动和文件对话框。确认按钮和表头可见。
3. 执行 `--smoke-all` 并保留报告，分别核对 64 位 OpenGL、32 位 OpenGL、D3D11 的位数、renderer、退出码和异常提示。纯虚拟机可以验证启动及错误处理，但可能没有厂商 GPU 驱动。
4. 在实体多 GPU Windows 10 机器上，对专用测试程序写入 / 恢复按应用偏好；核对 Windows 设置页，重启该测试程序，观察实际用卡。记录应用自行选择 GPU 的情况。
5. 在已有可恢复备份的实体机器上单独验证全局配置和 OpenGL 驱动配置；测试重启前后、32/64 位差异与完整恢复。未验证前保留“配置一致”和“实际渲染”的状态区别。
6. 在 Windows 10 上测试在线更新的系统代理、断网、取消、文件校验、覆盖与恢复，以及备份移入回收站。当前 Windows 11 上的真实 GitHub 下载校验结果，不能替代这些 Windows 10 测试。

发布描述建议采用：**“Windows 10 1809+ x64 为框架支持范围；优先适配目标 Windows 10 22H2 x64。当前已完成静态兼容审计，Windows 10 实机结果待补充；全局 GPU 配置效果受系统版本、驱动及应用行为影响。”**
