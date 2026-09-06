"""Backup cleanup UI tests; recycle operations only remove our temporary fixtures."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

import management_page


class CleanupOwner(QWidget):
    def __init__(self, folder):
        super().__init__()
        self.data_dir = folder
        self.backup_dir = folder / 'backups'
        self.backup_dir.mkdir()
        self.db = Mock()
        self.db.write.side_effect = AssertionError('Registry mutation is forbidden')
        self.gpus = []
        self.execute = Mock(side_effect=AssertionError('GPU transaction must not run during backup cleanup'))
        self.refresh = Mock(return_value=True)
        self.error = Mock()
        self.log = Mock()
        self.busy = False
        self.last_backup = None
        self.last_plan = None
        self.restore_button = QPushButton()
        self.restore_button.setEnabled(False)


class BackupCleanupUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = CleanupOwner(Path(self.temp.name))
        self.page = management_page.ManagementPage(self.owner)
        self.addCleanup(self.owner.close)
        self.addCleanup(self.page.deleteLater)
        self.validation_patch = patch('management_page.restore_plan', return_value=['validated'])
        self.validation = self.validation_patch.start()
        self.addCleanup(self.validation_patch.stop)
        self.trash_patch = patch('management_page.trash_backup', side_effect=self.recycle_temporary_fixture)
        self.trash = self.trash_patch.start()
        self.addCleanup(self.trash_patch.stop)
        self.dialog_patch = patch('management_page.QMessageBox.exec', return_value=QMessageBox.Yes)
        self.dialog = self.dialog_patch.start()
        self.addCleanup(self.dialog_patch.stop)
        self.a = self.backup('a.json', 100)
        self.b = self.backup('b.json', 200)
        self.page.refresh_backups()

    def backup(self, name, stamp):
        path = self.owner.backup_dir / name
        path.write_text(json.dumps({'label': name, 'after': []}), encoding='utf-8')
        os.utime(path, (stamp, stamp))
        return path

    def recycle_temporary_fixture(self, directory, snapshot):
        target = Path(snapshot['path'])
        self.assertEqual(Path(directory).resolve(), self.owner.backup_dir.resolve())
        self.assertEqual(target.resolve().parent, self.owner.backup_dir.resolve())
        target.unlink()  # Only the temporary fixture; the Windows recycle bin is never called.

    def select(self, path):
        for row, item in enumerate(self.page.backups):
            if Path(item['path']) == path:
                self.page.backup_table.selectRow(row)
                return
        self.fail('Requested fixture is missing from the backup list')

    def assert_no_success(self):
        self.assertFalse(any(call.args[:2] == ('清除备份', '成功') for call in self.owner.log.call_args_list))

    def test_initial_list_does_not_select_a_backup_for_cleanup_or_restore(self):
        self.assertEqual(len(self.page.backups), 2)
        self.assertFalse(self.page.backup_table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())
        self.assertFalse(self.page.restore_button.isEnabled())
        self.assertNotIn('尚无备份', self.page.backup_detail.toPlainText())

    def test_current_row_without_actual_selection_cannot_clear(self):
        self.page.backup_table.setCurrentCell(0, 0, QItemSelectionModel.NoUpdate)
        self.page.backup_table.clearSelection()
        self.assertEqual(self.page.backup_table.currentRow(), 0)
        self.page.clear_selected()
        self.dialog.assert_not_called()
        self.trash.assert_not_called()

    def test_default_and_escape_confirmation_are_no_and_text_is_plain(self):
        self.select(self.a)
        captured = []
        def inspect_dialog(dialog):
            captured.append(dialog)
            self.assertEqual(dialog.standardButtons(), QMessageBox.Yes | QMessageBox.No)
            self.assertIs(dialog.defaultButton(), dialog.button(QMessageBox.No))
            self.assertIs(dialog.escapeButton(), dialog.button(QMessageBox.No))
            self.assertEqual(dialog.textFormat(), Qt.PlainText)
            self.assertIn('回收站', dialog.button(QMessageBox.Yes).text())
            self.assertTrue(self.owner.busy)
            return QMessageBox.No
        with patch('management_page.QMessageBox.exec', new=inspect_dialog):
            self.page.clear_selected()
        self.assertEqual(len(captured), 1)
        self.trash.assert_not_called()
        self.assertFalse(self.owner.busy)

    def test_cancel_does_not_remove_file_or_record_success(self):
        self.select(self.a)
        self.dialog.return_value = QMessageBox.No
        self.page.clear_selected()
        self.trash.assert_not_called()
        self.assertTrue(self.a.exists())
        self.assertTrue(self.b.exists())
        self.assert_no_success()
        self.assertFalse(self.owner.busy)

    def test_clicked_signal_clears_only_selected_backup_and_never_registry(self):
        self.select(self.a)
        self.assertTrue(self.page.clear_button.isEnabled())
        self.page.clear_button.click()
        self.trash.assert_called_once()
        self.assertEqual(Path(self.trash.call_args.args[1]['path']), self.a)
        self.assertFalse(self.a.exists())
        self.assertTrue(self.b.exists())
        self.owner.db.write.assert_not_called()
        self.owner.execute.assert_not_called()
        self.assertFalse(self.owner.busy)

    def test_confirmation_selection_and_refresh_changes_cannot_change_captured_target(self):
        self.select(self.a)
        def change_selection():
            self.select(self.b)
            self.backup('newest.json', 300)
            self.page.refresh_backups()
            return QMessageBox.Yes
        self.dialog.side_effect = change_selection
        self.page.clear_selected()
        self.assertEqual(Path(self.trash.call_args.args[1]['path']), self.a)
        self.assertFalse(self.a.exists())
        self.assertTrue(self.b.exists())
        self.assertTrue((self.owner.backup_dir / 'newest.json').exists())

    def test_refresh_after_selected_last_row_disappears_leaves_empty_selection(self):
        self.select(self.a)
        self.assertEqual(self.page.backup_table.currentRow(), 1)
        self.a.unlink()
        self.page.refresh_backups()
        self.assertEqual(len(self.page.backups), 1)
        self.assertFalse(self.page.backup_table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())
        self.assertFalse(self.page.restore_button.isEnabled())

    def test_success_does_not_auto_select_a_surviving_backup(self):
        self.select(self.a)
        self.page.clear_selected()
        self.assertFalse(self.page.backup_table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())
        self.assertIn('回收站', self.page.backup_detail.toPlainText())
        self.assertTrue(any(call.args[:2] == ('清除备份', '成功') for call in self.owner.log.call_args_list))

    def test_corrupt_json_is_still_available_for_manual_cleanup(self):
        self.a.write_text('{broken', encoding='utf-8')
        self.page.refresh_backups()
        self.select(self.a)
        self.assertFalse(self.page.restore_button.isEnabled())
        self.assertTrue(self.page.clear_button.isEnabled())
        self.page.clear_selected()
        self.assertFalse(self.a.exists())
        self.assertTrue(self.b.exists())

    def test_currently_unrestorable_backup_can_be_cleaned(self):
        self.validation.side_effect = ValueError('Current settings no longer match')
        self.page.refresh_backups()
        self.select(self.b)
        self.assertFalse(self.page.restore_button.isEnabled())
        self.assertTrue(self.page.clear_button.isEnabled())
        self.page.clear_selected()
        self.assertFalse(self.b.exists())
        self.assertTrue(self.a.exists())

    def test_cleanup_failure_keeps_file_and_latest_restore_state(self):
        plan = ['last plan']
        self.owner.last_backup = self.a
        self.owner.last_plan = plan
        self.owner.restore_button.setEnabled(True)
        self.select(self.a)
        self.trash.side_effect = OSError('Simulated recycle-bin failure')
        self.page.clear_selected()
        self.assertTrue(self.a.exists())
        self.assertEqual(self.owner.last_backup, self.a)
        self.assertIs(self.owner.last_plan, plan)
        self.assertTrue(self.owner.restore_button.isEnabled())
        self.owner.error.assert_called_once()
        self.assert_no_success()
        self.assertFalse(self.owner.busy)

    def test_success_clearing_latest_disables_recent_restore_and_clears_plan(self):
        self.owner.last_backup = self.b
        self.owner.last_plan = ['last plan']
        self.owner.restore_button.setEnabled(True)
        self.select(self.b)
        self.page.clear_selected()
        self.assertIsNone(getattr(self.owner, 'last_backup', None))
        self.assertIsNone(self.owner.last_plan)
        self.assertFalse(self.owner.restore_button.isEnabled())

    def test_clearing_other_backup_preserves_latest_restore_state(self):
        plan = ['last plan']
        self.owner.last_backup = self.b
        self.owner.last_plan = plan
        self.owner.restore_button.setEnabled(True)
        self.select(self.a)
        self.page.clear_selected()
        self.assertEqual(self.owner.last_backup, self.b)
        self.assertIs(self.owner.last_plan, plan)
        self.assertTrue(self.owner.restore_button.isEnabled())

    def test_existing_busy_transaction_blocks_cleanup(self):
        self.select(self.a)
        self.owner.busy = True
        self.page.clear_selected()
        self.dialog.assert_not_called()
        self.trash.assert_not_called()
        self.assertTrue(self.owner.busy)

    def test_removed_target_before_snapshot_does_not_open_confirmation(self):
        self.select(self.a)
        self.a.unlink()
        self.page.clear_selected()
        self.dialog.assert_not_called()
        self.trash.assert_not_called()
        self.assertTrue(self.b.exists())
        self.assertFalse(self.owner.busy)


if __name__ == '__main__':
    unittest.main()
