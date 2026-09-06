"""Qt regressions using memory-only registry data; never apply real GPU settings."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from unittest.mock import Mock, patch

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication
import gpu_selector as ui
from gpu_core import dx_plan, gl_plan


class FakeRegistry:
    def __init__(self):
        self.data = {}

    def read(self, root, path, name, view=64):
        return self.data.get((root, path, name, view))

    def write(self, **kwargs):
        raise AssertionError('UI regression tests must not write registry values')


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.gpus = [dict(key='0000', name='GPU Zero', did='ZERO', present=True,
                          gl='zero64.dll', gl32='zero32.dll'),
                     dict(key='0001', name='GPU One', did='ONE', present=True,
                          gl='one64.dll', gl32='one32.dll')]
        self.db = FakeRegistry()
        for plan in (dx_plan(self.db, self.gpus[1]), gl_plan(self.gpus, self.gpus[1])):
            for op in plan:
                self.db.data[(op['root'], op['path'], op['name'], op['view'])] = (
                    tuple(op['value']) if op['value'] is not None else None)
        self.windows = []
        self.addCleanup(self.close_windows)
        self.registry = self.patched('Registry', return_value=self.db)
        self.adapters = self.patched('adapters', side_effect=lambda db: copy.deepcopy(self.gpus))
        self.report = self.patched('report', return_value='Current registry report')
        self.admin = self.patched('admin', return_value=False)
        self.critical = self.patched('QMessageBox.critical')
        self.question = self.patched('QMessageBox.question', return_value=ui.QMessageBox.No)
        self.apply = self.patched('apply_plan', side_effect=AssertionError('Unexpected registry apply'))
        self.window = self.new_window()

    def patched(self, target, **kwargs):
        item = patch('gpu_selector.' + target, **kwargs)
        result = item.start()
        self.addCleanup(item.stop)
        return result

    def new_window(self):
        window = ui.Window(data_dir=self.folder.name)
        window.timer.stop()
        self.windows.append(window)
        return window

    def close_windows(self):
        for window in self.windows:
            window.probe_process = None
            window.close()
            window.deleteLater()
        self.app.processEvents()

    def test_initial_selection_matches_current_dx_and_gl(self):
        self.assertEqual(self.window.dx_combo.currentData(), '0001')
        self.assertEqual(self.window.gl_combo.currentData(), '0001')

    def test_verification_snapshot_survives_timer_refresh(self):
        self.window.verify()
        snapshot = self.window.verification_text
        self.assertIn('所选配置与注册表完全匹配', snapshot)
        self.report.return_value = 'Updated registry report'
        self.window.refresh(rescan=False)
        self.assertEqual(self.window.verification_text, snapshot)
        self.assertIn(snapshot, self.window.status.toPlainText())
        self.assertIn('Updated registry report', self.window.status.toPlainText())

    def test_failed_refresh_stops_verify_and_disables_apply(self):
        self.window.verify()
        self.adapters.side_effect = PermissionError('device enumeration denied')
        with patch('gpu_selector.dx_matches') as dx_matches:
            self.window.verify()
            dx_matches.assert_not_called()
        self.assertFalse(self.window.read_ok)
        self.assertEqual(self.window.verification_text, '')
        self.assertNotIn('完全匹配', self.window.status.toPlainText())
        self.assertTrue(self.window.action_buttons)
        self.assertTrue(all(not b.isEnabled() for b in self.window.action_buttons))
        self.window.apply_dx()
        self.apply.assert_not_called()

    def test_refresh_recovery_clears_error_and_enables_actions(self):
        self.adapters.side_effect = PermissionError('device enumeration denied')
        self.window.refresh()
        self.adapters.side_effect = None
        self.adapters.return_value = self.gpus
        self.assertTrue(self.window.refresh())
        self.assertNotIn('读取失败', self.window.notice.text())
        self.assertTrue(all(b.isEnabled() for b in self.window.action_buttons))

    def test_initial_read_failure_also_clears_on_recovery(self):
        self.adapters.side_effect = PermissionError('initial enumeration denied')
        window = self.new_window()
        self.assertFalse(window.read_ok)
        self.adapters.side_effect = None
        self.adapters.return_value = self.gpus
        self.assertTrue(window.refresh())
        self.assertNotIn('读取失败', window.notice.text())

    def test_unchanged_refresh_keeps_selection_without_rebuilding_combo(self):
        self.window.dx_combo.setCurrentIndex(0)
        resets = QSignalSpy(self.window.dx_combo.model().modelReset)
        removals = QSignalSpy(self.window.dx_combo.model().rowsRemoved)
        self.assertTrue(self.window.refresh())
        self.assertEqual(self.window.dx_combo.currentData(), '0000')
        self.assertEqual(resets.count(), 0)
        self.assertEqual(removals.count(), 0)
        self.adapters.reset_mock()
        self.window.refresh(rescan=False)
        self.adapters.assert_not_called()

    def test_incomplete_or_disconnected_gl_device_is_not_selectable(self):
        self.gpus = [dict(self.gpus[0], gl32=''), dict(self.gpus[1], present=False)]
        self.window.refresh()
        self.assertEqual(self.window.gl_combo.count(), 0)
        self.window.apply_gl()
        self.question.assert_not_called()
        self.apply.assert_not_called()
        self.critical.assert_called_once()

    def test_missing_driver_file_is_rejected_before_uac(self):
        with patch('gpu_selector.gl_preflight', side_effect=ValueError('Missing ICD file')):
            self.window.apply_gl()
        self.question.assert_not_called()
        self.apply.assert_not_called()
        self.assertIn('Missing ICD file', str(self.critical.call_args))

    def test_report_export_keeps_snapshot_from_before_save_dialog(self):
        self.window.verify()
        snapshot = self.window.status.toPlainText()

        def show_dialog(*args):
            self.report.return_value = 'Changed while save dialog was open'
            self.window.refresh(rescan=False)
            return 'test-report.txt', 'Text'

        with patch('gpu_selector.QFileDialog.getSaveFileName', side_effect=show_dialog), \
                patch.object(ui.Path, 'write_text') as write:
            self.window.save_report()
        write.assert_called_once_with(snapshot, encoding='utf-8-sig')

    def prepare_probe(self):
        self.window.probe_process = Mock()
        self.window.probe_timeout = Mock()
        self.window.probe_temp = Mock()
        self.window.probe_timed_out = False
        self.window.probe_button.setEnabled(False)
        return self.window.probe_process

    def test_probe_failed_start_recovers_ui(self):
        process = self.prepare_probe()
        self.window.probe_error(ui.QProcess.FailedToStart)
        self.assertIn('实测未完成', self.window.probe_text)
        self.assertIsNone(self.window.probe_process)
        self.assertTrue(self.window.probe_button.isEnabled())
        process.deleteLater.assert_called_once()
        self.window.probe_temp.cleanup.assert_called_once()

    def test_probe_timeout_kills_only_probe_and_recovers_ui(self):
        process = self.prepare_probe()
        self.window.timeout_probe()
        process.kill.assert_called_once()
        self.window.finish_probe(-1, ui.QProcess.CrashExit)
        self.assertIn('超过 20 秒', self.window.probe_text)
        self.assertIsNone(self.window.probe_process)
        self.assertTrue(self.window.probe_button.isEnabled())
        self.apply.assert_not_called()

    def test_probe_crash_cannot_be_reported_as_success(self):
        self.prepare_probe()
        self.window.finish_probe(1, ui.QProcess.CrashExit)
        self.assertIn('未正常完成', self.window.probe_text)
        self.assertNotIn('渲染器：', self.window.probe_text)
        self.assertTrue(self.window.probe_button.isEnabled())

    def test_probe_completion_preserves_current_registry_read_failure(self):
        self.adapters.side_effect = PermissionError('device enumeration denied')
        self.window.refresh()
        self.prepare_probe()
        self.window.finish_probe(1, ui.QProcess.CrashExit)
        self.assertFalse(self.window.read_ok)
        self.assertIn('无法完整读取状态', self.window.status.toPlainText())
        self.assertIn('实测未完成', self.window.status.toPlainText())


if __name__ == '__main__':
    unittest.main(verbosity=2)
