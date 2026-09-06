"""Update consent, threading and shutdown regressions; no network or installation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import ANY, Mock, patch

from PySide6.QtCore import QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QWidget

from app_version import VERSION
import update_ui
from update_service import UpdateInfo
from ui_preferences import load_preferences


class UpdateOwner(QMainWindow):
    def __init__(self, folder):
        super().__init__()
        self.preferences = {'theme': 'dark', 'font_size': 10}
        self.data_dir = folder
        self.busy = False
        self.probe_process = None
        self.log = Mock()
        self.close = Mock(return_value=True)
        self.setCentralWidget(QWidget())


class UpdateUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.owner = UpdateOwner(self.folder)
        self.check = self.mock('check_for_update', return_value=None)
        self.download = self.mock('download_update', return_value=self.folder / 'update.exe')
        self.install = self.mock('install_update', return_value=None)
        self.frozen = self.mock('packaged', return_value=True)
        self.dialog = self.mock('QMessageBox.exec', return_value=QMessageBox.No)
        self.panel = update_ui.UpdatePanel(self.owner)
        self.gates = []
        self.info = UpdateInfo('9.0.0', 'v9.0.0',
            'https://github.com/Freeze7y/gpu-selector/releases/tag/v9.0.0',
            'GPUSelector-v9.0.0-windows-x64.exe',
            'https://github.com/Freeze7y/gpu-selector/releases/download/v9.0.0/GPUSelector-v9.0.0-windows-x64.exe',
            1024, 'a' * 64)

    def mock(self, name, **kwargs):
        context = patch('update_ui.' + name, **kwargs)
        result = context.start()
        self.addCleanup(context.stop)
        return result

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        if self.panel.thread is not None:
            self.panel.prepare_close()
            self.wait_idle()
        self.panel.deleteLater()
        self.owner.deleteLater()
        self.qt.processEvents()
        self.temp.cleanup()

    def gate(self):
        gate = threading.Event()
        self.gates.append(gate)
        return gate

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(condition(), 'Timed out waiting for mocked update worker')

    def wait_idle(self):
        self.wait_for(lambda: self.panel.thread is None)
        self.qt.processEvents()

    def test_constructor_never_checks_prompts_or_writes_preferences(self):
        self.qt.processEvents()
        self.check.assert_not_called()
        self.dialog.assert_not_called()
        self.assertFalse((self.folder / 'ui.json').exists())

    def test_first_start_no_is_saved_and_does_not_check(self):
        self.panel.startup()
        self.assertFalse(load_preferences(self.folder)[update_ui.PREFERENCE])
        self.check.assert_not_called()
        self.panel.startup()
        self.dialog.assert_called_once()

    def test_first_start_yes_is_saved_then_checked_once(self):
        self.dialog.return_value = QMessageBox.Yes
        self.panel.startup()
        self.wait_idle()
        self.assertTrue(load_preferences(self.folder)[update_ui.PREFERENCE])
        self.assertTrue(self.panel.auto_check.isChecked())
        self.check.assert_called_once_with(VERSION, cancel_event=ANY)
        self.panel.startup()
        self.check.assert_called_once()

    def test_first_start_confirmation_defaults_and_escape_to_no(self):
        seen = []
        def inspect(dialog):
            seen.append(dialog)
            self.assertIs(dialog.defaultButton(), dialog.button(QMessageBox.No))
            self.assertIs(dialog.escapeButton(), dialog.button(QMessageBox.No))
            self.assertEqual(dialog.textFormat(), Qt.PlainText)
            return QMessageBox.No
        with patch('update_ui.QMessageBox.exec', new=inspect):
            self.panel.startup()
        self.assertEqual(len(seen), 1)

    def test_remembered_enabled_checks_without_reasking(self):
        self.owner.preferences[update_ui.PREFERENCE] = True
        self.panel.startup()
        self.wait_idle()
        self.dialog.assert_not_called()
        self.check.assert_called_once_with(VERSION, cancel_event=ANY)

    def test_remembered_disabled_has_no_startup_network_or_dialog(self):
        self.owner.preferences[update_ui.PREFERENCE] = False
        self.panel.startup()
        self.check.assert_not_called()
        self.dialog.assert_not_called()

    def test_manual_check_clicked_does_not_enable_automatic_checks(self):
        self.owner.preferences[update_ui.PREFERENCE] = False
        self.panel.check_button.click()
        self.wait_idle()
        self.check.assert_called_once_with(VERSION, cancel_event=ANY)
        self.assertFalse(self.owner.preferences[update_ui.PREFERENCE])
        self.assertIn(VERSION, self.panel.status.text())

    def test_checkbox_persists_immediately(self):
        self.panel.auto_check.click()
        self.assertTrue(load_preferences(self.folder)[update_ui.PREFERENCE])
        self.panel.auto_check.click()
        self.assertFalse(load_preferences(self.folder)[update_ui.PREFERENCE])

    def test_failed_preference_save_does_not_auto_check(self):
        self.dialog.return_value = QMessageBox.Yes
        with patch('update_ui.save_preferences', side_effect=PermissionError('blocked preference file')):
            self.panel.startup()
        self.check.assert_not_called()
        self.assertNotIn(update_ui.PREFERENCE, self.owner.preferences)
        self.assertFalse(self.panel.auto_check.isChecked())
        self.assertIn('未能保存', self.panel.status.text())

    def test_check_runs_on_worker_and_rapid_clicks_do_not_duplicate(self):
        gate = self.gate()
        seen = []
        def check(version, cancel_event=None):
            seen.append(QThread.currentThread() != self.qt.thread())
            gate.wait(2)
            return None
        self.check.side_effect = check
        self.panel.check_button.click()
        self.panel.check()
        self.wait_for(lambda: bool(seen))
        self.assertEqual(seen, [True])
        self.assertFalse(self.panel.check_button.isEnabled())
        gate.set()
        self.wait_idle()
        self.check.assert_called_once()

    def test_network_failure_is_visible_without_install_or_success(self):
        self.check.side_effect = OSError('offline')
        self.panel.check()
        self.wait_idle()
        self.assertIn('失败', self.panel.status.text())
        self.assertIn('offline', self.panel.status.text())
        self.assertTrue(self.panel.check_button.isEnabled())
        self.install.assert_not_called()

    def test_new_release_cancellation_never_downloads_or_installs(self):
        self.check.return_value = self.info
        self.panel.check()
        self.wait_idle()
        self.dialog.assert_called_once()
        self.download.assert_not_called()
        self.install.assert_not_called()
        self.owner.close.assert_not_called()

    def test_source_mode_reports_release_without_download_or_install(self):
        self.frozen.return_value = False
        self.check.return_value = self.info
        self.panel.check()
        self.wait_idle()
        self.assertIn('源码', self.panel.status.text())
        self.assertIn('9.0.0', self.panel.status.text())
        self.download.assert_not_called()
        self.install.assert_not_called()
        self.assertIn(update_ui.RELEASES_URL, self.panel.release_link.text())

    def test_confirmed_download_and_install_run_in_workers_then_close(self):
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        threads = []
        def download(info, directory, cancel_event=None):
            threads.append(QThread.currentThread() != self.qt.thread())
            return self.folder / 'verified.exe'
        def install(path, digest, directory):
            threads.append(QThread.currentThread() != self.qt.thread())
            self.assertTrue(self.owner.busy)
            self.assertFalse(self.owner.centralWidget().isEnabled())
        self.download.side_effect = download
        self.install.side_effect = install
        self.panel.check()
        self.wait_idle()
        self.assertEqual(threads, [True, True])
        self.install.assert_called_once_with(self.folder / 'verified.exe', self.info.sha256, self.folder)
        self.owner.close.assert_called_once()
        self.assertFalse(self.owner.busy)
        self.assertTrue(self.owner.centralWidget().isEnabled())

    def test_download_failure_never_installs(self):
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        self.download.side_effect = OSError('hash mismatch')
        self.panel.check()
        self.wait_idle()
        self.install.assert_not_called()
        self.owner.close.assert_not_called()
        self.assertIn('hash mismatch', self.panel.status.text())

    def test_install_failure_unlocks_ui_and_does_not_close(self):
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        self.install.side_effect = OSError('helper not ready')
        self.panel.check()
        self.wait_idle()
        self.assertIn('helper not ready', self.panel.status.text())
        self.assertFalse(self.owner.busy)
        self.assertTrue(self.owner.centralWidget().isEnabled())
        self.owner.close.assert_not_called()

    def test_probe_running_blocks_update_offer(self):
        self.check.return_value = self.info
        self.owner.probe_process = object()
        self.panel.check()
        self.wait_idle()
        self.dialog.assert_not_called()
        self.download.assert_not_called()
        self.assertIn('探针', self.panel.status.text())

    def test_probe_started_during_download_defers_install_until_clicked(self):
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        def download(*args, **kwargs):
            self.owner.probe_process = object()
            return self.folder / 'verified.exe'
        self.download.side_effect = download
        self.panel.check()
        self.wait_idle()
        self.install.assert_not_called()
        self.assertFalse(self.panel.install_button.isHidden())
        self.owner.probe_process = None
        self.panel.install_button.click()
        self.wait_idle()
        self.install.assert_called_once()

    def test_closing_waits_for_check_worker_and_suppresses_new_dialog(self):
        gate = self.gate()
        started = self.gate()
        def check(*args, **kwargs):
            started.set()
            gate.wait(2)
            return self.info
        self.check.side_effect = check
        self.panel.check()
        self.wait_for(started.is_set)
        self.assertFalse(self.panel.prepare_close())
        self.assertTrue(self.panel.thread.cancel_event.is_set())
        self.owner.close.assert_not_called()
        self.panel.check()
        gate.set()
        self.wait_idle()
        self.owner.close.assert_called_once()
        self.dialog.assert_not_called()
        self.download.assert_not_called()

    def test_closing_during_download_never_starts_install(self):
        gate = self.gate()
        started = self.gate()
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        def download(*args, **kwargs):
            started.set()
            gate.wait(2)
            return self.folder / 'verified.exe'
        self.download.side_effect = download
        self.panel.check()
        self.wait_for(started.is_set)
        self.assertFalse(self.panel.prepare_close())
        gate.set()
        self.wait_idle()
        self.install.assert_not_called()
        self.owner.close.assert_called_once()

    def test_disabling_auto_check_while_request_runs_suppresses_update_prompt(self):
        gate = self.gate()
        started = self.gate()
        self.owner.preferences[update_ui.PREFERENCE] = True
        def check(*args, **kwargs):
            started.set()
            gate.wait(2)
            return self.info
        self.check.side_effect = check
        self.panel.startup()
        self.wait_for(started.is_set)
        self.panel.set_preference(False)
        gate.set()
        self.wait_idle()
        self.dialog.assert_not_called()
        self.download.assert_not_called()

    def test_close_during_install_does_not_interrupt_committed_protocol(self):
        gate = self.gate()
        started = self.gate()
        self.check.return_value = self.info
        self.dialog.return_value = QMessageBox.Yes
        def install(*args):
            started.set()
            gate.wait(2)
        self.install.side_effect = install
        self.panel.check()
        self.wait_for(started.is_set)
        self.assertEqual(self.panel.mode, 'install')
        self.assertIsNone(self.panel.thread.cancel_event)
        self.assertFalse(self.panel.prepare_close())
        self.assertFalse(self.panel.thread.isInterruptionRequested())
        self.owner.close.assert_not_called()
        gate.set()
        self.wait_idle()
        self.owner.close.assert_called_once()
        self.assertFalse(self.owner.busy)

    def test_parent_window_constructor_stays_offline_and_header_fits_compact_screen(self):
        import gpu_selector
        db = Mock()
        db.read.return_value = None
        db.children.return_value = []
        db.values.return_value = []
        with patch('gpu_selector.Registry', return_value=db), patch('gpu_selector.adapters', return_value=[]), \
                patch('gpu_selector.report', return_value='mock report'), patch('gpu_selector.admin', return_value=False):
            window = gpu_selector.Window(data_dir=self.folder / 'main-window')
            try:
                window.timer.stop()
                window.show()
                window.font_spin.setValue(14)
                window.resize(600, 430)
                self.qt.processEvents()
                self.check.assert_not_called()
                self.dialog.assert_not_called()
                self.assertIn(VERSION, window.windowTitle())
                self.assertIn('作者：Freeze7y', window.author_link.text())
                self.assertIn('github.com/Freeze7y/gpu-selector', window.author_link.text())
                self.assertTrue(window.author_link.openExternalLinks())
                self.assertTrue(window.author_link.wordWrap())
                self.assertLessEqual(window.width(), 600)
                self.assertGreater(window.author_link.width(), 0)
                window.tabs.setCurrentIndex(5)
                self.qt.processEvents()
                self.assertEqual(window.tabs.widget(5).horizontalScrollBar().maximum(), 0)
            finally:
                window.close()
                window.deleteLater()
                self.qt.processEvents()


if __name__ == '__main__':
    unittest.main()
