"""Opt-in update UI; blocking network and installer work runs off the GUI thread."""
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QThread, QTimer, Qt, Slot
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app_version import VERSION
from ui_preferences import save_preferences
from update_service import check_for_update, download_update

PREFERENCE = 'check_updates_on_startup'
RELEASES_URL = 'https://github.com/Freeze7y/gpu-selector/releases'


def install_update(downloaded, sha256, data_dir):
    from update_installer import install_update as prepare_install
    return prepare_install(downloaded, sha256, data_dir)


def packaged():
    return bool(getattr(sys, 'frozen', False))


class UpdateJob(QThread):
    def __init__(self, operation, cancellable):
        super().__init__()
        self.operation = operation
        self.value = None
        self.error = None
        self.cancel_event = threading.Event() if cancellable else None

    def run(self):
        try:
            self.value = self.operation(self.cancel_event)
        except Exception as exc:
            self.error = str(exc)


class UpdatePanel(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.thread = None
        self.mode = None
        self._started = False
        self._closing = False
        self._automatic = False
        self._owns_busy = False
        self._central = None
        self._central_enabled = True
        self._download_info = None
        self._ready = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        row = QHBoxLayout()
        row.addWidget(QLabel('软件更新 · 当前 ' + VERSION), 1)
        self.check_button = QPushButton('检查更新')
        self.check_button.clicked.connect(lambda _checked=False: self.check())
        row.addWidget(self.check_button)
        layout.addLayout(row)
        self.auto_check = QCheckBox('启动时检查更新（新版确认后安装）')
        self.auto_check.setChecked(owner.preferences.get(PREFERENCE) is True)
        self.auto_check.toggled.connect(self.set_preference)
        layout.addWidget(self.auto_check)
        self.status = QLabel('可手动检查更新；下载与安装前会征求确认。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.install_button = QPushButton('安装已下载更新')
        self.install_button.clicked.connect(self.install_ready)
        self.install_button.hide()
        layout.addWidget(self.install_button)
        self.release_link = QLabel('<a href="' + RELEASES_URL + '">查看 GitHub 发布页</a>')
        self.release_link.setOpenExternalLinks(True)
        self.release_link.setTextFormat(Qt.RichText)
        self.release_link.setWordWrap(True)
        layout.addWidget(self.release_link)

    def set_preference(self, enabled):
        before = self.owner.preferences.get(PREFERENCE)
        self.owner.preferences[PREFERENCE] = bool(enabled)
        try:
            save_preferences(self.owner.data_dir, self.owner.preferences)
        except OSError as exc:
            if before is None:
                self.owner.preferences.pop(PREFERENCE, None)
            else:
                self.owner.preferences[PREFERENCE] = before
            self.auto_check.blockSignals(True)
            self.auto_check.setChecked(before is True)
            self.auto_check.blockSignals(False)
            self.status.setText('更新偏好未能保存：' + str(exc))
            return False
        self.status.setText('已开启启动检查；发现新版后仍需确认下载与安装。' if enabled else '已关闭启动检查；仍可手动检查更新。')
        return True

    def startup(self):
        """Called explicitly after showing a normal interactive window, never by construction."""
        if self._started or self._closing:
            return
        self._started = True
        choice = self.owner.preferences.get(PREFERENCE)
        if type(choice) is not bool:
            dialog = QMessageBox(self)
            dialog.setWindowTitle('启动时检查更新')
            dialog.setIcon(QMessageBox.Question)
            dialog.setTextFormat(Qt.PlainText)
            dialog.setText('是否在每次启动时连接 GitHub 检查新版本？\n发现新版后会先询问，确认后才下载并安装。可随时在“外观与说明”中更改。')
            dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            dialog.setDefaultButton(QMessageBox.No)
            dialog.setEscapeButton(QMessageBox.No)
            choice = dialog.exec() == QMessageBox.Yes
            if self._closing or not self.set_preference(choice):
                return
            self.auto_check.blockSignals(True)
            self.auto_check.setChecked(choice)
            self.auto_check.blockSignals(False)
        if choice:
            self.check(automatic=True)

    def check(self, automatic=False):
        if self.thread is not None or self._closing:
            return
        if getattr(self.owner, 'busy', False):
            self.status.setText('请先完成当前操作，再检查更新。')
            return
        self._automatic = bool(automatic)
        self.status.setText('正在连接 GitHub 检查更新…')
        self._start('check', lambda cancel: check_for_update(VERSION, cancel_event=cancel))

    def _start(self, mode, operation):
        self.mode = mode
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.thread = UpdateJob(operation, cancellable=mode in ('check', 'download'))
        self.thread.finished.connect(self._completed)
        self.thread.start()

    @Slot()
    def _completed(self):
        job = self.thread
        mode = self.mode
        self.thread = None
        self.mode = None
        value, error = job.value, job.error
        job.deleteLater()
        self._release_busy()
        self.check_button.setEnabled(not self._closing)
        self.install_button.setEnabled(not self._closing)
        if self._closing:
            QTimer.singleShot(0, self.owner.close)
            return
        if error is not None:
            action = {'check': '检查更新', 'download': '下载更新', 'install': '准备安装'}[mode]
            self.status.setText(action + '失败：' + error)
            self._log(action, '失败', error)
            return
        if mode == 'check':
            if self._automatic and self.owner.preferences.get(PREFERENCE) is not True:
                self.status.setText('启动检查已关闭。')
            elif value is None:
                self.status.setText('当前已是最新可用版本：' + VERSION)
            else:
                self.offer(value)
        elif mode == 'download':
            self._ready = (Path(value), self._download_info)
            self.install_button.show()
            self.install_ready()
        elif mode == 'install':
            self.status.setText('更新已准备，正在关闭当前版本并重启…')
            self._log('软件更新', '准备完成', '独立更新程序将在本进程退出后替换并启动。')
            self.owner.close()

    def offer(self, info):
        self.status.setText('发现新版本：' + info.version)
        if not packaged():
            self.status.setText('发现新版本 ' + info.version + '。当前从源码运行，请从下方 GitHub 发布页下载 EXE；不会覆盖源码。')
            return
        if getattr(self.owner, 'busy', False) or getattr(self.owner, 'probe_process', None) is not None:
            self.status.setText('发现新版本 ' + info.version + '。请结束当前操作或渲染探针后，再点击“检查更新”。')
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle('发现软件更新')
        dialog.setIcon(QMessageBox.Question)
        dialog.setTextFormat(Qt.PlainText)
        dialog.setText(f'当前版本：{VERSION}\n新版本：{info.version}\n下载大小：{info.size / (1024 * 1024):.1f} MB\n\n是否下载并安装？下载校验通过后将关闭本程序，替换并重新启动；显卡设置和备份保持不变。\n\n发布页：{info.release_url}')
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        dialog.setEscapeButton(QMessageBox.No)
        accepted = dialog.exec() == QMessageBox.Yes
        if not accepted or self._closing:
            self.status.setText('已取消更新，可稍后重新检查。')
            return
        if getattr(self.owner, 'busy', False) or getattr(self.owner, 'probe_process', None) is not None:
            self.status.setText('当前操作或渲染探针尚未结束，请完成后重新检查更新。')
            return
        self._download_info = info
        self.status.setText('正在下载并校验 ' + info.version + '，请稍候…')
        self._start('download', lambda cancel: download_update(info, Path(self.owner.data_dir) / 'updates' / 'downloads', cancel_event=cancel))

    def install_ready(self):
        if self.thread is not None or self._ready is None or self._closing:
            return
        if getattr(self.owner, 'busy', False) or getattr(self.owner, 'probe_process', None) is not None:
            self.status.setText('更新已下载并校验。请完成当前操作或渲染探针，再点击“安装已下载更新”。')
            return
        path, info = self._ready
        self.owner.busy = True
        self._owns_busy = True
        if callable(getattr(self.owner, 'centralWidget', None)):
            self._central = self.owner.centralWidget()
            if self._central is not None:
                self._central_enabled = self._central.isEnabled()
                self._central.setEnabled(False)
        self.status.setText('正在准备更新，完成后将关闭并重新启动…')
        self._start('install', lambda _cancel: install_update(path, info.sha256, self.owner.data_dir))

    def _release_busy(self):
        if self._owns_busy:
            self.owner.busy = False
            self._owns_busy = False
            if self._central is not None:
                self._central.setEnabled(self._central_enabled)
                self._central = None

    def _log(self, action, result, details):
        if callable(getattr(self.owner, 'log', None)):
            self.owner.log(action, result, details)

    def prepare_close(self):
        if self.thread is None:
            self._closing = True
            return True
        self._closing = True
        if self.thread.cancel_event is not None:
            self.thread.cancel_event.set()
            self.thread.requestInterruption()
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.status.setText('正在结束更新任务，任务结束或超时后自动关闭…')
        return False
