# 重构建程序与替换 Qt / PySide

本程序提供完整 Python 源码和打包配置。你可以修改程序，也可以修改开源 Qt、
PySide6 和 Shiboken 后重新构建、运行。发行 EXE 没有阻止此操作的签名或密钥检查。

## 按原依赖重新打包

在 Windows x64 上安装 64 位 Python（发行主程序使用 3.12.14），下载本项目源码，
保留 `probe32` 原包与源码。创建自己的虚拟环境并在其中运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s . -p 'test_*.py'
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm GPUSelector.spec
```

输出文件位于 `dist`。`build.ps1` 也提供完整的依赖安装、测试和打包流程。
不同 Python、工具链、路径、构建时间会改变 EXE 字节；这些说明不承诺逐字节可复现。

## 使用修改后的 Qt / PySide

1. 从 [同一 Release](https://github.com/Freeze7y/gpu-selector/releases/tag/v2.1.0)
   取得 `qtbase-everywhere-src-6.11.2.tar.xz` 与
   `pyside-setup-everywhere-src-6.11.2.tar.xz`，按
   [第三方声明](THIRD_PARTY_NOTICES.md) 中 SHA-256 校验。两包包含其构建脚本。
2. 在 x64 MSVC 开发环境准备相应编译器、Windows SDK、CMake、Ninja；
   PySide 生成绑定还需要 Qt 官方文档要求的 libclang。按
   [Qt Windows 源码构建文档](https://doc.qt.io/qt-6/windows-building.html)
   构建并安装修改后的共享 Qt Base。保持 release / x64 / shared 配置，
   保留 Core、Gui、Widgets、Windows 平台与需要的图片插件。
3. 按 [Qt for Python 源码构建文档](https://doc.qt.io/qtforpython-6/building_from_source/index.html)
   对修改后的 Qt 构建 PySide / Shiboken。官方构建入口支持
   `--qtpaths=你的Qt安装目录\bin\qtpaths.exe`、`--ignore-git`、
   `--module-subset=Core,Gui,Widgets` 和 `--standalone`。
   使用 `python setup.py bdist_wheel` 生成与你的 x64 Python 匹配的 wheel。
   最稳妥的是 Qt 与 PySide 使用相同的 6.11.2 版本；修改接口后应一并重建绑定。
4. 在本程序的独立构建环境中安装你生成的 wheel（必要时替换原来的
   PySide6_Essentials、PySide6 与 Shiboken6），确认
   `python -c "from PySide6.QtCore import QLibraryInfo; print(QLibraryInfo.build())"`
   能导入。先用 `python gpu_selector.py` 运行源码验证自建库。
5. 直接运行该环境中的 `python -m PyInstaller --clean --noconfirm GPUSelector.spec`
   重新打包。使用自建库时不要再运行会安装原始 wheel 的依赖安装命令；
   若改了包版本，也应相应调整 `requirements.txt`。
6. 在自己的可写目录执行 `GPU默认显卡选择器.exe --smoke-all 输出目录`，
   检查图形界面和三个只读探针。不同显卡、驱动和自建库可能产生不同结果。

主 EXE 在运行时解压后动态加载 Qt DLL。可编辑的源码、依赖环境和 spec 是稳定的
替换入口；不需要在每次启动产生的临时解压目录里手动竞争替换 DLL。
你也可以自行改变 spec 的打包方式，直接分发可替换 DLL 的目录式应用。

`probe32` 的 32 位 Python / OpenGL 探针与主界面的 x64 Qt 库独立。
替换 Qt 不要求替换此探针；若替换它，应保持 32 位运行时并保留对应许可。

程序源码重打包和原始发行包的功能检查已经执行。此说明提供修改 Qt 的构建路径，
本次没有替用户重新编译整个 Qt / PySide 工具链，也不声称验证过每一种修改组合。
