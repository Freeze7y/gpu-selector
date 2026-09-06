"""Recycle one confirmed backup file, without reading its JSON or changing settings."""
from pathlib import Path
import stat

from PySide6.QtCore import QFile


def _is_reparse(info):
    return (stat.S_ISLNK(info.st_mode) or
            bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT) or
            bool(getattr(info, 'st_reparse_tag', 0)))


def backup_snapshot(backup_dir, path):
    """Capture a directly contained regular JSON file for the confirmation dialog."""
    folder, target = Path(backup_dir).absolute(), Path(path).absolute()
    directory = folder.lstat()
    if not stat.S_ISDIR(directory.st_mode) or _is_reparse(directory):
        raise ValueError('备份目录不是普通目录，或包含重解析点，停止清除。')
    resolved_folder = folder.resolve(strict=True)
    if (target.parent not in (folder, resolved_folder) or
            target.suffix.lower() != '.json' or ':' in target.name):
        raise ValueError('只能清除当前备份目录直接包含的 .json 文件。')
    info = target.lstat()
    if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
        raise ValueError('只能清除普通备份文件；目录、符号链接和重解析点不能清除。')
    resolved_target = target.resolve(strict=True)
    if resolved_target.parent != resolved_folder:
        raise ValueError('备份文件不在当前备份目录内，停止清除。')
    return dict(path=str(resolved_target), backup_dir=str(resolved_folder),
                stat=dict(device=info.st_dev, inode=info.st_ino, mode=info.st_mode,
                          size=info.st_size, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
                          attributes=getattr(info, 'st_file_attributes', 0),
                          reparse_tag=getattr(info, 'st_reparse_tag', 0)),
                directory_id=dict(device=directory.st_dev, inode=directory.st_ino))


def trash_backup(backup_dir, snapshot):
    """Revalidate the confirmed file, then request Qt's reversible trash operation."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('path'), str):
        raise ValueError('备份确认记录无效，请重新选择备份。')
    current = backup_snapshot(backup_dir, snapshot['path'])
    if current != snapshot:
        raise ValueError('确认期间备份文件或目录发生变化，已停止清除；请刷新后重新选择。')
    file = QFile(Path(current['path']).as_posix())
    if file.moveToTrash() is not True:
        raise OSError('无法将备份移入 Windows 回收站，未执行永久删除：' + file.errorString())
