"""Adaptive Qt GUI for the original select_default_GPU functionality."""
import ctypes
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import Qt, QTimer, QProcess, QByteArray
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QSpinBox, QDialog, QGridLayout, QSizePolicy)
from gpu_core import (Registry, adapters, apply_plan, check_plan, dx_plan, dx_target,
                      dx_matches, dx_reset_plan, export_bat, gl_plan, gl_preflight,
                      report, restore_plan, settings_plan, validate_operations)
from change_preview import PreviewDialog, capture_before
from ui_preferences import load_preferences, save_preferences, style_for
from app_version import VERSION
from update_ui import UpdatePanel

HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
DATA_DIR = Path(os.environ.get('GPU_SELECTOR_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'GPUSelector')))
BACKUPS = DATA_DIR / 'backups'

STYLE = '''
QWidget { background: #101522; color: #e8edf8; font-family: "Microsoft YaHei UI"; font-size: 10pt; }
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #101522; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #79dac8; font-size: 9pt; font-weight: 700; }
QLabel#heading { font-size: 26pt; font-weight: 700; }
QLabel#subtitle { color: #99a8c4; }
QLabel#section { font-size: 14pt; font-weight: 600; }
QFrame#card { background: #1a2233; border: 1px solid #2b3850; border-radius: 14px; }
QPushButton { background: #293750; border: 1px solid #3a4b67; border-radius: 7px; padding: 10px 17px; font-weight: 600; }
QPushButton:hover { background: #364967; border-color: #86a8e5; }
QPushButton:pressed { background: #18243a; }
QPushButton#primary { background: #72dbc4; color: #092c2b; border-color: #72dbc4; }
QPushButton#primary:hover { background: #9ae9d9; }
QPushButton:disabled { color: #63728b; background: #1f293a; border-color: #2b3850; }
QComboBox { background: #111a2b; border: 1px solid #485974; border-radius: 7px; padding: 10px; min-height: 24px; }
QComboBox::drop-down { border: 0; width: 27px; }
QComboBox QAbstractItemView { background: #1a263b; selection-background-color: #345170; }
QTextEdit { background: #111a29; border: 1px solid #2b3850; border-radius: 9px; padding: 12px; selection-background-color: #385776; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 12px 22px; margin-right: 6px; color: #9aabc7; background: #182033; border-radius: 7px; }
QTabBar::tab:selected { background: #2a3a50; color: #8de4d0; }
QScrollBar:vertical { width: 10px; background: #151d2e; }
QScrollBar::handle:vertical { background: #445571; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''


def admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def label(text, object_name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    if object_name:
        widget.setObjectName(object_name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(lambda _checked=False: callback())
    widget.setCursor(Qt.PointingHandCursor)
    if primary:
        widget.setObjectName('primary')
    return widget


def scroll_page(page):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(page)
    return scroll


class Window(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        self.data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self.backup_dir = self.data_dir / 'backups'
        self.preferences = load_preferences(self.data_dir)
        self.db = Registry()
        self.gpus = []
        self.last_plan = None
        self.verification_text = ''
        self.probe_text = ''
        self.report_text = ''
        self.read_ok = False
        self.first_load = True
        self.last_device_scan = 0
        self.action_buttons = []
        self.probe_process = None
        self.probe_kind = 'gl64'
        self.probe_results = {}
        self.busy = False
        self.setWindowTitle(f'GPU 控制台 {VERSION} · 默认显卡选择器')
        self.setWindowIcon(QIcon(str(HERE / 'gpu.ico')))
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1100, int(area.width() * .85)), min(900, int(area.height() * .87)))
        self.setMinimumSize(min(600, area.width()), min(430, area.height()))
        base = QWidget()
        outer = QVBoxLayout(base)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(12)
        self.eyebrow = label('GPU SELECTOR  /  WINDOWS', 'eyebrow')
        author_row = QHBoxLayout()
        author_row.addWidget(self.eyebrow, 1)
        self.author_link = QLabel()
        self.author_link.setTextFormat(Qt.RichText)
        self.author_link.setOpenExternalLinks(True)
        self.author_link.setWordWrap(True)
        self.author_link.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.author_link.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        author_row.addWidget(self.author_link, 1)
        outer.addLayout(author_row)
        self.heading = label('让每一次渲染，各就其位。', 'heading')
        outer.addWidget(self.heading)
        self.subtitle = label('默认显卡选择器   ·   DirectX / OpenGL   ·   实时读取系统配置', 'subtitle')
        outer.addWidget(self.subtitle)
        bar = QHBoxLayout()
        self.summary = label('正在读取显卡…', 'subtitle')
        bar.addWidget(self.summary, 1)
        bar.addWidget(button('刷新状态', self.refresh))
        outer.addLayout(bar)
        self.reboot_notice = label('', 'subtitle')
        outer.addWidget(self.reboot_notice)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        control = QWidget()
        controls = QVBoxLayout(control)
        controls.setContentsMargins(0, 14, 0, 0)
        controls.setSpacing(14)
        self.dx_combo = QComboBox()
        self.gl_combo = QComboBox()
        self.dx_combo.setMinimumContentsLength(18)
        self.gl_combo.setMinimumContentsLength(18)
        for combo in (self.dx_combo, self.gl_combo):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        controls.addWidget(self.card('01  Windows 图形设置',
            '启用默认高性能 GPU 和按应用指定 GPU 的选项，并打开系统图形设置。',
            None, [('打开系统图形设置', self.open_settings, True)]))
        controls.addWidget(self.card('02  DirectX 默认高性能显卡',
            '选择全局高性能偏好。通过界面设置时会保留已有的其他 DirectX 全局参数。',
            self.dx_combo, [('应用 DirectX 设置', self.apply_dx, True), ('导出 BAT', lambda: self.export('DX'), False), ('恢复自动选择', self.reset_dx, False)]))
        controls.addWidget(self.card('03  OpenGL 驱动选择',
            '沿用原程序的 ICD 回退方法，同时设置 64 / 32 位驱动。需要管理员权限；首次切换需要重启。Intel 核显不受原方法支持，GLOn12 兼容包可能使其失效。相同 AMD ICD 不能区分具体物理显卡。',
            self.gl_combo, [('应用 OpenGL 设置', self.apply_gl, True), ('导出 BAT', lambda: self.export('GL'), False)]))
        controls.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(control)
        self.tabs.addTab(scroll, '显卡设置')
        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(0, 14, 0, 0)
        status_layout.addWidget(label('配置状态 ≠ 应用实际使用的 GPU。下方提供读回结果与实际使用检查方法。', 'subtitle'))
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(180)
        status_layout.addWidget(self.status, 1)
        actions = QGridLayout()
        actions.addWidget(button('检查所选配置', self.verify, True), 0, 0)
        actions.addWidget(button('导出检查报告', self.save_report), 0, 1)
        actions.addWidget(button('任务管理器', self.task_manager), 2, 1)
        self.probe_button = button('OpenGL 64 位', lambda: self.start_probe('gl64'))
        self.probe32_button = button('OpenGL 32 位', lambda: self.start_probe('gl32'))
        self.dx_probe_button = button('DirectX 渲染测试', lambda: self.start_probe('dx'))
        self.probe_buttons = (self.probe_button, self.probe32_button, self.dx_probe_button)
        for index, item in enumerate(self.probe_buttons):
            actions.addWidget(item, 1 + index // 2, index % 2)
        status_layout.addLayout(actions)
        self.tabs.addTab(scroll_page(status_page), '状态与验证')
        help_page = QWidget()
        help_layout = QVBoxLayout(help_page)
        appearance = QHBoxLayout()
        appearance.addWidget(label('外观'))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem('深色', 'dark')
        self.theme_combo.addItem('浅色', 'light')
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.preferences['theme']))
        appearance.addWidget(self.theme_combo)
        appearance.addWidget(label('字体大小'))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(9, 14)
        self.font_spin.setValue(self.preferences['font_size'])
        appearance.addWidget(self.font_spin)
        appearance.addStretch()
        help_layout.addLayout(appearance)
        self.update_panel = UpdatePanel(self)
        help_layout.addWidget(self.update_panel)
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setMinimumHeight(180)
        help_text.setPlainText(f"""使用说明 · {VERSION}

本项目基于 nethe-GitHub/select_default_GPU 改编。
原项目：https://github.com/nethe-GitHub/select_default_GPU
Python 图形界面与功能扩展，修改日期：2026-09-06。
依据 AGPL-3.0 发布；保留原项目归属与许可证。

全局设置

保留 Windows 图形设置、DirectX 默认高性能 GPU 和 OpenGL ICD 回退切换功能。点击应用后先预览，显示当前值、目标值和操作类型。预览期间设置被外部改变，会停止写入。

应用设置

为桌面 EXE 选择 Windows 自动、节能或高性能偏好，并保留其他图形参数。具体物理 GPU 由 Windows 和应用决定；配置后需要退出并重新启动目标程序。未知的 Windows 自定义 GPU 指定不会被误判为自动。
在列表中选择路径后，可点击“清除所选路径”预览并删除整条图形设置，包括 Auto HDR 和窗口化优化；不删除应用文件。操作前备份、操作后读回验证，可在“备份与日志”恢复。

配置方案

保存全局 DirectX / OpenGL 目标与可选的应用偏好。应用前检查用户、电脑、显卡及驱动是否匹配；所有项目作为一次事务预览、备份和校验。未列入方案的应用保持原有设置。

状态与验证

注册表检查、OpenGL 64 位和 32 位探针、Direct3D 11 默认设备与离屏清色回读测试分别显示结果。探针运行在独立进程，20 秒超时；结果只代表测试进程，不能证明其他程序采用同一 GPU。

检查其他应用：任务管理器 → 详细信息 → 选择列 → GPU 引擎，运行渲染后到性能页核对 GPU 编号。

备份、日志与健康

备份列表显示时间、操作、目标及能否恢复。恢复前核对用户、电脑、相关驱动与当前值；损坏文件单独显示错误。操作日志可以导出。设备健康页显示驱动版本、是否禁用和问题代码；“无问题代码”不等于完整硬件检测通过。
不再需要的备份可选中后“清除所选备份”，确认后移到 Windows 回收站。暂时不可恢复不代表没有用；清除不会改变当前 GPU 设置。

OpenGL 修改或恢复后记录重启状态。睡眠、快速启动和系统时间调整会影响判断，无法确认时显示未知，不会自动重启。

外观

可切换深浅主题、调整字体大小。正常关闭时记住窗口大小和位置；旧显示器移除后自动放回可见区域。

软件更新

点击“检查更新”读取本 GitHub 仓库的新版本。首次启动可选择是否开启启动检查，发现新版先确认再下载；正式版只提示更高正式版本。下载大小及 SHA-256 校验通过后，程序退出、覆盖并重新启动，保留原设置、备份和日志。源码运行只提供下载指引，不覆盖 Python 源码。

软件更新

首次启动会询问是否启用启动检查，并记住选择。启用后每次启动连接 GitHub 检查版本；发现新版仍需确认，之后才下载、校验并准备替换和重启。也可以手动检查或关闭启动检查。源码运行仅提示到发布页下载 EXE，不会覆盖源码。

注意

原 OpenGL 方法首次采用需要重启；Intel 核显 ICD、GLOn12 兼容包和共享 ICD 的限制仍然存在。独立 BAT 有读回校验，但不包含界面的自动备份/回滚。历史恢复支持 1.1 及之后创建的备份，旧文件仍保留供人工检查。

改编自 nethe-GitHub/select_default_GPU，AGPL-3.0。
本程序按现状提供，不提供担保；允许按许可证复制、修改和分发。
许可证全文见源码仓库 LICENSE，第三方声明见 third-party 目录。
源码：https://github.com/Freeze7y/gpu-selector
附带官方 Python x86 运行时用于 32 位探测，无需额外安装。

数据目录：
""" + str(self.data_dir))
        help_layout.addWidget(help_text)
        help_actions = QHBoxLayout()
        self.restore_button = button('撤销最近设置', self.restore)
        self.restore_button.setEnabled(False)
        help_actions.addWidget(self.restore_button)
        help_actions.addWidget(button('打开备份目录', self.open_backups))
        help_layout.addLayout(help_actions)
        help_layout.addWidget(button('选择历史备份并恢复…', self.restore_history))
        help_layout.addWidget(button('查看开源许可证与第三方声明', self.show_licenses))
        help_layout.addWidget(label('备份、操作日志和设备信息可在“备份与日志”页集中查看。', 'subtitle'))
        self.tabs.addTab(scroll_page(help_page), '说明与备份')
        from application_page import ApplicationPage
        from profiles import ProfilesPage
        from management_page import ManagementPage
        self.application_page = ApplicationPage(self)
        self.profiles_page = ProfilesPage(self)
        self.management_page = ManagementPage(self)
        for index, page, title in [(2, self.application_page, '应用设置'), (3, self.profiles_page, '配置方案'), (4, self.management_page, '备份与日志')]:
            self.tabs.insertTab(index, scroll_page(page), title)
        self.tabs.setTabText(5, '外观与说明')
        self.tabs.setUsesScrollButtons(True)
        self.notice = label('就绪 · 自动适配屏幕缩放 · 操作前备份，操作后校验', 'subtitle')
        outer.addWidget(self.notice)
        self.setCentralWidget(base)
        self.theme_combo.currentIndexChanged.connect(self.apply_appearance)
        self.font_spin.valueChanged.connect(self.apply_appearance)
        self.apply_appearance()
        self.restore_window()
        self.refresh()
        self.tabs.currentChanged.connect(self.refresh_page)
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.refresh(rescan=False))
        timer.start(15000)
        self.timer = timer

    def card(self, title, description, combo, actions):
        frame = QFrame()
        frame.setObjectName('card')
        box = QVBoxLayout(frame)
        box.setContentsMargins(21, 18, 21, 18)
        box.setSpacing(12)
        box.addWidget(label(title, 'section'))
        box.addWidget(label(description, 'subtitle'))
        if combo:
            box.addWidget(combo)
        row = QGridLayout()
        for index, (text, action, primary) in enumerate(actions):
            item = button(text, action, primary)
            self.action_buttons.append(item)
            row.addWidget(item, index // 2, index % 2)
        box.addLayout(row)
        return frame

    def show_licenses(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('开源许可证与来源')
        area = self.screen().availableGeometry()
        dialog.resize(min(900, int(area.width() * .9)), min(650, int(area.height() * .85)))
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('基于 nethe-GitHub/select_default_GPU 改编，AGPL-3.0。\n源码：https://github.com/Freeze7y/gpu-selector\n使用 Qt / PySide6（LGPLv3）；第三方组件保留其各自许可证。'))
        choices = QComboBox()
        choices.setMinimumContentsLength(24)
        choices.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        paths = [HERE / 'LICENSE', HERE / 'third-party' / 'THIRD_PARTY_NOTICES.md']
        paths += sorted(path for path in (HERE / 'third-party' / 'licenses').rglob('*') if path.is_file())
        paths += [HERE / 'probe32' / 'LICENSE.txt']
        for path in paths:
            choices.addItem(str(path.relative_to(HERE)))
        layout.addWidget(choices)
        content = QTextEdit()
        content.setReadOnly(True)
        layout.addWidget(content, 1)
        def display(index):
            try:
                content.setPlainText(paths[index].read_text(encoding='utf-8-sig', errors='replace'))
            except OSError as exc:
                content.setPlainText('无法读取此许可文件：' + str(exc))
        choices.currentIndexChanged.connect(display)
        display(0)
        layout.addWidget(button('关闭', dialog.accept))
        dialog.exec()

    def refresh(self, rescan=True):
        if self.busy:
            return False
        try:
            if rescan or not self.read_ok or time.monotonic() - self.last_device_scan >= 60:
                gpus = adapters(self.db)
                self.last_device_scan = time.monotonic()
            else:
                gpus = self.gpus
            text = report(self.db, gpus)
            did = dx_target(self.db)
            self.gpus = gpus
            for mode, combo in [('DX', self.dx_combo), ('GL', self.gl_combo)]:
                key = combo.currentData()
                items = []
                for gpu in self.gpus:
                    if not gpu.get('present', True):
                        continue
                    if (mode == 'DX' and gpu['did']) or (mode == 'GL' and gpu['gl'] and gpu['gl32']):
                        items.append((gpu['name'] + '  ·  ' + (gpu['did'] if mode == 'DX' else 'ICD ' + gpu['key']), gpu['key']))
                if items != [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]:
                    combo.clear()
                    for title, item_key in items:
                        combo.addItem(title, item_key)
                if self.first_load:
                    if mode == 'DX':
                        key = next((g['key'] for g in self.gpus if g['did'] and g['did'].upper() == did), key)
                    else:
                        key = next((g['key'] for g in self.gpus if g.get('present', True) and g['gl'] and g['gl32'] and not check_plan(self.db, gl_plan(self.gpus, g))), key)
                index = combo.findData(key)
                if index >= 0:
                    combo.setCurrentIndex(index)
            self.summary.setText(f'已识别 {sum(g.get("present", True) for g in self.gpus)} 个当前设备   /   ' + ('管理员模式' if admin() else '普通模式 · DirectX 可直接设置'))
            self.report_text = text
            self.render_report()
            for item in self.action_buttons:
                item.setEnabled(True)
            if not self.read_ok and self.notice.text().startswith('读取失败'):
                self.notice.setText('状态读取已恢复。')
            self.read_ok = True
            self.first_load = False
            self.update_reboot_status()
            if rescan or self.tabs.currentIndex() == 2:
                self.refresh_page(self.tabs.currentIndex())
            return True
        except Exception as exc:
            self.read_ok = False
            self.verification_text = ''
            for item in self.action_buttons:
                item.setEnabled(False)
            self.notice.setText('读取失败：' + str(exc))
            self.report_text = '无法完整读取状态，不能确认设置成功。\n' + str(exc)
            self.status.setPlainText(self.report_text)
            return False

    def render_report(self):
        scroll = self.status.verticalScrollBar().value()
        self.status.setPlainText(self.report_text + self.verification_text + self.probe_text)
        self.status.verticalScrollBar().setValue(scroll)

    def fresh_selected(self, mode):
        old = self.selected(mode)
        if not self.refresh():
            raise ValueError('无法读取最新状态，已停止操作。')
        selected = self.selected(mode)
        if selected['key'] != old['key'] or selected['did'] != old['did']:
            raise ValueError('显卡列表已变化，请重新选择目标。')
        return selected

    def selected(self, mode):
        key = (self.dx_combo if mode == 'DX' else self.gl_combo).currentData()
        return next(g for g in self.gpus if g['key'] == key)

    def error(self, exc):
        self.log('错误', '失败', str(exc))
        QMessageBox.critical(self, '操作未完成', str(exc))
        self.refresh()

    def execute(self, plan, name):
        validate_operations(plan)
        if not check_plan(self.db, plan):
            self.notice.setText('当前配置已经一致，无需重复写入或生成备份。')
            self.log(name, '无需修改')
            return True
        before = capture_before(self.db, plan)
        changed = [op for old, op in zip(before, plan) if old['value'] != op['value']]
        changes_gl = any(op['root'] == 'HKLM' for op in changed)
        self.busy = True
        try:
            if PreviewDialog(self, name, before, plan).exec() != QDialog.Accepted:
                self.log(name, '已取消')
                return False
            if check_plan(self.db, before):
                raise ValueError('预览期间设置发生变化，已停止写入；请重新查看最新配置。')
            if changes_gl and not admin():
                QMessageBox.information(self, '需要管理员权限', '这项操作包含 OpenGL 系统设置。请以管理员身份重新打开程序，再选择同一方案或备份进行预览和应用。')
                return False
            self.log(name, '开始应用', f'{len(changed)} 个注册表值')
            self.last_backup = apply_plan(self.db, changed, self.backup_dir, name)
            self.last_plan = changed
            self.restore_button.setEnabled(True)
            self.log(name, '成功', '读回校验通过；备份：' + self.last_backup.name)
            if changes_gl:
                from system_status import record_gl_change
                try:
                    record_gl_change(self.data_dir, name)
                except OSError as exc:
                    self.log('重启记录', '失败', str(exc))
        except Exception as exc:
            self.log(name, '失败', str(exc))
            raise
        finally:
            self.busy = False
        self.refresh()
        self.notice.setText('设置已写入并通过逐项读回校验 · 备份：' + self.last_backup.name)
        self.tabs.setCurrentIndex(1)
        return True

    def open_settings(self):
        try:
            if not self.refresh():
                return
            if self.execute(settings_plan(), 'Windows'):
                os.startfile('ms-settings:display-advancedgraphics')
        except Exception as exc:
            self.error(exc)

    def apply_dx(self):
        try:
            self.execute(dx_plan(self.db, self.fresh_selected('DX')), 'DirectX')
        except StopIteration:
            self.error('没有可选的 DirectX 显卡。')
        except Exception as exc:
            self.error(exc)

    def apply_gl(self):
        try:
            gpu = self.fresh_selected('GL')
            plan = gl_plan(self.gpus, gpu)
            gl_preflight(gpu)
            if not check_plan(self.db, plan):
                self.execute(plan, 'OpenGL')
                return
            if not admin():
                before = capture_before(self.db, plan)
                if PreviewDialog(self, 'OpenGL 修改预览（需要管理员权限）', before, plan).exec() != QDialog.Accepted:
                    return
                if QMessageBox.question(self, '需要管理员权限', 'OpenGL 会修改系统级驱动注册表。是否以管理员身份重新打开本程序？\n重新打开后请再次选择显卡并应用。') != QMessageBox.Yes:
                    return
                args = ([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]) + ['--select-gl', gpu['key']]
                result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, subprocess.list2cmdline(args), None, 1)
                if result <= 32:
                    raise OSError('提权未完成或已取消。')
                self.close()
                return
            if self.execute(plan, 'OpenGL'):
                self.notice.setText('OpenGL 注册表已校验通过 · 首次使用请重启，再检查目标应用的 GPU 引擎。')
        except StopIteration:
            self.error('没有可用的 OpenGL ICD。')
        except Exception as exc:
            self.error(exc)

    def verify(self):
        try:
            if not self.refresh():
                return
            results = []
            for mode in ('DX', 'GL'):
                try:
                    gpu = self.selected(mode)
                    failures = ([] if dx_matches(self.db, gpu) else ['HighPerfAdapter 与所选硬件 ID 不一致']) if mode == 'DX' else check_plan(self.db, gl_plan(self.gpus, gpu))
                    results.append(mode + ' · ' + gpu['name'] + '\n' + ('所选配置与注册表完全匹配。' if not failures else f'与所选配置不一致：{len(failures)} 项\n' + '\n'.join(failures)))
                except (StopIteration, ValueError) as exc:
                    results.append(mode + '：无法检查所选设备。' + str(exc))
            text = '\n\n'.join(results) + '\n\n以上为配置校验，不代表运行时 GPU 验证。'
            self.verification_text = '\n\n【最近一次所选配置检查 · ' + datetime.datetime.now().strftime('%H:%M:%S') + '】\n' + text + '\n此部分是检查时的快照，重新检查可更新。'
            self.render_report()
            self.status.verticalScrollBar().setValue(self.status.verticalScrollBar().maximum())
            self.notice.setText('已检查所选配置，详细结果见报告末尾。')
        except Exception as exc:
            self.error(exc)

    def export(self, mode):
        try:
            gpu = self.fresh_selected(mode)
            if mode == 'GL':
                gl_preflight(gpu)
            data = export_bat(mode, gpu, self.gpus)
            path, _ = QFileDialog.getSaveFileName(self, '导出独立批处理', f'select_{mode}_{gpu["key"]}.bat', '批处理 (*.bat)')
            if path:
                Path(path).write_bytes(data.encode('utf-8'))
                self.notice.setText('已导出：' + path)
        except StopIteration:
            self.error('没有可导出的设备。')
        except Exception as exc:
            self.error(exc)

    def save_report(self):
        text = self.status.toPlainText()
        path, _ = QFileDialog.getSaveFileName(self, '导出检查报告', 'GPU检查报告.txt', '文本 (*.txt)')
        if path:
            try:
                Path(path).write_text(text, encoding='utf-8-sig')
                self.notice.setText('检查报告已保存。')
            except OSError as exc:
                self.error(exc)

    def restore(self):
        try:
            plan = restore_plan(self.db, self.last_backup)
            if self.execute(plan, 'Undo'):
                self.notice.setText('已恢复最近一次操作前的注册表值；OpenGL 恢复后可能需要重启。')
        except Exception as exc:
            self.error(exc)

    def open_backups(self):
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.backup_dir))
        except OSError as exc:
            self.error(exc)

    def task_manager(self):
        try:
            subprocess.Popen([str(Path(os.environ['WINDIR']) / 'System32' / 'Taskmgr.exe')])
        except OSError as exc:
            self.error(exc)

    def reset_dx(self):
        try:
            if not self.refresh():
                return
            if QMessageBox.question(self, '恢复系统自动选择', '移除 DirectX 全局高性能显卡指定，保留其他全局参数。继续？') == QMessageBox.Yes:
                self.execute(dx_reset_plan(self.db), 'DirectX-Auto')
        except Exception as exc:
            self.error(exc)

    def restore_history(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择历史备份（建议从最新开始）', str(self.backup_dir), 'GPU 设置备份 (*.json)')
        if not path:
            return
        try:
            plan = restore_plan(self.db, path)
            if any(op['root'] == 'HKLM' for op in plan) and not admin():
                raise ValueError('这份备份涉及 OpenGL 系统项。请以管理员身份启动本程序后，再选择这份历史备份。')
            self.execute(restore_plan(self.db, path), 'History-Restore')
        except Exception as exc:
            self.error(exc)

    def start_probe(self, kind='gl64'):
        if self.probe_process is not None:
            return
        self.probe_kind = kind
        self.probe_temp = tempfile.TemporaryDirectory(prefix='GPUSelector-probe-')
        self.probe_output = Path(self.probe_temp.name) / 'result.json'
        self.probe_timed_out = False
        process = QProcess(self)
        self.probe_process = process
        for item in self.probe_buttons:
            item.setEnabled(False)
        self.notice.setText('正在实测…最长 20 秒，可继续查看其他页面。')
        if kind == 'gl32':
            program = str(HERE / 'probe32' / 'pythonw.exe')
            args = [str(HERE / 'probe32' / 'runner.py'), str(self.probe_output)]
        else:
            program = sys.executable
            args = ([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]) + ['--probe-dx' if kind == 'dx' else '--probe-gl', str(self.probe_output)]
        process.setProgram(program)
        process.setArguments(args)
        process.finished.connect(self.finish_probe)
        process.errorOccurred.connect(self.probe_error)
        self.probe_timeout = QTimer(self)
        self.probe_timeout.setSingleShot(True)
        self.probe_timeout.timeout.connect(self.timeout_probe)
        self.probe_timeout.start(20000)
        process.start()

    def timeout_probe(self):
        if self.probe_process is not None:
            self.probe_timed_out = True
            self.probe_process.kill()

    def probe_error(self, error):
        if error == QProcess.FailedToStart:
            self.finish_probe(-1, QProcess.CrashExit)

    def finish_probe(self, code, exit_status):
        if self.probe_process is None:
            return
        self.probe_timeout.stop()
        try:
            if self.probe_timed_out:
                raise RuntimeError('驱动探测超过 20 秒，已终止探针进程；没有修改显卡配置。')
            if code != 0 or exit_status != QProcess.NormalExit:
                raise RuntimeError(f'探针进程未正常完成（退出码 {code}）。可能是驱动问题，主界面仍可继续使用。')
            data = json.loads(self.probe_output.read_text(encoding='utf-8'))
            if not data.get('ok'):
                raise RuntimeError(data.get('error', '未取得渲染器信息。'))
            expected_bits = 32 if self.probe_kind == 'gl32' else 64
            if data.get('process_bits') != expected_bits:
                raise RuntimeError('探针返回的进程位数与请求不符，拒绝当成成功。')
            text = f'渲染器：{data["renderer"]}\n厂商：{data["vendor"]}\n版本 / 协商级别：{data["version"]}\n进程位数：{data["process_bits"]}\n{data["limitation"]}'
            if self.probe_kind == 'dx':
                render = data.get('render_test', {})
                if not render.get('passed'):
                    raise RuntimeError('Direct3D 11 离屏清色回读未通过。')
                text += '\n离屏清色回读：通过\n' + str(render.get('method', ''))
            self.log('探测 ' + self.probe_kind, '成功', text)
        except Exception as exc:
            text = '实测未完成：' + str(exc)
            self.log('探测 ' + self.probe_kind, '失败', str(exc))
        title = {'gl64':'OpenGL 64 位', 'gl32':'OpenGL 32 位', 'dx':'Direct3D 11'}[self.probe_kind]
        self.probe_results[self.probe_kind] = '\n\n【' + title + ' 实测 · ' + datetime.datetime.now().strftime('%H:%M:%S') + '】\n' + text
        self.probe_text = ''.join(self.probe_results.values())
        self.render_report()
        self.tabs.setCurrentIndex(1)
        self.status.verticalScrollBar().setValue(self.status.verticalScrollBar().maximum())
        self.notice.setText(title + ' 探针已结束，结果见报告末尾。')
        self.probe_process.deleteLater()
        self.probe_process = None
        self.probe_timeout.deleteLater()
        self.probe_temp.cleanup()
        for item in self.probe_buttons:
            item.setEnabled(True)

    def log(self, action, result, details=''):
        from system_status import write_log
        try:
            write_log(self.data_dir, action, result, details)
        except OSError:
            # Logging failure must not turn an already successful GPU write into failure.
            self.notice.setText('操作日志无法保存，请检查数据目录权限。')

    def update_reboot_status(self):
        from system_status import reboot_status
        status = reboot_status(self.data_dir)
        self.reboot_notice.setText(status['text'])

    def refresh_page(self, index=None):
        index = self.tabs.currentIndex() if index is None else index
        page = {2:self.application_page, 3:self.profiles_page, 4:self.management_page}.get(index)
        if page is not None:
            page.refresh()

    def apply_appearance(self):
        theme = self.theme_combo.currentData()
        size = self.font_spin.value()
        self.preferences.update(theme=theme, font_size=size)
        QApplication.instance().setFont(QFont('Microsoft YaHei UI', size))
        QApplication.instance().setStyleSheet(style_for(STYLE, theme, size))
        link_color = '#9ccbff' if theme == 'dark' else '#175f9a'
        self.author_link.setText('作者：Freeze7y<br><a style="color:' + link_color + '" href="https://github.com/Freeze7y/gpu-selector">github.com/Freeze7y/gpu-selector</a>')
        self.update_panel.release_link.setText('<a style="color:' + link_color + '" href="https://github.com/Freeze7y/gpu-selector/releases">查看 GitHub 发布页</a>')

    def restore_window(self):
        geometry = self.preferences.get('geometry')
        if isinstance(geometry, str):
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode('ascii', errors='ignore')))
        screens = QApplication.screens()
        if not any(screen.availableGeometry().intersects(self.frameGeometry()) for screen in screens):
            self.move(QApplication.primaryScreen().availableGeometry().topLeft())
        area = self.screen().availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        if self.preferences.get('maximized') is True:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)

    def resizeEvent(self, event):
        if hasattr(self, 'heading'):
            self.heading.setVisible(self.height() >= 650)
            self.eyebrow.setVisible(self.height() >= 550)
            self.subtitle.setVisible(self.height() >= 550)
        super().resizeEvent(event)

    def closeEvent(self, event):
        if not self.update_panel.prepare_close():
            event.ignore()
            return
        if self.probe_process is not None:
            # Keep the event loop running until the isolated process exits.
            event.ignore()
            self.probe_process.finished.connect(lambda *_: self.close())
            self.probe_process.kill()
            return
        self.preferences['geometry'] = bytes(self.saveGeometry().toBase64()).decode('ascii')
        self.preferences['maximized'] = self.isMaximized()
        try:
            save_preferences(self.data_dir, self.preferences)
        except OSError as exc:
            self.log('保存窗口设置', '失败', str(exc))
        super().closeEvent(event)


def main():
    if '--apply-update' in sys.argv:
        from update_installer import run_update_helper
        job = Path(sys.argv[sys.argv.index('--apply-update') + 1])
        sys.exit(run_update_helper(job))
    if '--probe-dx' in sys.argv:
        from dx_probe import probe
        destination = Path(sys.argv[sys.argv.index('--probe-dx') + 1])
        destination.write_text(json.dumps(probe(), ensure_ascii=False), encoding='utf-8')
        return
    if '--probe-gl' in sys.argv:
        from gl_probe import probe
        destination = Path(sys.argv[sys.argv.index('--probe-gl') + 1])
        destination.write_text(json.dumps(probe(), ensure_ascii=False), encoding='utf-8')
        return
    if '--diagnose' in sys.argv:
        destination = Path(sys.argv[sys.argv.index('--diagnose') + 1])
        db = Registry()
        destination.write_text(report(db, adapters(db)), encoding='utf-8-sig')
        return
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(STYLE)
    smoke_all = Path(sys.argv[sys.argv.index('--smoke-all') + 1]) if '--smoke-all' in sys.argv else None
    completed_update = Path(sys.argv[sys.argv.index('--update-complete') + 1]) if '--update-complete' in sys.argv else None
    update_folder = None
    if completed_update is not None:
        from update_installer import update_data_dir, mark_update_ready
        update_folder = update_data_dir(completed_update)
    window = Window(data_dir=smoke_all / 'data' if smoke_all else update_folder)
    if '--select-gl' in sys.argv:
        key = sys.argv[sys.argv.index('--select-gl') + 1]
        index = window.gl_combo.findData(key)
        if index >= 0:
            window.gl_combo.setCurrentIndex(index)
    window.show()
    if completed_update is not None:
        def confirm_update_start():
            try:
                mark_update_ready(completed_update)
                window.update_panel.status.setText('已更新至 ' + VERSION + '，程序启动验证已通过。')
            except Exception as exc:
                window.update_panel.status.setText('更新启动验证失败：' + str(exc))
                window.log('软件更新', '启动验证失败', str(exc))
        QTimer.singleShot(300, confirm_update_start)
    if not smoke_all and '--smoke-test' not in sys.argv:
        QTimer.singleShot(0, window.update_panel.startup)
    if smoke_all:
        smoke_all.mkdir(parents=True, exist_ok=True)
        kinds = ['gl64', 'gl32', 'dx']
        completed = []
        license_check = []
        def begin_all():
            window.tabs.setCurrentIndex(0)
            window.grab().save(str(smoke_all / 'interface.png'))
            for index in range(window.tabs.count()):
                window.tabs.setCurrentIndex(index)
                app.processEvents()
                window.grab().save(str(smoke_all / f'page-{index}.png'))
            def capture_licenses():
                dialog = app.activeModalWidget()
                choices = dialog.findChild(QComboBox)
                content = dialog.findChild(QTextEdit)
                valid = choices.count() >= 4
                for index in range(choices.count()):
                    choices.setCurrentIndex(index)
                    text = content.toPlainText()
                    valid = valid and bool(text) and not text.startswith('无法读取')
                choices.setCurrentIndex(0)
                dialog.grab().save(str(smoke_all / 'licenses.png'))
                license_check.append(valid)
                dialog.accept()
            QTimer.singleShot(50, capture_licenses)
            window.show_licenses()
            next_probe()
        def next_probe():
            if not kinds:
                window.tabs.setCurrentIndex(1)
                window.grab().save(str(smoke_all / 'probes.png'))
                (smoke_all / 'report.txt').write_text(window.status.toPlainText(), encoding='utf-8-sig')
                window.theme_combo.setCurrentIndex(1)
                window.font_spin.setValue(12)
                window.tabs.setCurrentIndex(2)
                window.resize(640, 520)
                QTimer.singleShot(300, finish_all)
                return
            completed.append(kinds.pop(0))
            window.start_probe(completed[-1])
            poll.start(100)
        def wait_probe():
            if window.probe_process is None:
                poll.stop()
                QTimer.singleShot(50, next_probe)
        def finish_all():
            window.grab().save(str(smoke_all / 'compact-light.png'))
            results = {kind: '实测未完成' not in window.probe_results.get(kind, '实测未完成') for kind in completed}
            results['licenses'] = license_check == [True]
            (smoke_all / 'results.json').write_text(json.dumps(results), encoding='utf-8')
            window.close()
            app.exit(0 if all(results.values()) else 1)
        poll = QTimer(window)
        poll.timeout.connect(wait_probe)
        QTimer.singleShot(1200, begin_all)
    if '--smoke-test' in sys.argv:
        output = Path(sys.argv[sys.argv.index('--smoke-test') + 1])
        output.mkdir(parents=True, exist_ok=True)
        def capture():
            window.grab().save(str(output / 'interface.png'))
            window.tabs.setCurrentIndex(1)
            window.verify()
            window.grab().save(str(output / 'status.png'))
            (output / 'report.txt').write_text(window.status.toPlainText(), encoding='utf-8-sig')
            window.resize(640, 480)
            window.tabs.setCurrentIndex(0)
            QTimer.singleShot(500, finish)
        def finish():
            window.grab().save(str(output / 'compact.png'))
            app.quit()
        QTimer.singleShot(1200, capture)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
