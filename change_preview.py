"""Human-readable preview of a captured registry transaction."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QDialogButtonBox, QAbstractItemView, QHeaderView)


def capture_before(db, plan):
    result = []
    for op in plan:
        old = db.read(op['root'], op['path'], op['name'], op['view'])
        result.append(dict(op, value=list(old) if old is not None else None))
    return result


def format_value(item):
    if item is None:
        return '不存在（删除该值）'
    types = {1: '文本', 2: '可展开文本', 4: 'DWORD', 7: '多字符串'}
    return f'{item[0]}\n类型：{types.get(item[1], item[1])}'


class PreviewDialog(QDialog):
    def __init__(self, parent, title, before, after):
        super().__init__(parent)
        self.setWindowTitle('预览修改 · ' + title)
        area = parent.screen().availableGeometry()
        self.resize(min(1000, int(area.width() * .9)), min(650, int(area.height() * .85)))
        layout = QVBoxLayout(self)
        changed = sum(a['value'] != b['value'] for a, b in zip(before, after))
        summary = QLabel(f'{title} · {changed} 项变化\n应用前会自动备份，写入后逐项校验。OpenGL 修改或恢复后可能需要重启。')
        summary.setWordWrap(True)
        layout.addWidget(summary)
        table = QTableWidget(len(after), 4)
        table.setHorizontalHeaderLabels(['操作', '项目 / 位数', '当前值', '目标值'])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.verticalHeader().setDefaultSectionSize(84)
        for i, (old, new) in enumerate(zip(before, after)):
            action = '不变' if old['value'] == new['value'] else ('删除' if new['value'] is None else '新增' if old['value'] is None else '修改')
            target = f'{new["name"]}\n{new["root"]} · {new["view"]} 位'
            for column, text in enumerate((action, target, format_value(old['value']), format_value(new['value']))):
                item = QTableWidgetItem(text)
                item.setToolTip(new['root'] + '\\' + new['path'] + '\n' + text)
                table.setItem(i, column, item)
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('备份并应用这些修改')
        buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.table = table
