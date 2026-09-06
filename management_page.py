"""Backup, operation history and device health views; mutations belong to owner."""
import datetime
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from gpu_core import GLOBAL, GL, restore_plan
from system_status import export_logs, health_rows, read_logs, reboot_status


def backup_rows(db, backup_dir, gpus):
    folder = Path(backup_dir)
    if not folder.exists():
        return []
    rows = []
    for path in folder.glob('*.json'):
        row = dict(path=str(path), time='', label=path.stem, target='未知', eligible=False, error='', order=0)
        try:
            stat = path.stat()
            row['order'] = stat.st_mtime
            row['time'] = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            if stat.st_size > 1024 * 1024:
                raise ValueError('备份文件过大')
            saved = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(saved, dict):
                raise ValueError('备份内容不是对象')
            row['label'] = str(saved.get('label') or path.stem)
            # restore_plan validates the entire payload and current ownership.
            # A mismatched backup remains visible, with the exact refusal reason.
            targets = []
            for op in saved.get('after', []) if isinstance(saved.get('after'), list) else []:
                if not isinstance(op, dict):
                    continue
                val = op.get('value')
                raw = val[0] if isinstance(val, list) and len(val) == 2 else None
                if op.get('name') == GLOBAL and (isinstance(raw, str) or raw is None):
                    did = next((x.partition('=')[2].strip().upper() for x in (raw or '').split(';')
                                if x.partition('=')[0].strip().lower() == 'highperfadapter'), '')
                    targets.append('DirectX → ' + next((g['name'] for g in gpus if g.get('did') == did), did or '系统自动选择'))
                elif op.get('path') == GL and op.get('name') == 'DLL':
                    targets.append(f'OpenGL {op.get("view")} 位 → {raw or "默认"}')
                elif isinstance(op.get('name'), str) and op['name'].lower().endswith('.exe'):
                    targets.append('应用 → ' + op['name'])
            row['target'] = '\n'.join(dict.fromkeys(targets)) or 'Windows 图形设置 / 恢复操作'
            restore_plan(db, path)
            row['eligible'] = True
        except Exception as exc:
            row['error'] = str(exc)
        rows.append(row)
    return sorted(rows, key=lambda item: item['order'], reverse=True)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    widget.horizontalHeader().setStretchLastSection(True)
    widget.setWordWrap(False)
    widget.setMinimumHeight(120)
    return widget


def fill(widget, rows):
    widget.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(r, c, item)


class ManagementPage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.backups = []
        layout = QVBoxLayout(self)
        self.reboot_label = QLabel()
        self.reboot_label.setWordWrap(True)
        self.reboot_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.reboot_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        page = QWidget()
        content = QVBoxLayout(page)
        hint = QLabel('选中备份查看恢复资格。恢复前会重新检查当前用户、电脑、驱动和设置；建议从最新备份开始。')
        hint.setWordWrap(True)
        content.addWidget(hint)
        self.backup_table = table(['备份时间', '操作', '操作目标', '恢复资格'])
        self.backup_table.setColumnWidth(0, 155)
        self.backup_table.setColumnWidth(1, 110)
        self.backup_table.setColumnWidth(2, 220)
        content.addWidget(self.backup_table)
        self.backup_detail = QTextEdit()
        self.backup_detail.setReadOnly(True)
        self.backup_detail.setMinimumHeight(80)
        self.backup_detail.setMaximumHeight(150)
        content.addWidget(self.backup_detail)
        self.backup_table.itemSelectionChanged.connect(self.selection_changed)
        actions = QHBoxLayout()
        self.restore_button = QPushButton('预览并恢复选中备份')
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore_selected)
        actions.addWidget(self.restore_button)
        refresh_button = QPushButton('刷新备份')
        refresh_button.clicked.connect(self.refresh_backups)
        actions.addWidget(refresh_button)
        content.addLayout(actions)
        self.tabs.addTab(page, '备份管理')
        page = QWidget()
        content = QVBoxLayout(page)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        content.addWidget(self.log_view)
        actions = QHBoxLayout()
        for text, callback in [('刷新日志', self.refresh_logs), ('导出全部日志', self.export_logs)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        content.addLayout(actions)
        self.tabs.addTab(page, '操作日志')
        page = QWidget()
        content = QVBoxLayout(page)
        hint = QLabel('设备管理器状态和驱动信息。无问题代码不等于完整硬件诊断；不会启用、禁用或更新驱动。')
        hint.setWordWrap(True)
        content.addWidget(hint)
        self.health_table = table(['显卡', '驱动版本', '驱动日期', '当前设备状态'])
        self.health_table.setColumnWidth(0, 220)
        self.health_table.setColumnWidth(1, 150)
        content.addWidget(self.health_table)
        refresh_button = QPushButton('刷新设备健康信息')
        refresh_button.clicked.connect(self.refresh_health)
        content.addWidget(refresh_button)
        self.tabs.addTab(page, '显卡健康')

    def refresh(self):
        self.reboot_label.setText(reboot_status(self.owner.data_dir)['text'])
        self.refresh_backups()
        self.refresh_logs()
        self.refresh_health()

    def refresh_backups(self):
        selected = self.selected_backup()
        selected_path = selected['path'] if selected else None
        try:
            self.backups = backup_rows(self.owner.db, self.owner.backup_dir, self.owner.gpus)
            self.backup_table.blockSignals(True)
            fill(self.backup_table, [[b['time'], b['label'], b['target'],
                 '可恢复' if b['eligible'] else '不可恢复：' + b['error']] for b in self.backups])
            self.backup_table.blockSignals(False)
            if self.backups:
                index = next((i for i, b in enumerate(self.backups) if b['path'] == selected_path), 0)
                self.backup_table.selectRow(index)
            self.selection_changed()
        except Exception as exc:
            self.backup_table.blockSignals(False)
            self.backups = []
            self.backup_table.setRowCount(0)
            self.restore_button.setEnabled(False)
            self.backup_detail.setPlainText('备份列表读取失败：' + str(exc))

    def selected_backup(self):
        index = self.backup_table.currentRow()
        return self.backups[index] if 0 <= index < len(self.backups) else None

    def selection_changed(self):
        selected = self.selected_backup()
        self.restore_button.setEnabled(bool(selected and selected['eligible']))
        if not selected:
            self.backup_detail.setPlainText('尚无备份。应用设置后将自动生成。')
            return
        self.backup_detail.setPlainText(selected['path'] + '\n\n' + selected['target'] + '\n\n' +
            ('可恢复；点击按钮查看逐项修改预览后确认。' if selected['eligible'] else selected['error']))

    def restore_selected(self):
        selected = self.selected_backup()
        if not selected or not selected['eligible']:
            return
        try:
            if self.owner.refresh() is False:
                return
            plan = restore_plan(self.owner.db, selected['path'])
            self.owner.execute(plan, 'History-Restore')
        except Exception as exc:
            self.owner.error(exc)
        finally:
            self.refresh()

    def refresh_logs(self):
        position = self.log_view.verticalScrollBar().value()
        try:
            entries = read_logs(self.owner.data_dir)
            self.log_view.setPlainText('显示最近 500 条日志（导出包含全部记录）。\n\n' +
                ('\n\n'.join(f'{e["time"]}  {e["action"]}  [{e["result"]}]\n{e["details"]}'
                             for e in reversed(entries)) or '尚无操作记录。'))
        except Exception as exc:
            self.log_view.setPlainText('日志读取失败：' + str(exc))
        self.log_view.verticalScrollBar().setValue(position)

    def export_logs(self):
        filename, _ = QFileDialog.getSaveFileName(self, '导出操作日志', 'GPU操作日志.jsonl', 'JSONL 日志 (*.jsonl)')
        if not filename:
            return
        try:
            export_logs(self.owner.data_dir, filename)
        except Exception as exc:
            self.owner.error(exc)

    def refresh_health(self):
        try:
            rows = health_rows(self.owner.gpus, self.owner.db)
            fill(self.health_table, [[r['name'], r['version'], r['date'],
                 r['status'] + ('：' + r['error'] if r['error'] else '')] for r in rows])
        except Exception as exc:
            fill(self.health_table, [['读取失败', '', '', str(exc)]])
