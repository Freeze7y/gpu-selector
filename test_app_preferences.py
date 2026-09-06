"""Application preferences and scheme regressions; registry writes are mocked."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import winreg as reg

from PySide6.QtWidgets import QApplication, QWidget

import application_page
import profiles
from app_preferences import (app_plan, list_app_preferences, normalize_exe,
                             preference_state, preference_string, valid_exe_path)
from gpu_core import CLASS, PREF, GLOBAL, DX


class MemoryRegistry:
    def __init__(self):
        self.data = {}

    def read(self, root, path, name, view=64):
        key = (root, path.casefold(), name.casefold(), view)
        return self.data.get(key)

    def put(self, name, raw, kind=reg.REG_SZ, root='HKCU', path=PREF):
        self.data[(root, path.casefold(), name.casefold(), 64)] = (raw, kind)

    def values(self, root, path, view=64):
        return [(name, data, kind) for (rt, key, name, bits), (data, kind) in self.data.items()
                if rt == root and key == path.casefold() and bits == view]

    def write(self, **kwargs):
        raise AssertionError('These tests must never write registry values')


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryRegistry()

    def test_modes_preserve_unrelated_values_and_collapse_duplicate_gpu_values(self):
        result = preference_string('AutoHDREnable=1;GpuPreference=1; Other = x ;gpupreference=2;', 2)
        self.assertEqual(result, 'AutoHDREnable=1; Other = x ;GpuPreference=2;')

    def test_reset_removes_only_gpu_preference_fields(self):
        self.assertEqual(preference_string('GpuPreference=3;SpecificAdapter=opaque;AutoHDREnable=1;', 0), 'AutoHDREnable=1;')

    def test_empty_reset_deletes_value_instead_of_empty_registry_string(self):
        self.assertIsNone(preference_string('GpuPreference=2;', 0))

    def test_no_preferences_reports_automatic(self):
        for text in (None, '', 'AutoHDREnable=1;', 'GpuPreference=0;'):
            self.assertEqual(preference_state(text)[0], 0)

    def test_unknown_duplicate_and_custom_preferences_do_not_report_automatic(self):
        for text in ('GpuPreference=9;', 'GpuPreference=1;GpuPreference=2;', 'SpecificAdapter=123;', 'GpuPreference=3;', 'GpuPreference;', 'SpecificAdapter;'):
            self.assertIsNone(preference_state(text)[0])

    def test_invalid_registry_type_is_reported_and_rejected_on_write(self):
        self.assertIsNone(preference_state('GpuPreference=2;', reg.REG_EXPAND_SZ)[0])
        self.db.put(r'C:\app.exe', 2, reg.REG_DWORD)
        with self.assertRaises(ValueError):
            app_plan(self.db, r'C:\app.exe', 1)

    def test_illegal_paths_cannot_be_registry_targets(self):
        for path in ('app.exe', r'\app.exe', 'DirectXUserGlobalSettings', r'C:app.exe', r'C:\app.dll', 'C:\\app.exe\0'):
            self.assertFalse(valid_exe_path(path), path)
        self.assertTrue(valid_exe_path(r'C:\游戏\程序.exe'))
        self.assertTrue(valid_exe_path(r'\\server\share\app.exe'))

    def test_normalized_quoted_path(self):
        self.assertEqual(normalize_exe('"C:/App Dir/test.exe"'), r'C:\App Dir\test.exe')

    def test_preference_rejects_bool_and_unknown_mode(self):
        for value in (True, None, '2', 3):
            with self.assertRaises(ValueError):
                preference_string(None, value)

    def test_plan_is_scoped_and_preserves_current_other_settings(self):
        self.db.put(r'C:\app.exe', 'AutoHDREnable=1;GpuPreference=1;')
        plan = app_plan(self.db, r'C:\app.exe', 2)
        self.assertEqual(plan, [dict(root='HKCU', path=PREF, name=r'C:\app.exe', view=64,
                                     value=['AutoHDREnable=1;GpuPreference=2;', reg.REG_SZ])])

    def test_missing_application_is_rejected_when_setting_but_can_reset(self):
        with patch('app_preferences.Path.is_file', return_value=False):
            with self.assertRaises(ValueError):
                app_plan(self.db, r'C:\gone.exe', 2, require_exists=True)
        self.assertIsNone(app_plan(self.db, r'C:\gone.exe', 0)[0]['value'])

    def test_list_excludes_global_and_packaged_apps_and_reports_invalid_exe_entry(self):
        self.db.put(GLOBAL, 'HighPerfAdapter=foo;')
        self.db.put('Package.App_123', 'GpuPreference=2;')
        self.db.put(r'C:\A.exe', 'GpuPreference=1;')
        self.db.put(r'C:\B.exe', 2, reg.REG_DWORD)
        entries = list_app_preferences(self.db)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['preference'], 1)
        self.assertIsNone(entries[1]['preference'])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryRegistry()
        self.gpus = [dict(key='0000', did='10DE&1234&ABCD1234', name='GPU', present=True, gl='gpu64.dll', gl32='gpu32.dll')]
        self.db.put('DriverVersion', '1.0', root='HKLM', path=CLASS + r'\0000')
        identity = patch('profiles.backup_identity', return_value=dict(user='test', machine='test', drivers={}))
        identity.start()
        self.addCleanup(identity.stop)
        exists = patch('app_preferences.Path.is_file', return_value=True)
        exists.start()
        self.addCleanup(exists.stop)

    def snapshot(self, **kwargs):
        return profiles.profile_snapshot(self.db, self.gpus, '游戏', dx_key='0000', **kwargs)

    def test_profile_roundtrip_and_duplicate_names_do_not_overwrite(self):
        data = self.snapshot()
        with tempfile.TemporaryDirectory() as folder:
            first = profiles.save_profile(folder, data)
            second = profiles.save_profile(folder, data)
            self.assertNotEqual(first, second)
            self.assertEqual(profiles.read_profile(first), data)

    def test_profile_rejects_driver_changes(self):
        data = self.snapshot()
        self.db.put('DriverVersion', '2.0', root='HKLM', path=CLASS + r'\0000')
        with self.assertRaisesRegex(ValueError, '驱动'):
            profiles.profile_plan(self.db, self.gpus, data)

    def test_profile_rejects_same_slot_with_new_hardware(self):
        data = self.snapshot()
        self.gpus[0]['did'] = 'OTHER'
        with self.assertRaises(ValueError):
            profiles.profile_plan(self.db, self.gpus, data)

    def test_profile_rejects_machine_user_change(self):
        data = self.snapshot()
        with patch('profiles.backup_identity', return_value=dict(user='other', machine='test', drivers={})):
            with self.assertRaises(ValueError):
                profiles.profile_plan(self.db, self.gpus, data)

    def test_profile_preserves_live_non_gpu_fields_when_applied(self):
        self.db.put(r'C:\app.exe', 'GpuPreference=2;AutoHDREnable=1;')
        data = self.snapshot()
        self.db.put(r'C:\app.exe', 'GpuPreference=1;AutoHDREnable=0;SwapEffectUpgradeEnable=1;')
        plan = profiles.profile_plan(self.db, self.gpus, data)
        self.assertEqual(plan[-1]['value'][0], 'AutoHDREnable=0;SwapEffectUpgradeEnable=1;GpuPreference=2;')

    def test_profile_leaves_unlisted_application_untouched(self):
        data = self.snapshot()
        self.db.put(r'C:\new.exe', 'GpuPreference=1;')
        self.assertEqual(len(profiles.profile_plan(self.db, self.gpus, data)), 1)

    def test_auto_global_plan_preserves_live_other_fields(self):
        self.db.put(GLOBAL, 'HighPerfAdapter=X;AutoHDREnable=1;')
        data = profiles.profile_snapshot(self.db, self.gpus, '自动', dx_key='auto')
        self.assertEqual(profiles.profile_plan(self.db, self.gpus, data)[0]['value'][0], 'AutoHDREnable=1;')

    def test_gl_and_dx_and_apps_produce_single_plan(self):
        self.db.put(r'C:\app.exe', 'GpuPreference=2;')
        data = self.snapshot(gl_key='0000')
        with patch('profiles.gl_preflight') as preflight:
            plan = profiles.profile_plan(self.db, self.gpus, data)
        preflight.assert_called_once_with(self.gpus[0])
        self.assertEqual(len(plan), 14)
        self.assertEqual(plan[-1]['name'], r'c:\app.exe')

    def test_missing_gl_driver_blocks_whole_combined_plan(self):
        data = self.snapshot(gl_key='0000')
        with patch('profiles.gl_preflight', side_effect=ValueError('driver missing')):
            with self.assertRaisesRegex(ValueError, 'driver missing'):
                profiles.profile_plan(self.db, self.gpus, data)

    def test_unknown_application_preference_requires_exclusion(self):
        self.db.put(r'C:\app.exe', 'GpuPreference=3;SpecificAdapter=opaque;')
        with self.assertRaisesRegex(ValueError, '自定义'):
            self.snapshot()
        self.assertEqual(self.snapshot(include_apps=False)['apps'], [])

    def test_empty_scheme_rejected(self):
        with self.assertRaises(ValueError):
            profiles.profile_snapshot(self.db, self.gpus, '空白')

    def test_invalid_application_targets_and_duplicate_case_paths_rejected(self):
        data = self.snapshot()
        for apps in ([dict(path=GLOBAL, preference=2)],
                     [dict(path=r'C:\app.exe', preference=2), dict(path=r'c:\APP.exe', preference=1)],
                     [dict(path=r'C:\app.exe', preference=7)]):
            data['apps'] = apps
            with self.assertRaises(ValueError):
                profiles.profile_plan(self.db, self.gpus, data)

    def test_disconnected_gpu_blocks_scheme(self):
        data = self.snapshot()
        self.gpus[0]['present'] = False
        with self.assertRaises(ValueError):
            profiles.profile_plan(self.db, self.gpus, data)

    def test_profile_list_limit_is_validated(self):
        data = self.snapshot()
        data['apps'] = [dict(path=r'C:\app.exe', preference=2)] * 451
        with self.assertRaises(ValueError):
            profiles.profile_plan(self.db, self.gpus, data)


class AppUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.owner = QWidget()
        self.owner.data_dir = Path(self.temp.name)
        self.owner.db = MemoryRegistry()
        self.owner.gpus = []
        self.owner.execute = Mock(return_value=True)
        self.owner.refresh = Mock(return_value=True)
        self.page = application_page.ApplicationPage(self.owner)
        self.page.path_edit.setText(r'C:\app.exe')
        self.addCleanup(self.owner.deleteLater)
        critical = patch('application_page.QMessageBox.critical')
        self.critical = critical.start()
        self.addCleanup(critical.stop)

    def test_verify_accepts_explicit_auto_without_rewriting_registry(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=0;AutoHDREnable=1;')
        self.page.verify()
        self.assertIn('与注册表一致', self.page.feedback.text())
        self.owner.execute.assert_not_called()

    def test_load_current_normalizes_file_dialog_forward_slashes(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=2;')
        self.page.load_current('C:/app.exe')
        self.assertEqual(self.page.preference.currentData(), 2)
        self.assertIn('高性能', self.page.feedback.text())

    def test_browse_stores_normalized_path_and_reads_existing_preference(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=1;')
        with patch('application_page.QFileDialog.getOpenFileName', return_value=('C:/app.exe', '')):
            self.page.browse()
        self.assertEqual(self.page.path_edit.text(), r'C:\app.exe')
        self.assertEqual(self.page.preference.currentData(), 1)

    def test_verify_unknown_preference_never_claims_success(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=3;')
        self.page.preference.setCurrentIndex(-1)
        self.page.verify()
        self.assertIn('不一致', self.page.feedback.text())

    def test_reset_uses_owner_preview_transaction_and_keeps_non_gpu_fields(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=2;AutoHDREnable=1;')
        self.page.reset()
        plan, label = self.owner.execute.call_args.args
        self.assertEqual(plan[0]['value'][0], 'AutoHDREnable=1;')

    def test_cancelled_execution_does_not_claim_applied(self):
        self.owner.execute.return_value = False
        self.page.reset()
        self.assertNotIn('已应用', self.page.feedback.text())

    def test_failed_refresh_blocks_all_modification(self):
        self.owner.refresh.return_value = False
        self.page.reset()
        self.owner.execute.assert_not_called()
        self.critical.assert_called_once()

    def test_refresh_does_not_replace_user_pending_preference(self):
        self.owner.db.put(r'C:\app.exe', 'GpuPreference=1;')
        self.page.preference.setCurrentIndex(self.page.preference.findData(2))
        self.page.refresh()
        self.assertEqual(self.page.preference.currentData(), 2)

    def test_enumeration_failure_disables_app_actions(self):
        self.owner.db.values = Mock(side_effect=PermissionError('denied'))
        self.assertFalse(self.page.refresh())
        self.assertFalse(self.page.apply_button.isEnabled())
        self.assertIn('读取失败', self.page.feedback.text())

    def test_profile_page_handles_corrupt_scheme_and_keeps_file(self):
        directory = self.owner.data_dir / 'profiles'
        directory.mkdir()
        bad = directory / 'bad.json'
        bad.write_text('{bad')
        page = profiles.ProfilesPage(self.owner)
        self.assertTrue(page.refresh())
        self.assertIn('无法读取', page.list.item(0).text())
        self.assertTrue(bad.exists())

    def test_profile_page_save_and_apply_uses_one_preview_transaction(self):
        page = profiles.ProfilesPage(self.owner)
        page.refresh()
        page.name_edit.setText('办公')
        page.dx_combo.setCurrentIndex(page.dx_combo.findData('auto'))
        page.save()
        self.assertEqual(page.list.count(), 1)
        page.apply()
        self.owner.execute.assert_called_once()
        plan, label = self.owner.execute.call_args.args
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['name'], GLOBAL)

    def test_profile_page_cancel_does_not_report_applied(self):
        page = profiles.ProfilesPage(self.owner)
        page.refresh()
        page.name_edit.setText('办公')
        page.dx_combo.setCurrentIndex(page.dx_combo.findData('auto'))
        page.save()
        self.owner.execute.return_value = False
        page.apply()
        self.assertNotIn('方案已应用', page.details.toPlainText())

    def test_profile_save_detects_slot_reused_during_refresh(self):
        self.owner.gpus = [dict(key='0000', name='Before GPU', did='BEFORE', gl='', gl32='', present=True)]
        page = profiles.ProfilesPage(self.owner)
        page.refresh()
        page.name_edit.setText('游戏')
        page.dx_combo.setCurrentIndex(page.dx_combo.findData('0000'))
        def change_gpu():
            self.owner.gpus[0]['did'] = 'AFTER'
            return True
        self.owner.refresh.side_effect = change_gpu
        page.save()
        self.critical.assert_called_once()
        self.assertEqual(page.list.count(), 0)


if __name__ == '__main__':
    unittest.main()
