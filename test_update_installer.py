"""Updater regressions: temporary EXE fixtures and mocked process creation only."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import update_installer as updater


class UpdateInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / '旧版本.exe'
        self.downloaded = self.root / '新版本.exe'
        self.old_bytes = b'MZ old test fixture'
        self.new_bytes = b'MZ new test fixture'
        self.target.write_bytes(self.old_bytes)
        self.downloaded.write_bytes(self.new_bytes)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.sentinel = self.data / 'backups' / 'real-settings.json'
        self.sentinel.parent.mkdir()
        self.sentinel.write_bytes(b'untouched GPU settings')
        self.frozen = patch.object(updater.sys, 'frozen', True, create=True)
        self.frozen.start()
        self.addCleanup(self.frozen.stop)
        self.executable = patch.object(updater.sys, 'executable', str(self.target))
        self.executable.start()
        self.addCleanup(self.executable.stop)

    def job(self):
        identifier = 'a' * 32
        directory = self.data / 'updates' / identifier
        directory.mkdir(parents=True)
        staged = self.target.with_name('.' + self.target.name + '.update-' + identifier + '.exe')
        staged.write_bytes(self.new_bytes)
        backup = directory / 'previous.exe'
        backup.write_bytes(self.old_bytes)
        result = dict(schema=1, id=identifier, data_dir=str(self.data), job_dir=str(directory),
                      target=str(self.target), downloaded=str(self.downloaded), staged=str(staged),
                      backup=str(backup), sha256=updater._sha256(self.downloaded),
                      old_sha256=updater._sha256(self.target), old_identity=updater._regular(self.target),
                      parent_pid=123)
        jobfile = directory / 'job.json'
        updater._write_json(jobfile, result)
        updater._marker(result, 'commit.json')
        return result, jobfile

    def helper_mocks(self, job, parent_exited=None, spawn=None):
        parent = Mock(path=self.target)
        parent.exited.side_effect = parent_exited if parent_exited is not None else [False, True]
        ready_process = Mock(path=self.target)
        ready_process.exited.return_value = False
        process = Mock(pid=456)
        process.poll.return_value = None
        def ready_spawn(args, data_dir, cwd):
            updater._marker(job, 'new-ready.json', pid=789)
            return process
        stack = []
        for item in (patch.object(updater.sys, 'executable', str(self.downloaded)),
                     patch('update_installer._Process', side_effect=[parent, ready_process]),
                     patch('update_installer._spawn', side_effect=spawn or ready_spawn)):
            stack.append(item.start())
            self.addCleanup(item.stop)
        return parent, process, stack[-1]

    def test_source_mode_refuses_before_creating_update_files(self):
        with patch.object(updater.sys, 'frozen', False), patch('update_installer._spawn') as spawn:
            with self.assertRaisesRegex(ValueError, '源码'):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        self.assertFalse((self.data / 'updates').exists())
        spawn.assert_not_called()

    def test_bad_download_hash_never_changes_existing_exe(self):
        with patch('update_installer._spawn') as spawn:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                updater.install_update(self.downloaded, '0' * 64, self.data)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertFalse((self.data / 'updates').exists())
        spawn.assert_not_called()

    def test_helper_launch_failure_keeps_current_exe_and_records_failure(self):
        with patch('update_installer._spawn', side_effect=OSError('launch blocked')):
            with self.assertRaisesRegex(OSError, 'launch blocked'):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        directory = next((self.data / 'updates').iterdir())
        self.assertEqual(updater._read_json(directory / 'result.json')['status'], 'failed')
        self.assertEqual((directory / 'previous.exe').read_bytes(), self.old_bytes)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertFalse(list(self.root.glob('.*.update-*.exe')))
        self.assertEqual(self.sentinel.read_bytes(), b'untouched GPU settings')

    def test_helper_ready_timeout_keeps_old_ui_safe_to_continue(self):
        process = Mock()
        process.poll.return_value = None
        with patch('update_installer._spawn', return_value=process), patch('update_installer.READY_TIMEOUT', 0):
            with self.assertRaises(TimeoutError):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertTrue(next((self.data / 'updates').iterdir()).joinpath('cancel.json').exists())

    def test_stale_ready_marker_from_exited_helper_does_not_allow_gui_exit(self):
        process = Mock()
        process.poll.return_value = 1
        def start(args, data_dir, cwd):
            job = updater._load_job(args[-1])
            updater._marker(job, 'ready.json', pid=456)
            updater._marker(job, 'accepted.json', pid=456)
            return process
        with patch('update_installer._spawn', side_effect=start), patch('update_installer._Process') as identity:
            with self.assertRaisesRegex(RuntimeError, '提前退出'):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        identity.assert_not_called()

    def test_successful_commit_handshake_preserves_old_exe_until_caller_exits(self):
        helper = Mock()
        helper.poll.return_value = None
        helper_identity = Mock(path=self.downloaded)
        helper_identity.exited.return_value = False
        def start(args, data_dir, cwd):
            job = updater._load_job(args[-1])
            updater._marker(job, 'ready.json', pid=456)
            updater._marker(job, 'accepted.json', pid=456)
            return helper
        with patch('update_installer._spawn', side_effect=start) as spawn, patch('update_installer._Process', return_value=helper_identity):
            self.assertIsNone(updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data))
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        jobfile = Path(spawn.call_args.args[0][-1])
        job = updater._load_job(jobfile)
        self.assertIsNotNone(updater._read_marker(job, 'commit.json'))
        self.assertEqual(Path(job['staged']).read_bytes(), self.new_bytes)

    def test_commit_timeout_cancels_helper_and_keeps_original_running_file(self):
        helper = Mock()
        helper.poll.return_value = None
        helper_identity = Mock(path=self.downloaded)
        helper_identity.exited.return_value = False
        def start(args, data_dir, cwd):
            job = updater._load_job(args[-1])
            updater._marker(job, 'ready.json', pid=456)
            return helper
        with patch('update_installer._spawn', side_effect=start), patch('update_installer._Process', return_value=helper_identity), patch('update_installer.COMMIT_TIMEOUT', 0):
            with self.assertRaises(TimeoutError):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertTrue(next((self.data / 'updates').iterdir()).joinpath('cancel.json').exists())

    def test_unwritable_install_directory_fails_before_launching_helper(self):
        original_open = Path.open
        def deny_stage(path, mode='r', *args, **kwargs):
            if '.update-' in path.name and mode == 'xb':
                raise PermissionError('install directory is read-only')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', deny_stage), patch('update_installer._spawn') as spawn:
            with self.assertRaises(PermissionError):
                updater.install_update(self.downloaded, updater._sha256(self.downloaded), self.data)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        spawn.assert_not_called()

    def test_parent_stays_alive_timeout_prevents_replacement(self):
        job, jobfile = self.job()
        self.helper_mocks(job, parent_exited=lambda: False)
        with patch('update_installer.PARENT_TIMEOUT', 0):
            self.assertEqual(updater.run_update_helper(jobfile), 1)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertEqual(updater._read_marker(job, 'result.json')['status'], 'failed')

    def test_success_requires_ready_from_live_new_gui_and_preserves_backup(self):
        job, jobfile = self.job()
        parent, process, spawn = self.helper_mocks(job)
        self.assertEqual(updater.run_update_helper(jobfile), 0)
        self.assertEqual(self.target.read_bytes(), self.new_bytes)
        self.assertEqual(Path(job['backup']).read_bytes(), self.old_bytes)
        result = updater._read_marker(job, 'result.json')
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(spawn.call_args.args[0], [str(self.target), '--update-complete', str(jobfile)])
        self.assertEqual(self.sentinel.read_bytes(), b'untouched GPU settings')

    def test_new_gui_no_ready_rolls_back_and_requests_old_restart(self):
        job, jobfile = self.job()
        new = Mock(pid=456)
        new.poll.return_value = None
        self.helper_mocks(job, spawn=lambda *args: new)
        with patch('update_installer.START_TIMEOUT', 0), patch('update_installer._stop_started_process') as stop:
            self.assertEqual(updater.run_update_helper(jobfile), 1)
        stop.assert_called_once_with(new)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        result = updater._read_marker(job, 'result.json')
        self.assertEqual(result['status'], 'rolled_back')
        self.assertTrue(result['old_restart_requested'])
        self.assertEqual(Path(job['backup']).read_bytes(), self.old_bytes)

    def test_external_target_change_after_replace_is_never_overwritten_on_failure(self):
        job, jobfile = self.job()
        new = Mock(pid=456)
        new.poll.return_value = 1
        def spawn(*args):
            self.target.write_bytes(b'MZ external modification')
            return new
        self.helper_mocks(job, spawn=spawn)
        with patch('update_installer._stop_started_process'):
            self.assertEqual(updater.run_update_helper(jobfile), 1)
        self.assertEqual(self.target.read_bytes(), b'MZ external modification')
        self.assertEqual(updater._read_marker(job, 'result.json')['status'], 'failed')
        self.assertEqual(Path(job['backup']).read_bytes(), self.old_bytes)

    def test_tampered_stage_while_parent_exits_is_rejected_before_replace(self):
        job, jobfile = self.job()
        calls = []
        def exited():
            calls.append(1)
            if len(calls) == 1:
                return False
            Path(job['staged']).write_bytes(b'MZ tampered update')
            return True
        self.helper_mocks(job, parent_exited=exited)
        self.assertEqual(updater.run_update_helper(jobfile), 1)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertTrue(updater._read_marker(job, 'result.json')['old_restart_requested'])

    def test_bootloader_file_lock_is_retried_before_atomic_replace(self):
        job, jobfile = self.job()
        self.helper_mocks(job)
        replace = os.replace
        attempts = []
        def locked_once(source, destination):
            if Path(source) == Path(job['staged']):
                attempts.append(1)
                if len(attempts) == 1:
                    raise PermissionError('old bootloader still holds executable')
            return replace(source, destination)
        with patch('update_installer.os.replace', side_effect=locked_once), patch('update_installer.time.sleep'):
            self.assertEqual(updater.run_update_helper(jobfile), 0)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.target.read_bytes(), self.new_bytes)

    def test_cancelled_job_never_replaces_target(self):
        job, jobfile = self.job()
        self.helper_mocks(job)
        updater._marker(job, 'cancel.json')
        self.assertEqual(updater.run_update_helper(jobfile), 1)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)

    def test_permanent_bootloader_lock_preserves_and_restarts_old_program(self):
        job, jobfile = self.job()
        self.helper_mocks(job)
        replace = os.replace
        def locked(source, destination):
            if Path(source) == Path(job['staged']):
                raise PermissionError('still in use')
            return replace(source, destination)
        with patch('update_installer.os.replace', side_effect=locked), patch('update_installer.REPLACE_TIMEOUT', 0):
            self.assertEqual(updater.run_update_helper(jobfile), 1)
        self.assertEqual(self.target.read_bytes(), self.old_bytes)
        self.assertTrue(updater._read_marker(job, 'result.json')['old_restart_requested'])

    def test_logging_failure_after_new_gui_ready_does_not_rollback_working_update(self):
        job, jobfile = self.job()
        self.helper_mocks(job)
        marker = updater._marker
        def result_denied(job, name, **values):
            if name == 'result.json':
                raise PermissionError('result file is read-only')
            return marker(job, name, **values)
        with patch('update_installer._marker', side_effect=result_denied):
            self.assertEqual(updater.run_update_helper(jobfile), 0)
        self.assertEqual(self.target.read_bytes(), self.new_bytes)

    def test_job_cannot_redirect_staged_or_backup_outside_assigned_paths(self):
        job, jobfile = self.job()
        for key in ('staged', 'backup', 'job_dir'):
            changed = copy.deepcopy(job)
            changed[key] = str(self.root / 'unrelated.exe')
            updater._write_json(jobfile, changed)
            with self.subTest(key=key), self.assertRaises(ValueError):
                updater._load_job(jobfile)

    def test_ready_marker_requires_current_updated_exe_and_preserves_data_directory(self):
        job, jobfile = self.job()
        self.target.write_bytes(self.new_bytes)
        self.assertEqual(updater.update_data_dir(jobfile), self.data)
        updater.mark_update_ready(jobfile)
        self.assertEqual(updater._read_marker(job, 'new-ready.json')['pid'], os.getpid())
        with patch.object(updater.sys, 'executable', str(self.downloaded)):
            with self.assertRaises(ValueError):
                updater.mark_update_ready(jobfile)

    def test_spawn_resets_pyinstaller_environment_and_uses_argument_list(self):
        with patch('update_installer.subprocess.Popen') as popen:
            updater._spawn([self.downloaded, '--apply-update', self.root / '含 空格.json'], self.data, self.root)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(self.downloaded), '--apply-update', str(self.root / '含 空格.json')])
        self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertEqual(kwargs['env']['GPU_SELECTOR_DATA_DIR'], str(self.data))
        self.assertNotIn('shell', kwargs)


if __name__ == '__main__':
    unittest.main()
