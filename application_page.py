"""Desktop application GPU preference editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QVBoxLayout, QWidget)

from app_preferences import PREFERENCES, app_plan, list_app_preferences, normalize_exe, preference_state
from gpu_core import PREF


def text_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    return label


class ApplicationPage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.entries = []
        box = QVBoxLayout(self)
        box.addWidget(text_label('按应用设置 GPU 偏好'))
        box.addWidget(text_label('为桌面程序选择系统自动、节能或高性能。具体显卡由 Windows 决定；软件自行选择 GPU 时可能不遵循偏好。应用后请完整退出并重新启动目标程序。'))
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText('选择游戏或软件实际运行的 .exe 文件')
        row.addWidget(self.path_edit, 1)
        browse = QPushButton('选择 EXE…')
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        box.addLayout(row)
        self.preference = QComboBox()
        for mode, label in PREFERENCES.items():
            self.preference.addItem(label, mode)
        box.addWidget(self.preference)
        actions = QGridLayout()
        self.apply_button = QPushButton('预览并应用')
        self.apply_button.setObjectName('primary')
        self.apply_button.clicked.connect(self.apply)
        actions.addWidget(self.apply_button, 0, 0)
        self.reset_button = QPushButton('恢复自动选择')
        self.reset_button.clicked.connect(self.reset)
        actions.addWidget(self.reset_button, 0, 1)
        self.verify_button = QPushButton('检查所选应用')
        self.verify_button.clicked.connect(self.verify)
        actions.addWidget(self.verify_button, 1, 0)
        refresh = QPushButton('刷新列表')
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh, 1, 1)
        box.addLayout(actions)
        self.feedback = text_label('选择应用后，可检查当前配置或预览修改。')
        box.addWidget(self.feedback)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['应用', '当前偏好 / 文件状态', '完整路径'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(130)
        self.table.itemSelectionChanged.connect(self.select_row)
        box.addWidget(self.table, 1)
        box.addWidget(text_label('仅更改 GPU 偏好，保留 Auto HDR、窗口化优化等其他参数。恢复自动会清除应用的 GPU 指定项。列表中的不存在路径仍可清除偏好；不会删除应用文件。'))

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择应用实际运行的 EXE', '', 'Windows 程序 (*.exe)')
        if path:
            self.path_edit.setText(normalize_exe(path))
            self.load_current(self.path_edit.text())

    def load_current(self, path):
        try:
            path = normalize_exe(path)
            item = self.owner.db.read('HKCU', PREF, path, 64)
            mode, status = preference_state(*item) if item else preference_state(None)
            self.preference.setCurrentIndex(self.preference.findData(mode))
            self.feedback.setText('当前配置：' + status + '。读到偏好不代表目标程序已使用相应显卡。')
        except Exception as exc:
            self.feedback.setText('读取失败：' + str(exc))

    def select_row(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries):
            self.path_edit.setText(self.entries[row]['path'])
            self.load_current(self.entries[row]['path'])

    def refresh(self):
        try:
            entries = list_app_preferences(self.owner.db)
            selected = self.path_edit.text().casefold()
            scroll = self.table.verticalScrollBar().value()
            self.table.blockSignals(True)
            self.table.setRowCount(len(entries))
            self.entries = entries
            for row, item in enumerate(entries):
                status = item['status'] + ('' if item['exists'] else ' · 文件不存在')
                for col, raw in enumerate((item['name'], status, item['path'])):
                    cell = QTableWidgetItem(raw)
                    cell.setToolTip(raw)
                    self.table.setItem(row, col, cell)
                if item['path'].casefold() == selected:
                    self.table.selectRow(row)
            self.table.verticalScrollBar().setValue(scroll)
            self.apply_button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self.verify_button.setEnabled(True)
            return True
        except Exception as exc:
            self.feedback.setText('应用列表读取失败，停止操作：' + str(exc))
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.verify_button.setEnabled(False)
            return False
        finally:
            self.table.blockSignals(False)

    def apply(self):
        self.change(self.preference.currentData())

    def reset(self):
        self.change(0)

    def change(self, preference):
        try:
            if not self.owner.refresh():
                raise ValueError('无法读取最新系统状态，已停止操作。')
            plan = app_plan(self.owner.db, self.path_edit.text(), preference, require_exists=preference != 0)
            if self.owner.execute(plan, '应用GPU偏好'):
                self.refresh()
                self.load_current(plan[0]['name'])
                self.feedback.setText('已应用并读回验证：' + PREFERENCES[preference] + '。请完整退出并重新启动目标程序。')
        except Exception as exc:
            QMessageBox.critical(self, '应用偏好未完成', str(exc))

    def verify(self):
        try:
            path = normalize_exe(self.path_edit.text())
            item = self.owner.db.read('HKCU', PREF, path, 64)
            mode, status = preference_state(*item) if item else preference_state(None)
            matches = mode is not None and mode == self.preference.currentData()
            self.feedback.setText('所选偏好与注册表一致；实际 GPU 请在任务管理器中检查。' if matches
                                  else '所选偏好与当前配置不一致。当前：' + status)
        except Exception as exc:
            self.feedback.setText('无法确认配置：' + str(exc))
