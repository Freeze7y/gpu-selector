"""Named GPU configuration schemes with hardware and driver matching."""
import datetime
import json
from pathlib import Path
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from app_preferences import PREFERENCES, app_plan, list_app_preferences, normalize_exe
from gpu_core import (CLASS, backup_identity, dx_plan, dx_reset_plan, gl_plan,
                      gl_preflight, value)


def fingerprint(db, gpus):
    # A driver-class slot alone can be reused; bind it to IDs plus driver metadata.
    hardware = []
    for gpu in gpus:
        if not gpu.get('present', True):
            continue
        hardware.append({key: gpu.get(key) for key in ('key', 'did', 'name', 'gl', 'gl32')})
        hardware[-1]['driver'] = [value(db, 'HKLM', CLASS + '\\' + gpu['key'], name)
                                for name in ('DriverVersion', 'DriverDate', 'MatchingDeviceId')]
    return dict(identity=backup_identity(db, []), hardware=sorted(hardware, key=lambda item: item['key']))


def profile_snapshot(db, gpus, name, dx_key=None, gl_key=None, include_apps=True):
    name = name.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError('请输入 1–80 个字符的方案名称。')
    keys = {gpu['key'] for gpu in gpus if gpu.get('present', True)}
    if dx_key not in (None, 'auto') and dx_key not in keys:
        raise ValueError('DirectX 目标设备已变化，请重新选择。')
    if gl_key is not None and gl_key not in keys:
        raise ValueError('OpenGL 目标设备已变化，请重新选择。')
    apps = []
    if include_apps:
        for item in list_app_preferences(db):
            if item['preference'] is None:
                raise ValueError('应用有未知或 Windows 自定义 GPU 指定，不能转换为方案：\n' + item['path'] +
                                 '\n请取消“包含应用偏好”，或先在应用页改为自动、节能或高性能。')
            apps.append(dict(path=item['path'], preference=item['preference']))
    if dx_key is None and gl_key is None and not apps:
        raise ValueError('方案没有任何设置。请选择 DirectX / OpenGL 目标，或包含已有应用偏好。')
    if len(apps) > 450:
        raise ValueError('应用偏好超过 450 项，请取消包含应用偏好。')
    return dict(schema=1, name=name, created=datetime.datetime.now().isoformat(timespec='seconds'),
                fingerprint=fingerprint(db, gpus), dx=dx_key, gl=gl_key, apps=apps)


def read_profile(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('方案文件过大。')
    profile = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(profile, dict) or profile.get('schema') != 1:
        raise ValueError('不支持的方案格式。')
    if not isinstance(profile.get('name'), str) or not profile['name'].strip():
        raise ValueError('方案名称无效。')
    if not isinstance(profile.get('created'), str):
        raise ValueError('方案时间无效。')
    if not isinstance(profile.get('apps'), list) or len(profile['apps']) > 450:
        raise ValueError('方案应用列表无效或超过 450 项。')
    return profile


def profile_plan(db, gpus, profile):
    if not isinstance(profile, dict) or profile.get('schema') != 1:
        raise ValueError('不支持的方案格式。')
    if profile.get('fingerprint') != fingerprint(db, gpus):
        raise ValueError('当前用户、电脑、显卡或驱动与方案不匹配。请重新检查并保存新方案。')
    dx_key, gl_key = profile.get('dx'), profile.get('gl')
    if (dx_key is not None and not isinstance(dx_key, str)) or (gl_key is not None and not isinstance(gl_key, str)):
        raise ValueError('方案的显卡目标格式无效。')
    by_key = {gpu['key']: gpu for gpu in gpus if gpu.get('present', True)}
    plan = []
    if dx_key == 'auto':
        plan += dx_reset_plan(db)
    elif dx_key is not None:
        if dx_key not in by_key:
            raise ValueError('方案的 DirectX 显卡不在当前设备列表中。')
        plan += dx_plan(db, by_key[dx_key])
    if gl_key is not None:
        if gl_key not in by_key:
            raise ValueError('方案的 OpenGL 显卡不在当前设备列表中。')
        gl_preflight(by_key[gl_key])
        plan += gl_plan(gpus, by_key[gl_key])
    apps = profile.get('apps')
    if not isinstance(apps, list) or len(apps) > 450:
        raise ValueError('方案应用列表无效或超过 450 项。')
    seen = set()
    for item in apps:
        if not isinstance(item, dict) or set(item) != {'path', 'preference'}:
            raise ValueError('方案应用字段无效。')
        path = normalize_exe(item['path'])
        if path.casefold() in seen:
            raise ValueError('方案包含重复应用路径。')
        seen.add(path.casefold())
        plan += app_plan(db, path, item['preference'], require_exists=item['preference'] != 0)
    if not plan:
        raise ValueError('方案没有任何设置。')
    if len(plan) > 512:
        raise ValueError('方案修改项目超过备份支持的 512 项，请减少方案内容。')
    return plan


def save_profile(folder, profile):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (uuid.uuid4().hex + '.json')
    # Exclusive creation: duplicate friendly names never overwrite earlier schemes.
    with target.open('x', encoding='utf-8') as stream:
        json.dump(profile, stream, ensure_ascii=False, indent=2)
    return target


class ProfilesPage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.folder = Path(owner.data_dir) / 'profiles'
        self.paths = []
        layout = QVBoxLayout(self)
        heading = QLabel('保存“游戏”“办公”等方案；应用前核对显卡和驱动，并统一预览、备份和校验。')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('方案名称，例如：游戏 / 办公')
        self.name_edit.setMaxLength(80)
        layout.addWidget(self.name_edit)
        self.dx_combo = QComboBox()
        self.gl_combo = QComboBox()
        layout.addWidget(QLabel('方案中的 DirectX 设置'))
        layout.addWidget(self.dx_combo)
        layout.addWidget(QLabel('方案中的 OpenGL 设置'))
        layout.addWidget(self.gl_combo)
        self.include_apps = QCheckBox('包含当前应用偏好（保留应用的 HDR 等其他参数）')
        self.include_apps.setChecked(True)
        layout.addWidget(self.include_apps)
        save = QPushButton('保存新方案')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.list = QListWidget()
        self.list.setMinimumHeight(90)
        self.list.currentRowChanged.connect(self.show_selected)
        layout.addWidget(self.list, 1)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(80)
        layout.addWidget(self.details, 1)
        row = QGridLayout()
        apply = QPushButton('预览并应用方案')
        apply.setObjectName('primary')
        apply.clicked.connect(self.apply)
        row.addWidget(apply, 0, 0)
        delete = QPushButton('删除所选方案')
        delete.clicked.connect(self.delete)
        row.addWidget(delete, 0, 1)
        refresh = QPushButton('刷新方案')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh, 1, 0, 1, 2)
        layout.addLayout(row)
        note = QLabel('方案只应用其中列出的项目，其他应用保持原配置。更换显卡、更新驱动或应用路径失效后，会要求重新保存方案。')
        note.setWordWrap(True)
        layout.addWidget(note)

    def refresh(self):
        for combo, mode in ((self.dx_combo, 'dx'), (self.gl_combo, 'gl')):
            selected = combo.currentData()
            items = [('不更改', None)]
            if mode == 'dx':
                items.append(('系统自动选择', 'auto'))
            items += [(gpu['name'] + ' · ' + gpu['key'], gpu['key']) for gpu in self.owner.gpus
                      if gpu.get('present', True) and (gpu.get('did') if mode == 'dx' else gpu.get('gl') and gpu.get('gl32'))]
            if items != [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]:
                combo.clear()
                for title, key in items:
                    combo.addItem(title, key)
                index = combo.findData(selected)
                combo.setCurrentIndex(max(index, 0))
        try:
            selected_path = self.paths[self.list.currentRow()] if 0 <= self.list.currentRow() < len(self.paths) else None
            paths = sorted(self.folder.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True) if self.folder.exists() else []
            self.list.blockSignals(True)
            self.list.clear()
            self.paths = paths
            for path in paths:
                try:
                    profile = read_profile(path)
                    title = profile['name'] + ' · ' + profile['created']
                except Exception:
                    title = '无法读取 · ' + path.name
                item = QListWidgetItem(title)
                item.setToolTip(str(path))
                self.list.addItem(item)
            if paths:
                self.list.setCurrentRow(paths.index(selected_path) if selected_path in paths else 0)
            self.show_selected()
            return True
        except Exception as exc:
            self.details.setPlainText('方案列表读取失败：' + str(exc))
            return False
        finally:
            self.list.blockSignals(False)

    def selected_path(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.paths):
            raise ValueError('请先选择一个方案。')
        return self.paths[row]

    def show_selected(self, *_):
        if not self.paths or self.list.currentRow() < 0:
            self.details.setPlainText('暂无方案。先选择要保存的设置，再保存新方案。')
            return
        try:
            profile = read_profile(self.selected_path())
            names = {item['key']: item['name'] for item in profile['fingerprint']['hardware']}
            matched = profile['fingerprint'] == fingerprint(self.owner.db, self.owner.gpus)
            lines = [profile['name'], '设备与驱动：' + ('匹配' if matched else '不匹配，不能应用'),
                     'DirectX：' + ('不更改' if profile['dx'] is None else '系统自动' if profile['dx'] == 'auto' else names.get(profile['dx'], profile['dx'])),
                     'OpenGL：' + ('不更改' if profile['gl'] is None else names.get(profile['gl'], profile['gl'])),
                     '应用偏好：' + str(len(profile['apps'])) + ' 项']
            lines += [item['path'] + ' → ' + PREFERENCES.get(item['preference'], '未知') for item in profile['apps']]
            self.details.setPlainText('\n'.join(lines))
        except Exception as exc:
            self.details.setPlainText('方案不可用：' + str(exc))

    def save(self):
        try:
            dx, gl = self.dx_combo.currentData(), self.gl_combo.currentData()
            selected_hardware = {gpu['key']: (gpu.get('did'), gpu.get('name'), gpu.get('gl'), gpu.get('gl32'))
                                 for gpu in self.owner.gpus if gpu['key'] in (dx, gl)}
            if not self.owner.refresh():
                raise ValueError('无法读取最新设备状态，已停止保存。')
            current_hardware = {gpu['key']: (gpu.get('did'), gpu.get('name'), gpu.get('gl'), gpu.get('gl32'))
                                for gpu in self.owner.gpus if gpu['key'] in (dx, gl)}
            if selected_hardware != current_hardware:
                raise ValueError('所选显卡已变化，请重新选择方案目标。')
            profile = profile_snapshot(self.owner.db, self.owner.gpus, self.name_edit.text(), dx, gl,
                                       self.include_apps.isChecked())
            target = save_profile(self.folder, profile)
            self.refresh()
            self.list.setCurrentRow(self.paths.index(target))
        except Exception as exc:
            QMessageBox.critical(self, '方案未保存', str(exc))

    def apply(self):
        try:
            profile = read_profile(self.selected_path())
            if not self.owner.refresh():
                raise ValueError('无法读取最新设备状态，已停止操作。')
            plan = profile_plan(self.owner.db, self.owner.gpus, profile)
            if self.owner.execute(plan, '配置方案'):
                self.refresh()
                self.details.append('\n方案已应用并完成读回校验。应用偏好需重启目标程序，OpenGL 可能需要重启电脑。')
        except Exception as exc:
            QMessageBox.critical(self, '方案未应用', str(exc))

    def delete(self):
        try:
            path = self.selected_path()
            # Only files from this app-owned list may be removed.
            if path.resolve().parent != self.folder.resolve():
                raise ValueError('方案路径不在方案目录中。')
            if QMessageBox.question(self, '删除方案', '删除此方案文件？这不会修改当前显卡设置。') != QMessageBox.Yes:
                return
            path.unlink()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, '方案未删除', str(exc))
