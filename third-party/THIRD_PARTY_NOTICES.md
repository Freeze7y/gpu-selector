# 第三方组件、许可证与对应源码

适用版本：GPU Selector v2.0.2-beta，Windows x64 主程序与独立 x86 OpenGL 探针。

本程序使用 **Qt / PySide6 / Shiboken 6.11.2**。相关库以动态库形式装入进程，
本发行采用其 LGPLv3 开源许可选项；库中第三方代码按各自许可证提供。
程序自身的许可证见仓库根目录 `LICENSE`。这些条款不会把 Microsoft 运行库
或其他第三方组件改为程序自身的许可证。

用户可以取得、修改并重构建这些开源库，在本程序中使用修改后的兼容版本，
并为调试此类修改进行相关逆向工程。程序不要求官方签名，也没有限制替换 Qt 的校验。
具体操作见 [重构建与替换库说明](REBUILDING.md)。

## 实际打包范围

本表依据公开版 `GPUSelector.spec`、PyInstaller 打包目录和本地实际运行时核对。
文件级清单及 SHA-256 见 [BUNDLED_COMPONENTS.json](BUNDLED_COMPONENTS.json)。

| 组件 | 版本 / 范围 | 许可证与说明 |
|---|---|---|
| Qt Base | 6.11.2，x64，Qt6Core / Qt6Gui / Qt6Widgets | LGPL-3.0-only；[全文](licenses/qtbase-everywhere-src-6.11.2/LICENSES/LGPL-3.0-only.txt) 与其引用的 [GPLv3 全文](licenses/qtbase-everywhere-src-6.11.2/LICENSES/GPL-3.0-only.txt) |
| Qt 平台与图片插件 | 同上；qwindows、qoffscreen、qico、qjpeg | 均来自 Qt Base；图片处理代码还使用下面列出的第三方许可 |
| PySide6 与 Shiboken | 6.11.2，x64 | LGPL-3.0-only 选项；[全文](licenses/pyside-setup-everywhere-src-6.11.2/LICENSES/LGPL-3.0-only.txt)；保留源码中的其他许可证文本不表示本项目使用商业许可 |
| CPython 主运行时 | 3.12.14，x64 | [实际运行时 LICENSE.txt](licenses/Python-3.12.14-LICENSE.txt)；[此版本官方第三方声明](licenses/Python-3.12.14-THIRD-PARTY.rst) |
| CPython OpenGL 探针运行时 | 官方 3.13.15 Windows x86 embeddable 包 | [实际运行时 LICENSE.txt](licenses/Python-3.13.15-LICENSE.txt)；[此版本官方第三方声明](licenses/Python-3.13.15-THIRD-PARTY.rst)；原包许可同时保留在 `probe32/LICENSE.txt` |
| PyInstaller | 6.22.2，引导器和运行时装载代码 | GPL-2.0-or-later 加 Bootloader Exception；运行时 hooks 为 Apache-2.0；[完整条款](licenses/PyInstaller-6.22.2-COPYING.txt) |
| Microsoft Visual C++ Runtime | 随 Python / PySide6 原包提供的 x86 / x64 VCRUNTIME140 与 x64 MSVCP140 系列 | Microsoft 许可，非 LGPL；[条款全文](licenses/Microsoft-Visual-C-Runtime-2015-2022-LICENSE.txt)，以及上述 Python Windows 二进制附加条件 |

公开版不分发 Qt PDF、Qt Virtual Keyboard、QML / Quick、Qt Network / TLS 插件、
Mesa `opengl32sw.dll` 或主进程的 x64 OpenSSL DLL。
独立 `probe32` 保留官方 Python 嵌入包中的 x86 OpenSSL 等文件，
不能因此把整个发行包称为“不含 OpenSSL”。
Windows 自带的 Direct3D、DXGI、OpenGL、UCRT、ICU 等系统文件没有复制进发行包。

## Qt 内嵌第三方代码

Qt 的 DLL 除 Qt 自身外，还包含或可能根据其官方构建配置包含第三方实现。
本次没有重新编译官方 Qt wheel，因此不声称已经逐个识别所有静态链接对象。
为保留版权与许可，随包完整保存 **同一 6.11.2 官方源码包**的声明和原始许可文本：

- [Qt Base 完整版权与许可声明目录](qtbase-everywhere-src-6.11.2-ATTRIBUTIONS.md)
- [PySide / Shiboken 完整版权与许可声明目录](pyside-setup-everywhere-src-6.11.2-ATTRIBUTIONS.md)

该目录还包含构建工具、示例和非 Windows 平台条目；它们的出现不表示全部进入 EXE。
与保留模块相关的上游声明包括：FreeType（FTL / GPLv2 选项）、HarfBuzz（MIT）、
LibJPEG-turbo（IJG 与 BSD）、LibPNG（libpng / PNG Reference Library）、
zlib（Zlib）、PCRE2（BSD 与其二进制包例外）、double-conversion（BSD）、
TinyCBOR（MIT）、MD4C（MIT）、D3D12 / Vulkan Memory Allocator（MIT）、
Khronos 头文件（MIT）、Unicode 数据、Qt 图像变换与栅格器代码的独立许可。
各项作者、版本、配置条件及全文链接以目录中的原始声明为准。

FreeType 项目致谢：本软件的一部分基于 FreeType 团队的工作。
JPEG 项目致谢：本软件的一部分基于 Independent JPEG Group 的工作。

## Python 内嵌第三方代码

两个 Python `LICENSE.txt` 保留 PSF、历史许可证、Windows 运行时附加条件、
bzip2 和 libffi 文字。它们不是完整的 Python 第三方组件清单，因此本目录另外提供
上述两个版本的官方 `Doc/license.rst`，以及单独的 Expat、HACL 和 XZ / LZMA 说明。

- x86 运行时的官方 [SPDX 清单](Python-3.13.15-win32.spdx.json) 未经修改保留。
  它是 Python 发布者提供的整包清单，含某些可选或其他平台条目，不能直接当作
  本程序实际加载模块清单。
- x86 实际模块查询得到 OpenSSL **3.0.21**、SQLite **3.50.4**、zlib **1.3.1**、
  Expat **2.8.2**、libmpdec **4.0.0**。官方 SPDX 还声明 bzip2 **1.0.8**、
  libffi **3.4.4**、XZ **5.2.5**。OpenGL 探针本身只调用 ctypes / Windows OpenGL。
- x64 实际模块查询得到 zlib **1.3.2**、libmpdec **2.5.1**；其余内嵌库没有
  单独断言精确构建版本。x64 运行时来源是本机已有 CPython 3.12.14 构建，
  不将其误称为 python.org 的官方 Windows 安装包（3.12.14 官方仅提供源码）。
- OpenSSL 3 使用 Apache-2.0；完整 Apache 文本也在 x86 Python LICENSE 中。
  SQLite 采用公共领域声明；libffi 为 MIT；bzip2 为其自有宽松许可证。
  [XZ / LZMA 条款](licenses/XZ-LZMA-COPYING.txt) 区分库代码和上游工具的许可。
  [3.12 HACL 声明](licenses/Python-3.12.14-HACL-NOTICES.txt)、
  [3.13 HACL 声明](licenses/Python-3.13.15-HACL-NOTICES.txt)、
  [3.12 Expat 许可](licenses/Python-3.12.14-Expat-COPYING.txt)、
  [3.13 Expat 许可](licenses/Python-3.13.15-Expat-COPYING.txt) 分别摘自准确版本官方源码。

## 对应源码与构建资料

**与二进制相同 Release 的 Assets 提供以下两个未经修改的官方源码压缩包：**

[v2.0.2-beta 发布页与源码下载](https://github.com/Freeze7y/gpu-selector/releases/tag/v2.0.2-beta)

| 文件 | SHA-256 |
|---|---|
| `qtbase-everywhere-src-6.11.2.tar.xz` | `5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22` |
| `pyside-setup-everywhere-src-6.11.2.tar.xz` | `cba47efbaad1bedd529725cbc14e21f156c7a19366f07b3edfbb076ffd7afdf8` |

原始来源及校验元数据：

- [Qt Base 官方下载与 SHA-256](https://download.qt.io/archive/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz.mirrorlist)
- [PySide / Shiboken 官方下载与 SHA-256](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz.mirrorlist)
- [Python 3.12.14 官方源码](https://www.python.org/downloads/release/python-31214/)
- [Python 3.13.15 官方源码、x86 原包及 SPDX](https://www.python.org/downloads/release/python-31315/)
- [PyInstaller 源码与许可](https://github.com/pyinstaller/pyinstaller/tree/v6.22.2)

本项目没有修改 Qt / PySide / Shiboken 库源码。发布源码包含本程序的 Python 源码、
打包 spec、依赖版本与测试；详见 [REBUILDING.md](REBUILDING.md)。
这是依赖核对与分发说明，不代表完成了全面法律审查，也不替代各许可证原文。

Microsoft 条款仅针对其组件，不限制 LGPL 所赋予的 Qt / PySide / Shiboken 权利。
Qt、Python、Microsoft 等名称与商标归各自权利人；本项目不表示受到其背书。
