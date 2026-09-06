"""Windows registry backend; port of nethe-GitHub/select_default_GPU (AGPL-3.0).

Python GUI adaptation and modifications: 2026-09-06.
Upstream: https://github.com/nethe-GitHub/select_default_GPU
"""
import datetime
import ctypes
import json
import os
import ntpath
import re
import winreg as reg
from pathlib import Path

CLASS = r'SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}'
PCI = r'SYSTEM\CurrentControlSet\Enum\PCI'
DX = r'Software\Microsoft\DirectX'
PREF = DX + r'\UserGpuPreferences'
GL = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\OpenGLDrivers\MSOGL'
GLOBAL = 'DirectXUserGlobalSettings'
ROOTS = {'HKLM': reg.HKEY_LOCAL_MACHINE, 'HKCU': reg.HKEY_CURRENT_USER}


def user_identity():
    """Use the process token, not editable environment variables, for restore ownership."""
    from ctypes import wintypes as wt
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    token = wt.HANDLE()
    kernel.GetCurrentProcess.restype = wt.HANDLE
    advapi.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [wt.LPVOID, ctypes.POINTER(wt.LPWSTR)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    kernel.LocalFree.argtypes = [wt.LPVOID]
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wt.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(data, ctypes.POINTER(wt.LPVOID))[0]
        text = wt.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def backup_identity(db, plan):
    drivers = {op['path'] for op in plan if op['root'] == 'HKLM' and op['path'].startswith(CLASS + '\\')}
    if any(op['root'] == 'HKLM' and op['path'] == GL for op in plan):
        drivers.update(CLASS + '\\' + key for key in db.children('HKLM', CLASS) if re.fullmatch(r'\d{4}', key))
    drivers = sorted(drivers)
    return dict(user=user_identity(), machine=value(db, 'HKLM', r'SOFTWARE\Microsoft\Cryptography', 'MachineGuid'),
                drivers={p: [value(db, 'HKLM', p, n) for n in ('DriverDesc', 'DriverVersion', 'DriverDate', 'MatchingDeviceId')]
                         for p in drivers})


class Registry:
    def read(self, root, path, name, view=64):
        try:
            with reg.OpenKey(ROOTS[root], path, 0, reg.KEY_READ | self.flag(view)) as key:
                return reg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None

    @staticmethod
    def flag(view):
        return reg.KEY_WOW64_64KEY if view == 64 else reg.KEY_WOW64_32KEY

    def children(self, root, path):
        try:
            with reg.OpenKey(ROOTS[root], path, 0, reg.KEY_READ | self.flag(64)) as key:
                return [reg.EnumKey(key, i) for i in range(reg.QueryInfoKey(key)[0])]
        except FileNotFoundError:
            return []

    def values(self, root, path, view=64):
        try:
            with reg.OpenKey(ROOTS[root], path, 0, reg.KEY_READ | self.flag(view)) as key:
                return [reg.EnumValue(key, i) for i in range(reg.QueryInfoKey(key)[1])]
        except FileNotFoundError:
            return []

    def write(self, root, path, name, view, value):
        if value is None:
            try:
                with reg.OpenKey(ROOTS[root], path, 0, reg.KEY_SET_VALUE | self.flag(view)) as key:
                    reg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        else:
            with reg.CreateKeyEx(ROOTS[root], path, 0, reg.KEY_SET_VALUE | self.flag(view)) as key:
                reg.SetValueEx(key, name, 0, value[1], value[0])


def value(db, root, path, name, view=64):
    item = db.read(root, path, name, view)
    return item[0] if item else None


def driver_string(raw):
    return next((s for s in raw if s), '') if isinstance(raw, list) else (raw or '')


def adapters(db, present=None):
    if present is None:
        from device_presence import present_pci_ids
        present = present_pci_ids()
    pci_map = {}
    present_keys = set()
    for device in db.children('HKLM', PCI):
        match = re.search(r'VEN_([0-9A-F]{4})&DEV_([0-9A-F]{4})&SUBSYS_([0-9A-F]{8})', device, re.I)
        if not match:
            continue
        for instance in db.children('HKLM', PCI + '\\' + device):
            driver = value(db, 'HKLM', PCI + '\\' + device + '\\' + instance, 'Driver')
            if driver:
                key = str(driver).lower()
                is_present = ('PCI\\' + device + '\\' + instance).upper() in present
                if is_present:
                    present_keys.add(key)
                if key not in pci_map or is_present:
                    pci_map[key] = '&'.join(match.groups()).upper()
    result = []
    for number in db.children('HKLM', CLASS):
        if not re.fullmatch(r'\d{4}', number):
            continue
        path = CLASS + '\\' + number
        desc = value(db, 'HKLM', path, 'DriverDesc')
        if not desc:
            continue
        result.append(dict(key=number, name=desc,
                           present=(CLASS.split('\\')[-1] + '\\' + number).lower() in present_keys,
                           did=pci_map.get((CLASS.split('\\')[-1] + '\\' + number).lower()),
                           gl=driver_string(value(db, 'HKLM', path, 'OpenGLDriverName') or value(db, 'HKLM', path, '_OpenGLDriverName')),
                           gl32=driver_string(value(db, 'HKLM', path, 'OpenGLDriverNameWow') or value(db, 'HKLM', path, '_OpenGLDriverNameWow'))))
    return result


def operation(root, path, name, data, kind=reg.REG_SZ, view=64):
    return dict(root=root, path=path, name=name, view=view, value=None if data is None else [data, kind])


def settings_plan():
    return [operation('HKCU', DX + r'\GraphicsSettings', name, 1, reg.REG_DWORD)
            for name in ('DefaultHighPerfGPUApplicable', 'SpecificGPUOptionApplicable')]


def dx_string(current, did):
    # Preserve unrelated preferences; change only the original tool's target field.
    fields = [s for s in (current or '').split(';') if s and s.partition('=')[0].strip().lower() != 'highperfadapter']
    if not any(s.partition('=')[0].strip().lower() == 'swapeffectupgradeenable' for s in fields):
        fields.append('SwapEffectUpgradeEnable=0')
    return 'HighPerfAdapter=' + did + ';' + ';'.join(fields) + ';'


def dx_target(db):
    current = value(db, 'HKCU', PREF, GLOBAL)
    current = '' if current is None else current
    if not isinstance(current, str):
        raise ValueError('DirectX 全局设置的注册表类型异常，停止操作。')
    return next((s.partition('=')[2].strip().upper() for s in current.split(';')
                 if s.partition('=')[0].strip().lower() == 'highperfadapter'), '')


def dx_matches(db, gpu):
    return bool(gpu['did']) and dx_target(db) == gpu['did'].upper()


def dx_reset_plan(db):
    current = value(db, 'HKCU', PREF, GLOBAL)
    if current is not None and not isinstance(current, str):
        raise ValueError('DirectX 全局设置的注册表类型异常，停止操作。')
    fields = [s for s in (current or '').split(';')
              if s and s.partition('=')[0].strip().lower() != 'highperfadapter']
    return [operation('HKCU', PREF, GLOBAL, ';'.join(fields) + ';' if fields else None)]


def dx_plan(db, gpu):
    if not gpu.get('present', True):
        raise ValueError('此显卡当前未连接，不能设为 DirectX 目标。')
    if not gpu['did']:
        raise ValueError('此设备没有可用的 PCI 硬件 ID，不能设置 DirectX。')
    dx_target(db)  # Validate type before changing the global string.
    return [operation('HKCU', PREF, GLOBAL, dx_string(value(db, 'HKCU', PREF, GLOBAL), gpu['did']))]


def gl_preflight(gpu):
    """Reject stale/missing driver files before changing system-wide ICD entries."""
    for field, bits in [('gl', 64), ('gl32', 32)]:
        raw = gpu[field]
        if not raw:
            raise ValueError(f'此设备缺少 {bits} 位 OpenGL ICD。')
        path = Path(os.path.expandvars(raw))
        if not path.is_absolute():
            path = Path(os.environ['WINDIR']) / ('System32' if bits == 64 else 'SysWOW64') / path
        if not path.is_file():
            raise ValueError(f'{bits} 位 OpenGL 驱动文件不存在：{path}\n请先修复或更新驱动。')
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError(f'不是有效的 Windows 驱动 DLL：{path}')
            stream.seek(0x3c)
            offset = int.from_bytes(stream.read(4), 'little')
            stream.seek(offset)
            if stream.read(4) != b'PE\0\0' or int.from_bytes(stream.read(2), 'little') != (0x8664 if bits == 64 else 0x14c):
                raise ValueError(f'{bits} 位驱动 DLL 架构不匹配：{path}')


def gl_plan(gpus, gpu):
    if not gpu.get('present', True):
        raise ValueError('此显卡当前未连接，不能设为 OpenGL 目标。')
    if not gpu['gl'] or not gpu['gl32']:
        raise ValueError('此设备缺少 64 位或 32 位 OpenGL ICD，无法完整执行原程序的切换。')
    plan = []
    for view, dll in ((64, gpu['gl']), (32, gpu['gl32'])):
        for name, data, kind in [('DLL', dll, reg.REG_SZ), ('DriverVersion', 1, reg.REG_DWORD),
                                 ('Version', 2, reg.REG_DWORD), ('Flags', 3, reg.REG_DWORD)]:
            plan.append(operation('HKLM', GL, name, data, kind, view))
    for item in gpus:
        if not item.get('present', True) or not (item['gl'] or item['gl32']):
            continue
        path = CLASS + '\\' + item['key']
        for original, saved, dll in [('OpenGLDriverName', '_OpenGLDriverName', item['gl']),
                                      ('OpenGLDriverNameWow', '_OpenGLDriverNameWow', item['gl32'])]:
            if dll:
                plan.append(operation('HKLM', path, saved, dll))
            plan.append(operation('HKLM', path, original, None))
    return plan


def check_plan(db, plan):
    errors = []
    for op in plan:
        actual = db.read(op['root'], op['path'], op['name'], op['view'])
        expected = op['value']
        if (list(actual) if actual is not None else None) != expected:
            errors.append(f"{op['root']}\\{op['path']} [{op['view']}] {op['name']}\n  期望：{expected!r}\n  实际：{actual!r}")
    return errors


def apply_plan(db, plan, backup_dir, label):
    before = []
    for op in plan:
        old = db.read(op['root'], op['path'], op['name'], op['view'])
        before.append(dict(op, value=list(old) if old is not None else None))
    folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    safe_label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(label))[:80]
    backup = folder / (stamp + '-' + safe_label + '.json')
    backup.write_text(json.dumps(dict(schema=2, label=label, identity=backup_identity(db, plan), before=before, after=plan), ensure_ascii=False, indent=2), encoding='utf-8')
    applied = []
    try:
        for old, op in zip(before, plan):
            applied.append(old)
            db.write(**op)
        errors = check_plan(db, plan)
        if errors:
            raise OSError('写入后的读回校验失败：' + '\n'.join(errors))
    except Exception as exc:
        rollback_errors = []
        for old in reversed(applied):
            try:
                db.write(**old)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        try:
            rollback_errors.extend(check_plan(db, applied))
        except OSError as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        raise OSError(f'{exc}\n备份：{backup}\n' + ('回滚失败：' + '; '.join(rollback_errors) if rollback_errors else '已回滚本次修改的注册表值。')) from exc
    return backup


def is_app_value(name):
    return (isinstance(name, str) and ntpath.isabs(name) and bool(ntpath.splitdrive(name)[0])
            and name.lower().endswith('.exe') and not any(c in name for c in '\x00\n\r')
            and ':' not in ntpath.splitdrive(name)[1])


def validate_operations(plan):
    if not isinstance(plan, list) or not plan or len(plan) > 512:
        raise ValueError('操作列表无效或超过 512 项。')
    seen = set()
    for op in plan:
        if not isinstance(op, dict) or set(op) != {'root', 'path', 'name', 'view', 'value'}:
            raise ValueError('操作字段无效。')
        root, path, name, view = (op[k] for k in ('root', 'path', 'name', 'view'))
        if not all(isinstance(x, str) for x in (root, path, name)) or type(view) is not int:
            raise ValueError('注册表位置格式无效。')
        valid = ((root == 'HKCU' and view == 64 and
                  ((path == PREF and (name == GLOBAL or is_app_value(name))) or
                   (path == DX + r'\GraphicsSettings' and name in ('DefaultHighPerfGPUApplicable', 'SpecificGPUOptionApplicable'))))
                 or (root == 'HKLM' and view in (32, 64) and path == GL and name in ('DLL', 'DriverVersion', 'Version', 'Flags'))
                 or (root == 'HKLM' and view == 64 and re.fullmatch(re.escape(CLASS) + r'\\\d{4}', path) and
                     name in ('OpenGLDriverName', '_OpenGLDriverName', 'OpenGLDriverNameWow', '_OpenGLDriverNameWow')))
        if not valid:
            raise ValueError('包含本工具范围以外的注册表项，拒绝操作。')
        key = (root, path, name.lower(), view)
        if key in seen:
            raise ValueError('操作列表包含重复项目。')
        seen.add(key)
        data = op['value']
        if data is not None:
            if not isinstance(data, list) or len(data) != 2:
                raise ValueError('注册表值格式无效。')
            raw, kind = data
            if not ((kind in (reg.REG_SZ, reg.REG_EXPAND_SZ) and isinstance(raw, str)) or
                    (kind == reg.REG_DWORD and type(raw) is int and 0 <= raw <= 0xffffffff) or
                    (kind == reg.REG_MULTI_SZ and isinstance(raw, list) and all(isinstance(x, str) for x in raw))):
                raise ValueError('不支持的注册表值类型。')


def restore_plan(db, backup):
    if Path(backup).stat().st_size > 1024 * 1024:
        raise ValueError('备份文件过大。')
    saved = json.loads(Path(backup).read_text(encoding='utf-8'))
    if saved.get('schema') != 2:
        raise ValueError('此备份缺少新版身份和驱动信息，不能自动恢复；原文件可供人工检查。')
    before, after = saved.get('before'), saved.get('after')
    if not isinstance(before, list) or not isinstance(after, list) or not before or len(before) != len(after) or len(before) > 512:
        raise ValueError('备份操作列表无效。')
    validate_operations(before)
    validate_operations(after)
    for old, new in zip(before, after):
        if tuple(old[k] for k in ('root', 'path', 'name', 'view')) != tuple(new[k] for k in ('root', 'path', 'name', 'view')):
            raise ValueError('备份前后项目不匹配。')
    if saved.get('identity') != backup_identity(db, before):
        raise ValueError('备份不属于当前用户/电脑，或相关显卡驱动已更新，不能自动恢复。')
    if check_plan(db, after):
        raise ValueError('设置在备份后已发生变化，拒绝覆盖后续修改。请从最新且匹配的备份开始恢复。')
    return before


def compatibility_packages(db):
    path = r'Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'
    found = []
    for root, location in [('HKCU', 'Software\\Classes\\' + path),
                           ('HKLM', 'SOFTWARE\\Classes\\' + path),
                           ('HKLM', r'SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications')]:
        try:
            found.extend(n for n in db.children(root, location) if n.lower().startswith('microsoft.d3dmappinglayers_'))
        except PermissionError:
            found.append('部分系统兼容包信息无权读取，检测不完整')
    return sorted(set(found))


def report(db, gpus):
    raw = value(db, 'HKCU', PREF, GLOBAL) or ''
    did = dx_target(db)
    names = [g['name'] for g in gpus if did and g['did'] == did.upper()]
    lines = ['检查时间：' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             '', '【DirectX 默认高性能偏好】',
             '当前目标：' + (' / '.join(names) if names else (did + '（未匹配到当前设备）' if did else '未设置，交由 Windows / 应用选择')),
             '原始值：' + (raw or '不存在'), '', '【Windows 图形设置选项】']
    for op in settings_plan():
        lines.append(op['name'] + '：' + str(value(db, op['root'], op['path'], op['name'])))
    lines += ['', '【OpenGL ICD 回退配置】']
    for view in (64, 32):
        dll = value(db, 'HKLM', GL, 'DLL', view)
        lines.append(f'{view} 位 DLL：{dll or "未设置 MSOGL 回退项"}')
        for name in ('DriverVersion', 'Version', 'Flags'):
            lines.append(f'  {name}：{value(db, "HKLM", GL, name, view)}')
    for gpu in gpus:
        if not gpu.get('present', True) or not gpu['gl'] or not gpu['gl32']:
            continue
        if not check_plan(db, gl_plan(gpus, gpu)):
            lines.append('完整配置匹配：' + gpu['name'] + '（相同 ICD 路径可能由多张显卡共用）')
    active = [g['name'] for g in gpus if value(db, 'HKLM', CLASS + '\\' + g['key'], 'OpenGLDriverName')]
    lines.append('仍保留常规 64 位 ICD 的设备：' + (' / '.join(active) or '无'))
    lines += ['', '【设备与驱动可用性】']
    for gpu in gpus:
        lines.append(gpu['name'] + '：' + ('当前连接' if gpu.get('present', True) else '未检测到当前 PCI 实例，已从可选目标排除'))
        if gpu.get('present', True) and (gpu['gl'] or gpu['gl32']):
            try:
                gl_preflight(gpu)
                lines.append('  64 / 32 位 ICD 文件存在且架构正确')
            except ValueError as exc:
                lines.append('  ICD 诊断：' + str(exc))
    packs = compatibility_packages(db)
    lines += ['', '【兼容包检查】', '\n'.join(packs) if packs else '未在已检查的注册表位置发现 GLOn12 兼容包（不等于运行时保证）。',
              '', '【结果含义】', '注册表匹配只能证明配置已写入，不能证明所有应用都已采用。',
              'OpenGL 首次切换需重启；Intel 核显 ICD 是原项目已知限制。',
              '实际 GPU：打开任务管理器 → 详细信息 → 选择列 → GPU 引擎；运行目标程序，',
              '再到“性能”页将 GPU 编号对应到显卡名称。应用自身显卡选择可能优先。']
    return '\n'.join(lines)


def export_bat(mode, gpu, gpus):
    from bat_export import build_bat
    if not gpu.get('present', True):
        raise ValueError('此显卡当前未连接，不能导出为目标。')
    if mode == 'DX':
        return build_bat(mode, did=gpu['did'])
    if mode == 'GL':
        return build_bat(mode, plan=gl_plan(gpus, gpu))
    raise ValueError('未知导出类型。')
