"""Read-only device health and local diagnostic history for GPU Selector."""
from collections import deque
import ctypes
from ctypes import wintypes
import datetime
import json
import math
import os
from pathlib import Path
import tempfile
import time

from gpu_core import CLASS, PCI, Registry, value

DN_STARTED = 0x00000008
DN_HAS_PROBLEM = 0x00000400
CM_PROB_DISABLED = 22
LOG_NAME = 'operations.jsonl'
REBOOT_NAME = 'opengl-reboot.json'


def device_status(instance_id):
    """Read a current devnode. No phantom nodes or device changes are requested."""
    cfg = ctypes.WinDLL('cfgmgr32')
    locate = cfg.CM_Locate_DevNodeW
    locate.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR, wintypes.ULONG]
    locate.restype = wintypes.ULONG
    get_status = cfg.CM_Get_DevNode_Status
    get_status.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG),
                          wintypes.ULONG, wintypes.ULONG]
    get_status.restype = wintypes.ULONG
    node, flags, problem = wintypes.ULONG(), wintypes.ULONG(), wintypes.ULONG()
    result = locate(ctypes.byref(node), ctypes.create_unicode_buffer(instance_id), 0)
    if result:
        raise OSError(f'无法定位当前设备：CONFIGRET=0x{result:08X}')
    result = get_status(ctypes.byref(flags), ctypes.byref(problem), node, 0)
    if result:
        raise OSError(f'无法读取设备状态：CONFIGRET=0x{result:08X}')
    code = problem.value if flags.value & DN_HAS_PROBLEM else 0
    return dict(flags=flags.value, problem=code, disabled=code == CM_PROB_DISABLED,
                started=bool(flags.value & DN_STARTED))


def health_rows(gpus, db=None):
    db = Registry() if db is None else db
    from device_presence import present_pci_ids
    instances, scan_error = {}, ''
    try:
        present = present_pci_ids()
        for device in db.children('HKLM', PCI):
            for instance in db.children('HKLM', PCI + '\\' + device):
                instance_id = 'PCI\\' + device + '\\' + instance
                if instance_id.upper() not in present:
                    continue
                driver = value(db, 'HKLM', PCI + '\\' + device + '\\' + instance, 'Driver')
                if isinstance(driver, str):
                    instances.setdefault(driver.lower(), []).append(instance_id)
    except OSError as exc:
        scan_error = str(exc)
    result = []
    for gpu in gpus:
        row = dict(key=gpu['key'], name=gpu['name'], version='', date='',
                   present=bool(gpu.get('present')), disabled=None, problem=None,
                   status='状态未知', error='')
        try:
            path = CLASS + '\\' + gpu['key']
            row['version'] = str(value(db, 'HKLM', path, 'DriverVersion') or '未知')
            row['date'] = str(value(db, 'HKLM', path, 'DriverDate') or '未知')
            if scan_error:
                raise OSError(scan_error)
            ids = instances.get((CLASS.split('\\')[-1] + '\\' + gpu['key']).lower(), [])
            row['present'] = bool(ids)
            if not ids:
                row['status'] = '未检测到当前 PCI 设备'
            else:
                states = [device_status(i) for i in ids]
                row['disabled'] = any(s['disabled'] for s in states)
                row['problem'] = next((s['problem'] for s in states if s['problem']), 0)
                row['status'] = ('已禁用（代码 22）' if row['disabled'] else
                                 f'设备错误（代码 {row["problem"]}）' if row['problem'] else
                                 '设备已启动，无问题代码' if all(s['started'] for s in states) else
                                 '设备未启动，无问题代码')
        except (OSError, ValueError) as exc:
            row['error'] = str(exc)
            row['status'] = '读取失败，健康状态未知'
        result.append(row)
    return result


def write_log(data_dir, action, result, details=''):
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    entry = dict(time=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                 action=str(action), result=str(result), details=str(details))
    path = folder / LOG_NAME
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return path


def read_logs(data_dir, limit=500):
    """Load a bounded tail, keeping malformed lines visible as diagnostic errors."""
    path = Path(data_dir) / LOG_NAME
    if not path.exists():
        return []
    if limit <= 0:
        return []
    with path.open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - 2 * 1024 * 1024))
        if stream.tell():
            stream.readline()  # An incomplete first line is not a damaged record.
        lines = deque(stream, maxlen=limit)
    result = []
    for line in lines:
        try:
            entry = json.loads(line.decode('utf-8'))
            if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str)
                    for k in ('time', 'action', 'result', 'details')):
                raise ValueError('日志字段无效')
            result.append(entry)
        except (UnicodeError, ValueError) as exc:
            result.append(dict(time='', action='日志读取', result='损坏记录', details=str(exc)))
    return result


def export_logs(data_dir, destination):
    """Export all records byte-for-byte; reject overwriting the live log itself."""
    import shutil
    source, destination = Path(data_dir) / LOG_NAME, Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('请选择日志目录以外的导出文件，不能覆盖正在使用的日志。')
    if source.exists():
        shutil.copyfile(source, destination)
    else:
        destination.write_text('', encoding='utf-8')
    return destination


def boot_marker():
    kernel = ctypes.WinDLL('kernel32')
    tick = kernel.GetTickCount64
    tick.argtypes = []
    tick.restype = ctypes.c_ulonglong
    uptime_ms = tick()
    now = time.time()
    return dict(boot_utc=now - uptime_ms / 1000, uptime_ms=uptime_ms, observed_utc=now)


def record_gl_change(data_dir, label, marker=None):
    marker = boot_marker() if marker is None else marker
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / REBOOT_NAME
    record = dict(schema=1, label=str(label), marker=marker)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                         prefix='reboot-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return path


def reboot_status(data_dir, marker=None):
    path = Path(data_dir) / REBOOT_NAME
    if not path.exists():
        return dict(state='none', text='本工具没有记录需要重启的 OpenGL 修改。')
    try:
        if path.stat().st_size > 16384:
            raise ValueError('重启记录过大')
        saved = json.loads(path.read_text(encoding='utf-8'))
        old = saved['marker']
        current = boot_marker() if marker is None else marker
        if saved.get('schema') != 1:
            raise ValueError('重启记录版本无效')
        for item in (old, current):
            for key in ('boot_utc', 'uptime_ms', 'observed_utc'):
                if type(item[key]) not in (int, float) or not math.isfinite(item[key]) or item[key] < 0:
                    raise ValueError('重启记录时间无效')
        # Clock adjustments can move a derived boot timestamp. Only a reduced
        # monotonic uptime proves a new kernel boot; otherwise report uncertainty.
        if current['uptime_ms'] + 1000 < old['uptime_ms']:
            return dict(state='restarted', text='已检测到 OpenGL 修改后的系统重新启动；可再次运行渲染探针。')
        if abs(current['boot_utc'] - old['boot_utc']) <= 120:
            return dict(state='pending', text='OpenGL 修改后尚未检测到重启。请使用 Windows“重启”；睡眠或快速启动关机不算完整重启。')
        return dict(state='unknown', text='启动时间或系统时钟发生变化，无法可靠确认是否已重启；请重启后再实测渲染器。')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return dict(state='unknown', text='重启状态未知：' + str(exc))
