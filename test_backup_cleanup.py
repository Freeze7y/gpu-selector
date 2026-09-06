"""Backup cleanup tests use temporary files and mock every actual trash request."""
import copy
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backup_cleanup import backup_snapshot, trash_backup


class BackupCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'backups'
        self.folder.mkdir()
        self.path = self.folder / '中文备份.json'
        self.path.write_text('{malformed JSON', encoding='utf-8')
        self.qt_patch = patch('backup_cleanup.QFile')
        self.qt = self.qt_patch.start()
        self.addCleanup(self.qt_patch.stop)
        self.qt.return_value.moveToTrash.return_value = True
        self.qt.return_value.errorString.return_value = 'simulated trash failure'

    def test_snapshot_accepts_corrupt_json_without_reading_content(self):
        with patch.object(Path, 'open', side_effect=AssertionError('Must not read backup contents')):
            snapshot = backup_snapshot(self.folder, self.path)
        self.assertEqual(snapshot['path'], str(self.path.resolve()))
        self.assertEqual(snapshot['stat']['size'], self.path.stat().st_size)
        self.assertEqual(snapshot['stat']['inode'], self.path.stat().st_ino)
        self.qt.assert_not_called()

    def test_large_and_uppercase_json_backup_is_allowed(self):
        path = self.folder / 'large.JSON'
        with path.open('wb') as stream:
            stream.truncate(5 * 1024 * 1024)
        self.assertEqual(backup_snapshot(self.folder, path)['stat']['size'], 5 * 1024 * 1024)

    def test_only_immediate_json_files_are_eligible(self):
        nested = self.folder / 'nested'
        nested.mkdir()
        for path in (self.root / 'outside.json', nested / 'nested.json', self.folder / 'note.txt'):
            path.write_text('x', encoding='utf-8')
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                backup_snapshot(self.folder, path)
        directory = self.folder / 'directory.json'
        directory.mkdir()
        with self.assertRaises(ValueError):
            backup_snapshot(self.folder, directory)
        self.qt.assert_not_called()

    def marked_lstat(self, path, **changes):
        original = Path.lstat
        def modified(candidate, *args, **kwargs):
            result = original(candidate, *args, **kwargs)
            if candidate == path:
                fields = {name: getattr(result, name) for name in dir(result) if name.startswith('st_')}
                fields.update(changes)
                return SimpleNamespace(**fields)
            return result
        return patch.object(Path, 'lstat', modified)

    def test_symbolic_link_mode_is_rejected(self):
        with self.marked_lstat(self.path, st_mode=stat.S_IFLNK | 0o777):
            with self.assertRaises(ValueError):
                backup_snapshot(self.folder, self.path)
        self.qt.assert_not_called()

    def test_windows_file_reparse_attribute_and_tag_are_rejected(self):
        for changes in (dict(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT),
                        dict(st_reparse_tag=0xA0000003)):
            with self.subTest(changes=changes), self.marked_lstat(self.path, **changes):
                with self.assertRaises(ValueError):
                    backup_snapshot(self.folder, self.path)
        self.qt.assert_not_called()

    def test_backup_directory_reparse_point_is_rejected(self):
        with self.marked_lstat(self.folder, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT):
            with self.assertRaises(ValueError):
                backup_snapshot(self.folder, self.path)
        self.qt.assert_not_called()

    def test_missing_file_is_not_reported_successful(self):
        snapshot = backup_snapshot(self.folder, self.path)
        self.path.unlink()
        with self.assertRaises(OSError):
            trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()

    def test_changed_contents_after_confirmation_are_rejected(self):
        snapshot = backup_snapshot(self.folder, self.path)
        self.path.write_text('changed backup contents', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '发生变化'):
            trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()

    def test_replaced_file_with_same_size_and_mtime_is_rejected_by_identity(self):
        snapshot = backup_snapshot(self.folder, self.path)
        old = self.path.stat()
        replacement = self.root / 'replacement.json'
        replacement.write_bytes(b'x' * old.st_size)
        os.utime(replacement, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.path.replace(self.root / 'original-kept.json')
        replacement.replace(self.path)
        with self.assertRaisesRegex(ValueError, '发生变化'):
            trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()

    def test_replaced_directory_identity_is_rejected(self):
        snapshot = backup_snapshot(self.folder, self.path)
        with self.marked_lstat(self.folder, st_ino=snapshot['directory_id']['inode'] + 1):
            with self.assertRaisesRegex(ValueError, '发生变化'):
                trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()

    def test_reparse_replacement_after_confirmation_is_rejected(self):
        snapshot = backup_snapshot(self.folder, self.path)
        with self.marked_lstat(self.path, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT):
            with self.assertRaises(ValueError):
                trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()

    def test_outside_snapshot_cannot_bypass_directory_scope(self):
        snapshot = backup_snapshot(self.folder, self.path)
        outside = self.root / 'outside.json'
        outside.write_text('preserve me', encoding='utf-8')
        snapshot['path'] = str(outside)
        with self.assertRaises(ValueError):
            trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()
        self.assertEqual(outside.read_text(encoding='utf-8'), 'preserve me')

    def test_success_calls_only_qt_instance_trash_with_confirmed_path(self):
        snapshot = backup_snapshot(self.folder, self.path)
        with patch.object(Path, 'unlink', side_effect=AssertionError('Permanent deletion forbidden')):
            self.assertIsNone(trash_backup(self.folder, snapshot))
        self.qt.assert_called_once_with(self.path.resolve().as_posix())
        self.qt.return_value.moveToTrash.assert_called_once_with()
        self.qt.return_value.remove.assert_not_called()
        self.assertTrue(self.path.exists())  # Mocking trash leaves the test file intact.

    def test_configured_folder_with_parent_segment_remains_valid_after_snapshot(self):
        (self.root / 'unused').mkdir()
        configured = self.root / 'unused' / '..' / 'backups'
        snapshot = backup_snapshot(configured, configured / self.path.name)
        self.assertIsNone(trash_backup(configured, snapshot))
        self.qt.assert_called_once_with(self.path.resolve().as_posix())

    def test_new_unrelated_backup_does_not_invalidate_confirmed_file(self):
        snapshot = backup_snapshot(self.folder, self.path)
        (self.folder / 'new-backup.json').write_text('{}', encoding='utf-8')
        self.assertIsNone(trash_backup(self.folder, snapshot))
        self.qt.return_value.moveToTrash.assert_called_once_with()

    def test_qt_failure_never_falls_back_to_permanent_deletion(self):
        snapshot = backup_snapshot(self.folder, self.path)
        self.qt.return_value.moveToTrash.return_value = False
        with patch.object(Path, 'unlink', side_effect=AssertionError('Permanent deletion forbidden')):
            with self.assertRaisesRegex(OSError, '未执行永久删除'):
                trash_backup(self.folder, snapshot)
        self.qt.return_value.remove.assert_not_called()
        self.assertTrue(self.path.exists())

    def test_tuple_from_wrong_overload_cannot_be_misreported_as_success(self):
        snapshot = backup_snapshot(self.folder, self.path)
        self.qt.return_value.moveToTrash.return_value = (False, '')
        with self.assertRaises(OSError):
            trash_backup(self.folder, snapshot)
        self.assertTrue(self.path.exists())

    def test_invalid_or_tampered_confirmation_is_rejected(self):
        good = backup_snapshot(self.folder, self.path)
        bad = copy.deepcopy(good)
        bad['stat']['size'] += 1
        for snapshot in (None, {}, dict(path=123), bad):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                trash_backup(self.folder, snapshot)
        self.qt.assert_not_called()
