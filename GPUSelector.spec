# Windows 10/11 provide UCRT and API-set forwarding DLLs themselves.
# Do not bundle unrelated copies injected by a build host's runtime.
from pathlib import Path

base = Path(SPECPATH)
a = Analysis([str(base / 'gpu_selector.py')], pathex=[str(base)],
             binaries=[], datas=[(str(base / 'gpu.ico'), '.'), (str(base / 'LICENSE'), '.')],
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtNetwork', 'PySide6.QtSvg', 'PySide6.QtPdf',
                       'PySide6.QtQml', 'PySide6.QtQuick',
                       'PySide6.QtVirtualKeyboard', '_hashlib', '_ssl'],
             noarchive=False, optimize=0)

# This Widgets application uses the native raster renderer and Fusion style.
# PyInstaller's broad Qt hooks otherwise collect unrelated PDF/QML/Mesa/TLS
# plugins. Keep only the plugins exercised by this application's GUI/tests.
def keep_binary(entry):
    destination = Path(entry[0])
    name = destination.name.lower()
    if name.startswith(('api-ms-', 'ext-ms-', 'libcrypto-', 'libssl-')):
        return False
    if name in {'ucrtbase.dll', 'icuuc.dll', 'icuin.dll', 'icudt78.dll',
                'opengl32sw.dll'}:
        return False
    if 'plugins' in destination.parts:
        return name in {'qwindows.dll', 'qoffscreen.dll', 'qico.dll', 'qjpeg.dll'}
    if name.startswith('qt6'):
        return name in {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll'}
    return True

a.binaries = [entry for entry in a.binaries if keep_binary(entry)]
# Keep the independent x86 runtime intact, outside x64 dependency analysis.
for resource in sorted((base / 'probe32').rglob('*')):
    if resource.is_file() and '__pycache__' not in resource.parts and resource.suffix != '.pyc':
        a.datas.append((str(resource.relative_to(base)), str(resource), 'DATA'))
# Offline notices accompany the standalone EXE. Corresponding source archives
# remain separate downloads beside the binary on the same GitHub Release.
notices = base / 'third-party'
for resource in sorted(notices.rglob('*')):
    if resource.is_file() and ('licenses' in resource.relative_to(notices).parts
                              or (resource.parent == notices
                                  and resource.suffix.lower() in {'.md', '.json'})):
        a.datas.append((str(resource.relative_to(base)), str(resource), 'DATA'))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='GPU默认显卡选择器', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False,
          icon=[str(base / 'gpu.ico')])
