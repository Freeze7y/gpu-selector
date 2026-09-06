# 32 位 OpenGL 实测运行时

本目录附带 Python 官方 Windows x86 embeddable 运行时，供图形界面的隔离子进程调用。
不需要安装 Python，不会修改系统 Python、PATH 或显卡设置。

- 运行时版本：Python 3.13.15，32 位。
- 官方发布页：https://www.python.org/downloads/release/python-31315/
- 官方下载：https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-win32.zip
- 官方发布包 SHA-256：`3f5506367943d16dffa89f0ea140ebf04481a80611eb119e76e95aea8c79f5ce`
- `python.exe` 的 Python Software Foundation Authenticode 签名已验证有效。
- 原始许可保留在 `LICENSE.txt`，运行时文件按官方发布包分发。
- `runner.py` 和 `gl_probe.py` 是显卡选择器的 Python 探针源码。

调用：`python.exe runner.py 输出文件.json`。父进程必须设置超时并在超时时结束探针；
显卡驱动属于原生代码，不能只依赖 Python 异常处理。JSON 使用 UTF-8 编码。

该目录应作为数据原样打包到主 EXE 的 `probe32` 目录；32 位 DLL 不能放进主程序的
64 位二进制依赖列表。`python313._pth` 保持官方隔离配置，不加载用户 site-packages。
