"""Desktop application GPU preference editor."""
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QVBoxLayout, QWidget)

from app_preferences import PREFERENCES, app_plan, clear_app_plan, list_app_preferences, normalize_exe, preference_state
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
        self.list_available = True
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
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(130)
        self.table.itemSelectionChanged.connect(self.select_row)
        box.addWidget(self.table, 1)
        self.clear_button = QPushButton('清除所选路径…')
        self.clear_button.setEnabled(False)
        self.clear_button.setToolTip('一次预览并删除所有选中路径的整条图形设置记录，包括 GPU 偏好、Auto HDR 和窗口化优化；不会删除应用文件。')
        self.clear_button.clicked.connect(self.clear_selected)
        box.addWidget(self.clear_button)
        self.path_edit.textEdited.connect(self.clear_selection)
        box.addWidget(text_label('按 Ctrl 点选多个路径、Shift 选择连续路径，列表中按 Ctrl+A 全选。多选仅用于清除；修改或检查 GPU 偏好请单选。应用偏好和恢复自动保留 Auto HDR、窗口化优化等其他参数。“清除所选路径”会删除所有选中路径的全部图形设置，统一预览和备份；不会删除应用文件。'))

    def selected_paths(self):
        rows = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        return [self.entries[row]['path'] for row in rows if 0 <= row < len(self.entries)]

    def selected_path(self):
        paths = self.selected_paths()
        return paths[0] if len(paths) == 1 else None

    def update_actions(self):
        count = len(self.selected_paths())
        single = self.list_available and count <= 1
        for widget in (self.preference, self.apply_button, self.reset_button, self.verify_button):
            widget.setEnabled(single)
        self.clear_button.setEnabled(self.list_available and count > 0)
        self.clear_button.setText(f'清除所选路径（{count} 项）…' if count else '清除所选路径…')

    def clear_selection(self):
        self.table.clearSelection()
        self.update_actions()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择应用实际运行的 EXE', '', 'Windows 程序 (*.exe)')
        if path:
            self.clear_selection()
            self.path_edit.setText(normalize_exe(path))
            self.load_current(self.path_edit.text())

    def load_current(self, path, exact_path=False):
        try:
            if not exact_path:
                path = normalize_exe(path)
            item = self.owner.db.read('HKCU', PREF, path, 64)
            mode, status = preference_state(*item) if item else preference_state(None)
            self.preference.setCurrentIndex(self.preference.findData(mode))
            self.feedback.setText('当前配置：' + status + '。读到偏好不代表目标程序已使用相应显卡。')
        except Exception as exc:
            self.feedback.setText('读取失败：' + str(exc))

    def select_row(self):
        self.update_actions()
        path = self.selected_path()
        if path is not None:
            self.path_edit.setText(path)
            self.load_current(path, exact_path=True)
        elif len(self.selected_paths()) > 1:
            self.path_edit.setText('')
            self.feedback.setText(f'已选择 {len(self.selected_paths())} 个路径，可统一预览并清除。修改或检查 GPU 偏好请先单选。')

    def refresh(self):
        try:
            entries = list_app_preferences(self.owner.db)
            selected = self.selected_paths()
            selected_keys = {path.casefold() for path in selected}
            current_row = self.table.currentRow()
            current = self.entries[current_row]['path'].casefold() if 0 <= current_row < len(self.entries) else None
            scroll = self.table.verticalScrollBar().value()
            self.table.blockSignals(True)
            self.table.setRowCount(len(entries))
            self.entries = entries
            selected_rows = []
            restored_current = None
            for row, item in enumerate(entries):
                status = item['status'] + ('' if item['exists'] else ' · 文件不存在')
                for col, raw in enumerate((item['name'], status, item['path'])):
                    cell = QTableWidgetItem(raw)
                    cell.setToolTip(raw)
                    self.table.setItem(row, col, cell)
                if item['path'].casefold() in selected_keys:
                    selected_rows.append(row)
                    if item['path'].casefold() == current:
                        restored_current = row
            self.table.clearSelection()
            for row in selected_rows:
                self.table.selectionModel().select(self.table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows)
            if restored_current is not None:
                self.table.selectionModel().setCurrentIndex(self.table.model().index(restored_current, 0),
                    QItemSelectionModel.NoUpdate)
            self.table.verticalScrollBar().setValue(scroll)
            self.list_available = True
            self.update_actions()
            if len(selected) > 1 and selected_rows:
                self.select_row()
            return True
        except Exception as exc:
            self.feedback.setText('应用列表读取失败，停止操作：' + str(exc))
            self.list_available = False
            self.update_actions()
            return False
        finally:
            self.table.blockSignals(False)

    def apply(self):
        self.change(self.preference.currentData())

    def reset(self):
        self.change(0)

    def clear_selected(self):
        try:
            paths = self.selected_paths()
            if not paths:
                raise ValueError('请先在列表中选择要清除的一个或多个路径。')
            if not self.owner.refresh():
                raise ValueError('无法读取最新系统状态，已停止操作。')
            plan = [operation for path in paths for operation in clear_app_plan(self.owner.db, path)]
            if self.owner.execute(plan, f'清除 {len(paths)} 个应用路径及全部图形设置'):
                if self.refresh():
                    detail = paths[0] if len(paths) == 1 else f'{len(paths)} 个所选路径'
                    self.feedback.setText('已清除并读回验证：' + detail + '。未删除应用文件；可从“备份与日志”恢复全部设置。')
        except Exception as exc:
            QMessageBox.critical(self, '路径清除未完成', str(exc))

    def change(self, preference):
        try:
            if len(self.selected_paths()) > 1:
                raise ValueError('多选仅用于清除；修改 GPU 偏好请先单选一个应用。')
            path = self.path_edit.text()
            exact_path = path == self.selected_path()
            if not self.owner.refresh():
                raise ValueError('无法读取最新系统状态，已停止操作。')
            plan = app_plan(self.owner.db, path, preference, require_exists=preference != 0,
                            exact_path=exact_path)
            if self.owner.execute(plan, '应用GPU偏好'):
                self.refresh()
                self.load_current(plan[0]['name'], exact_path=True)
                self.feedback.setText('已应用并读回验证：' + PREFERENCES[preference] + '。请完整退出并重新启动目标程序。')
        except Exception as exc:
            QMessageBox.critical(self, '应用偏好未完成', str(exc))

    def verify(self):
        try:
            if len(self.selected_paths()) > 1:
                raise ValueError('检查 GPU 偏好请先单选一个应用。')
            path = self.path_edit.text()
            if path != self.selected_path():
                path = normalize_exe(path)
            item = self.owner.db.read('HKCU', PREF, path, 64)
            mode, status = preference_state(*item) if item else preference_state(None)
            matches = mode is not None and mode == self.preference.currentData()
            self.feedback.setText('所选偏好与注册表一致；实际 GPU 请在任务管理器中检查。' if matches
                                  else '所选偏好与当前配置不一致。当前：' + status)
        except Exception as exc:
            self.feedback.setText('无法确认配置：' + str(exc))
