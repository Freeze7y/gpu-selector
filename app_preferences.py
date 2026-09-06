"""Per-desktop-EXE Windows GPU preferences; no registry writes in this module."""
import ntpath
from pathlib import Path
import winreg as reg

from gpu_core import PREF, operation

PREFERENCES = {0: '系统自动选择', 1: '节能', 2: '高性能'}
GPU_FIELDS = {'gpupreference', 'specificadapter'}


def valid_exe_path(path):
    if not isinstance(path, str) or not path or any(c in path for c in '\0\r\n"'):
        return False
    drive, tail = ntpath.splitdrive(path)
    return bool(drive and ntpath.isabs(path) and tail.lower().endswith('.exe'))


def normalize_exe(path, require_exists=False):
    path = ntpath.normpath(path.strip().strip('"')) if isinstance(path, str) else ''
    if not valid_exe_path(path):
        raise ValueError('请选择完整路径的 .exe 文件。')
    if require_exists and not Path(path).is_file():
        raise ValueError('应用文件不存在；请重新选择实际的 .exe 文件。')
    return path


def preference_state(raw, kind=reg.REG_SZ):
    """Report unknown/custom values without pretending they are automatic."""
    if raw is None:
        return 0, PREFERENCES[0]
    if kind != reg.REG_SZ or not isinstance(raw, str):
        return None, '异常注册表类型'
    fields = [part.partition('=') for part in raw.split(';') if part]
    if any(k.strip().lower() in GPU_FIELDS and not sep for k, sep, v in fields):
        return None, '格式异常的 GPU 偏好'
    values = [v.strip() for k, sep, v in fields if sep and k.strip().lower() == 'gpupreference']
    specific = any(k.strip().lower() == 'specificadapter' and v.strip() for k, sep, v in fields if sep)
    if specific:
        return None, 'Windows 指定 GPU（自定义）'
    if not values:
        return 0, PREFERENCES[0]
    if len(values) != 1 or values[0] not in ('0', '1', '2'):
        return None, '未知或重复的 GPU 偏好'
    mode = int(values[0])
    return mode, PREFERENCES[mode]


def preference_string(current, preference):
    if type(preference) is not int or preference not in PREFERENCES:
        raise ValueError('不支持的应用 GPU 偏好。')
    if current is not None and not isinstance(current, str):
        raise ValueError('应用设置的注册表类型异常，停止修改。')
    # SpecificAdapter is a related GPU override: leaving it would defeat auto/reset.
    fields = [part for part in (current or '').split(';')
              if part and part.partition('=')[0].strip().lower() not in GPU_FIELDS]
    if preference:
        fields.append(f'GpuPreference={preference}')
    return ';'.join(fields) + ';' if fields else None


def app_plan(db, path, preference, require_exists=False):
    path = normalize_exe(path, require_exists)
    old = db.read('HKCU', PREF, path, 64)
    if old is not None and (old[1] != reg.REG_SZ or not isinstance(old[0], str)):
        raise ValueError('应用设置不是字符串，停止修改。')
    return [operation('HKCU', PREF, path, preference_string(old[0] if old else None, preference))]


def list_app_preferences(db):
    items = []
    for name, raw, kind in db.values('HKCU', PREF, 64):
        if not valid_exe_path(name):
            continue
        mode, status = preference_state(raw, kind)
        items.append(dict(path=name, name=ntpath.basename(name), preference=mode,
                          status=status, exists=Path(name).is_file(), raw=raw, kind=kind))
    return sorted(items, key=lambda item: (item['name'].casefold(), item['path'].casefold()))
