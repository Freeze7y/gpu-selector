"""Backup page tests with an owner that forbids registry mutation."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QWidget
from management_page import ManagementPage, backup_rows


class Owner(QWidget):
    def __init__(self, folder):
        super().__init__()
        self.db = Mock()
        self.db.write.side_effect = AssertionError('Registry mutation forbidden')
        self.gpus = []
        self.data_dir = folder
        self.backup_dir = folder / 'backups'
        self.execute = Mock(return_value=True)
        self.refresh = Mock(return_value=True)
        self.error = Mock()


class ManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'uncreated'
        self.owner = Owner(self.folder)
        self.page = ManagementPage(self.owner)
        self.addCleanup(self.owner.close)

    def backup(self, name='latest.json'):
        self.owner.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.owner.backup_dir / name
        path.write_text(json.dumps(dict(label='DX', after=[])), encoding='utf-8')
        return path

    def test_constructor_and_empty_refresh_create_no_files(self):
        with patch('management_page.health_rows', return_value=[]):
            self.page.refresh()
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.page.restore_button.isEnabled())

    def test_corrupt_and_mismatched_backups_do_not_hide_good_rows(self):
        good = self.backup('good.json')
        broken = self.backup('broken.json')
        broken.write_text('bad json', encoding='utf-8')
        mismatch = self.backup('old.json')
        def validate(db, path):
            if Path(path) == mismatch:
                raise ValueError('设置已经发生变化')
            return ['plan']
        with patch('management_page.restore_plan', side_effect=validate):
            rows = backup_rows(self.owner.db, self.owner.backup_dir, [])
        self.assertEqual(len(rows), 3)
        self.assertTrue(next(r for r in rows if r['path'] == str(good))['eligible'])
        self.assertFalse(next(r for r in rows if r['path'] == str(broken))['eligible'])
        self.assertIn('发生变化', next(r for r in rows if r['path'] == str(mismatch))['error'])

    def test_restore_revalidates_after_refresh_before_delegating(self):
        self.backup()
        plan = ['approved-plan']
        with patch('management_page.restore_plan', return_value=plan), patch('management_page.health_rows', return_value=[]):
            self.page.refresh_backups()
            self.page.restore_selected()
        self.owner.refresh.assert_called_once()
        self.owner.execute.assert_called_once_with(plan, 'History-Restore')
        self.owner.db.write.assert_not_called()

    def test_restore_rejects_changed_registry_after_list_loaded(self):
        self.backup()
        with patch('management_page.restore_plan', return_value=['plan']):
            self.page.refresh_backups()
        with patch('management_page.restore_plan', side_effect=ValueError('设置已变化')), patch('management_page.health_rows', return_value=[]):
            self.page.restore_selected()
        self.owner.execute.assert_not_called()
        self.owner.error.assert_called_once()
        self.assertFalse(self.page.restore_button.isEnabled())

    def test_failed_owner_refresh_stops_restore(self):
        self.backup()
        self.owner.refresh.return_value = False
        with patch('management_page.restore_plan', return_value=['plan']), patch('management_page.health_rows', return_value=[]):
            self.page.refresh_backups()
            self.page.restore_selected()
        self.owner.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
