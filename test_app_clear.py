"""Clearing one selected application value; all registry writes stay in memory."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import winreg as reg

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

import app_preferences
import application_page
from gpu_core import PREF, GLOBAL, apply_plan, check_plan, restore_plan, validate_operations


class ClearRegistry:
    """Case-insensitive registry keys without normalizing their value-name paths."""
    def __init__(self):
        self.data = {}
        self.names = {}

    @staticmethod
    def key(root, path, name, view):
        return root, path.casefold(), name.casefold(), view

    def read(self, root, path, name, view=64):
        return self.data.get(self.key(root, path, name, view))

    def write(self, root, path, name, view, value):
        key = self.key(root, path, name, view)
        if value is None:
            self.data.pop(key, None)
            self.names.pop(key, None)
        else:
            self.data[key] = tuple(value)
            self.names[key] = name

    def put(self, name, raw='AppStatus=1;', kind=reg.REG_SZ):
        self.write('HKCU', PREF, name, 64, [raw, kind])

    def values(self, root, path, view=64):
        return [(self.names[key], raw, kind) for key, (raw, kind) in self.data.items()
                if key[0] == root and key[1] == path.casefold() and key[3] == view]


class ClearPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = ClearRegistry()

    def test_appstatus_only_value_is_fully_removed(self):
        path = r'C:\Old App\app.exe'
        self.db.put(path, 'AppStatus=1;')
        plan = app_preferences.clear_app_plan(self.db, path)
        self.assertEqual(plan, [dict(root='HKCU', path=PREF, name=path, view=64, value=None)])

    def test_clear_removes_gpu_hdr_and_all_other_parameters(self):
        path = r'C:\Games\app.exe'
        self.db.put(path, 'GpuPreference=2;SpecificAdapter=opaque;AutoHDREnable=1;AppStatus=1;')
        self.assertIsNone(app_preferences.clear_app_plan(self.db, path)[0]['value'])

    def test_preserves_exact_registry_value_name_including_path_spelling(self):
        for path in ('C:/Games/Chinese App.exe', r'C:\Games\.\app.exe', r'\\server\share\MixedCase.EXE'):
            with self.subTest(path=path):
                self.db.put(path)
                self.assertEqual(app_preferences.clear_app_plan(self.db, path)[0]['name'], path)

    def test_missing_executable_file_does_not_block_clear(self):
        path = r'Z:\Unavailable Volume\old.exe'
        self.db.put(path)
        with patch('app_preferences.Path.is_file', side_effect=AssertionError('Must not check executable existence')):
            self.assertIsNone(app_preferences.clear_app_plan(self.db, path)[0]['value'])

    def test_missing_registry_value_is_rejected(self):
        with self.assertRaises(ValueError):
            app_preferences.clear_app_plan(self.db, r'C:\not-recorded.exe')

    def test_illegal_targets_are_rejected_before_a_plan_is_returned(self):
        for path in ('', None, GLOBAL, 'relative.exe', r'C:relative.exe', r'\rooted.exe',
                     r'C:\file.dll', 'C:\\bad\nname.exe', r'C:\app.exe:stream.exe', '"C:\\app.exe"'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    app_preferences.clear_app_plan(self.db, path)

    def test_abnormal_registry_type_is_rejected(self):
        path = r'C:\app.exe'
        self.db.put(path, 1, reg.REG_DWORD)
        with self.assertRaises(ValueError):
            app_preferences.clear_app_plan(self.db, path)

    def test_exact_app_plan_still_validates_target_and_required_file(self):
        for path in ('relative.exe', '"C:\\Game.exe"', GLOBAL):
            with self.subTest(path=path), self.assertRaises(ValueError):
                app_preferences.app_plan(self.db, path, 2, exact_path=True)
        path = r'Z:\Unavailable\.\Game.exe'
        self.db.put(path, 'GpuPreference=2;AutoHDREnable=1;')
        with patch('app_preferences.Path.is_file', return_value=False):
            with self.assertRaises(ValueError):
                app_preferences.app_plan(self.db, path, 1, require_exists=True, exact_path=True)
            reset = app_preferences.app_plan(self.db, path, 0, exact_path=True)
        self.assertEqual(reset[0]['name'], path)
        self.assertEqual(reset[0]['value'], ['AutoHDREnable=1;', reg.REG_SZ])

    def test_transaction_backup_and_restore_only_affect_the_exact_path(self):
        target = 'C:/Games/MixedCase.exe'
        normal_spelling = r'C:\Games\MixedCase.exe'
        unrelated = r'C:\Other\other.exe'
        self.db.put(target, 'AppStatus=1;AutoHDREnable=0;GpuPreference=2;')
        self.db.put(normal_spelling, 'GpuPreference=1;')
        self.db.put(unrelated, 'AutoHDREnable=1;')
        self.db.put(GLOBAL, 'HighPerfAdapter=KEEP;')
        before = copy.deepcopy(self.db.data)
        plan = app_preferences.clear_app_plan(self.db, target)
        validate_operations(plan)
        with tempfile.TemporaryDirectory() as folder, patch('gpu_core.backup_identity', return_value={'user':'fake', 'machine':'fake', 'drivers':{}}):
            backup = apply_plan(self.db, plan, folder, '清除所选应用路径')
            self.assertIsNone(self.db.read('HKCU', PREF, target))
            self.assertEqual(self.db.read('HKCU', PREF, normal_spelling), ('GpuPreference=1;', reg.REG_SZ))
            self.assertEqual(self.db.read('HKCU', PREF, unrelated), ('AutoHDREnable=1;', reg.REG_SZ))
            self.assertFalse(check_plan(self.db, plan))
            saved = json.loads(backup.read_text(encoding='utf-8'))
            self.assertEqual(saved['before'][0]['name'], target)
            self.assertEqual(saved['before'][0]['value'][0], before[self.db.key('HKCU', PREF, target, 64)][0])
            self.assertIsNone(saved['after'][0]['value'])
            restoration = restore_plan(self.db, backup)
            apply_plan(self.db, restoration, folder, '恢复清除的应用路径')
        self.assertEqual(self.db.data, before)


class ClearSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.owner = QWidget()
        self.owner.db = ClearRegistry()
        self.owner.db.put(r'C:\A.exe')
        self.owner.db.put(r'C:\B.exe', 'AppStatus=2;AutoHDREnable=1;')
        self.owner.gpus = []
        self.owner.execute = Mock(return_value=False)
        self.page = application_page.ApplicationPage(self.owner)
        self.owner.refresh = Mock(side_effect=self.page.refresh)
        self.critical_patch = patch('application_page.QMessageBox.critical')
        self.critical = self.critical_patch.start()
        self.addCleanup(self.critical_patch.stop)
        self.addCleanup(self.owner.deleteLater)
        self.assertTrue(self.page.refresh())

    def select_path(self, path):
        for row, entry in enumerate(self.page.entries):
            if entry['path'] == path:
                self.page.table.selectRow(row)
                return
        self.fail('Path is not present in the table')

    def test_clearing_requires_selected_row_not_current_row_or_input(self):
        self.page.path_edit.setText(r'C:\A.exe')
        self.page.table.setCurrentCell(0, 0, QItemSelectionModel.NoUpdate)
        self.page.table.clearSelection()
        self.assertEqual(self.page.table.currentRow(), 0)
        self.assertFalse(self.page.clear_button.isEnabled())
        self.page.clear_selected()
        self.owner.execute.assert_not_called()

    def test_refresh_does_not_invent_selection_from_text_input(self):
        self.page.path_edit.setText(r'C:\B.exe')
        self.page.refresh()
        self.assertFalse(self.page.table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())

    def test_selected_row_enables_clear_and_captured_path_is_exact(self):
        path = r'C:\B.exe'
        self.select_path(path)
        self.assertTrue(self.page.clear_button.isEnabled())
        self.page.clear_selected()
        plan = self.owner.execute.call_args.args[0]
        self.assertEqual(plan[0]['name'], path)
        self.assertIsNone(plan[0]['value'])

    def test_button_clicked_signal_uses_selected_path_not_checked_argument(self):
        self.select_path(r'C:\B.exe')
        self.page.clear_button.click()
        self.owner.execute.assert_called_once()
        self.assertEqual(self.owner.execute.call_args.args[0][0]['name'], r'C:\B.exe')
        self.critical.assert_not_called()

    def test_disabled_clear_button_cannot_execute_without_selection(self):
        self.page.clear_button.click()
        self.owner.execute.assert_not_called()

    def test_manual_input_edit_invalidates_clear_selection(self):
        self.select_path(r'C:\A.exe')
        self.page.path_edit.selectAll()
        QTest.keyClicks(self.page.path_edit, r'C:\B.exe')
        self.assertFalse(self.page.table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())
        self.page.clear_selected()
        self.owner.execute.assert_not_called()

    def test_browsing_new_exe_invalidates_previous_clear_selection(self):
        self.select_path(r'C:\A.exe')
        with patch('application_page.QFileDialog.getOpenFileName', return_value=('C:/B.exe', '')):
            self.page.browse()
        self.assertFalse(self.page.table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())

    def test_refresh_reordering_cannot_clear_the_new_row_at_old_index(self):
        self.select_path(r'C:\B.exe')
        self.assertEqual(self.page.table.currentRow(), 1)
        def refresh_with_new_entry():
            self.owner.db.put(r'C:\A0.exe')
            return self.page.refresh()
        self.owner.refresh.side_effect = refresh_with_new_entry
        self.page.clear_selected()
        plan = self.owner.execute.call_args.args[0]
        self.assertEqual(plan[0]['name'], r'C:\B.exe')
        self.assertNotEqual(plan[0]['name'], self.page.entries[1]['path'])

    def test_disappeared_selected_record_does_not_clear_another_row(self):
        self.select_path(r'C:\A.exe')
        def refresh_without_target():
            self.owner.db.write('HKCU', PREF, r'C:\A.exe', 64, None)
            return self.page.refresh()
        self.owner.refresh.side_effect = refresh_without_target
        self.page.clear_selected()
        self.owner.execute.assert_not_called()
        self.assertIsNotNone(self.owner.db.read('HKCU', PREF, r'C:\B.exe'))

    def test_external_deletion_of_last_selected_row_leaves_selection_empty(self):
        self.select_path(r'C:\B.exe')
        self.owner.db.write('HKCU', PREF, r'C:\B.exe', 64, None)
        self.page.refresh()
        self.assertFalse(self.page.table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())

    def test_cancel_does_not_report_clear_success_or_change_any_value(self):
        self.select_path(r'C:\B.exe')
        self.page.feedback.setText('Previous status')
        before = copy.deepcopy(self.owner.db.data)
        self.page.clear_selected()
        self.owner.execute.assert_called_once()
        self.assertEqual(self.page.feedback.text(), 'Previous status')
        self.assertEqual(self.owner.db.data, before)

    def test_success_clears_complete_record_and_refreshes_selection(self):
        target = r'C:\B.exe'
        self.select_path(target)
        def execute_in_memory(plan, label):
            validate_operations(plan)
            for op in plan:
                self.owner.db.write(**op)
            return True
        self.owner.execute.side_effect = execute_in_memory
        self.page.clear_selected()
        self.assertIsNone(self.owner.db.read('HKCU', PREF, target))
        self.assertEqual(len(self.page.entries), 1)
        self.assertEqual(self.page.entries[0]['path'], r'C:\A.exe')
        self.assertFalse(self.page.table.selectionModel().selectedRows())
        self.assertFalse(self.page.clear_button.isEnabled())
        self.assertIn(target, self.page.feedback.text())

    def test_failed_owner_refresh_blocks_clear(self):
        self.select_path(r'C:\A.exe')
        self.owner.refresh.side_effect = None
        self.owner.refresh.return_value = False
        self.page.clear_selected()
        self.owner.execute.assert_not_called()

    def add_alias_records(self, path=r'C:\Games\.\Game.exe'):
        canonical = r'C:\Games\Game.exe'
        self.owner.db.put(path, 'GpuPreference=2;AutoHDREnable=1;')
        self.owner.db.put(canonical, 'GpuPreference=1;AutoHDREnable=0;')
        self.page.refresh()
        self.select_path(path)
        return path, canonical

    def test_selected_alias_reads_its_own_preference(self):
        for path in (r'C:\Games\.\Game.exe', 'C:/Games/Game.exe'):
            with self.subTest(path=path):
                self.add_alias_records(path)
                self.assertEqual(self.page.preference.currentData(), 2)
                self.assertIn('高性能', self.page.feedback.text())

    def test_verify_selected_alias_does_not_verify_the_normalized_value(self):
        self.add_alias_records()
        self.page.preference.setCurrentIndex(self.page.preference.findData(1))
        self.page.verify()
        self.assertIn('不一致', self.page.feedback.text())
        self.page.preference.setCurrentIndex(self.page.preference.findData(2))
        self.page.verify()
        self.assertIn('与注册表一致', self.page.feedback.text())

    def test_apply_selected_alias_preserves_its_hdr_and_leaves_other_value(self):
        target, canonical = self.add_alias_records()
        def execute_in_memory(plan, label):
            validate_operations(plan)
            for op in plan:
                self.owner.db.write(**op)
            return True
        self.owner.execute.side_effect = execute_in_memory
        self.page.preference.setCurrentIndex(self.page.preference.findData(1))
        with patch('app_preferences.Path.is_file', return_value=True):
            self.page.apply()
        self.assertEqual(self.owner.db.read('HKCU', PREF, target),
                         ('AutoHDREnable=1;GpuPreference=1;', reg.REG_SZ))
        self.assertEqual(self.owner.db.read('HKCU', PREF, canonical),
                         ('GpuPreference=1;AutoHDREnable=0;', reg.REG_SZ))
        self.assertEqual(self.owner.execute.call_args.args[0][0]['name'], target)
        self.critical.assert_not_called()

    def test_reset_selected_missing_alias_captures_target_before_refresh(self):
        target, canonical = self.add_alias_records()
        def refresh_and_change_input():
            self.owner.db.put(r'C:\First.exe')
            self.page.refresh()
            self.select_path(canonical)
            return True
        self.owner.refresh.side_effect = refresh_and_change_input
        with patch('app_preferences.Path.is_file', return_value=False):
            self.page.reset()
        op = self.owner.execute.call_args.args[0][0]
        self.assertEqual(op['name'], target)
        self.assertEqual(op['value'], ['AutoHDREnable=1;', reg.REG_SZ])
        self.critical.assert_not_called()

    def test_manual_input_normalizes_after_alias_selection_is_cleared(self):
        target, canonical = self.add_alias_records()
        self.page.path_edit.selectAll()
        QTest.keyClicks(self.page.path_edit, target)
        self.assertIsNone(self.page.selected_path())
        self.page.preference.setCurrentIndex(self.page.preference.findData(1))
        self.page.verify()
        self.assertIn('与注册表一致', self.page.feedback.text())
        self.page.reset()
        op = self.owner.execute.call_args.args[0][0]
        self.assertEqual(op['name'], canonical)
        self.assertEqual(op['value'], ['AutoHDREnable=0;', reg.REG_SZ])

    def test_changed_input_without_matching_selection_does_not_use_exact_mode(self):
        self.add_alias_records()
        self.page.path_edit.setText('C:/Games/Game.exe')
        self.page.reset()
        op = self.owner.execute.call_args.args[0][0]
        self.assertEqual(op['name'], r'C:\Games\Game.exe')
        self.assertEqual(op['value'], ['AutoHDREnable=0;', reg.REG_SZ])


if __name__ == '__main__':
    unittest.main()
