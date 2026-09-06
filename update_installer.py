"""Verified, reversible EXE replacement through an independent Windows helper."""
import ctypes
import contextlib
from ctypes import wintypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

READY_TIMEOUT = 25
COMMIT_TIMEOUT = 10
PARENT_TIMEOUT = 60
REPLACE_TIMEOUT = 30
START_TIMEOUT = 30


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('更新文件必须是普通文件，不能是目录、符号链接或重解析点。')
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size, mtime_ns=info.st_mtime_ns)


def _write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError('更新记录过大。')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('更新记录格式无效。')
    return value


def _marker(job, name, **values):
    _write_json(Path(job['job_dir']) / name, dict(id=job['id'], **values))


def _read_marker(job, name):
    path = Path(job['job_dir']) / name
    if not path.exists():
        return None
    value = _read_json(path)
    if value.get('id') != job['id']:
        raise ValueError('更新握手记录不匹配。')
    return value


def _cancelled(job):
    if (Path(job['job_dir']) / 'cancel.json').exists():
        raise RuntimeError('更新已取消，保留原程序。')


def _wait_for(job, callback, timeout, description, process=None):
    deadline = time.monotonic() + timeout
    while True:
        _cancelled(job)
        if process is not None and process.poll() is not None:
            raise RuntimeError(description + '：进程提前退出。')
        value = callback()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError(description + '超时。')
        time.sleep(.1)


class _Process:
    """A process handle survives PID reuse while waiting for the original GUI."""
    def __init__(self, pid):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                          wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.path = Path(buffer.value).resolve()
        except Exception:
            self.close()
            raise

    def exited(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result == 0xffffffff:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _spawn(args, data_dir, cwd):
    environment = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1',
                       GPU_SELECTOR_DATA_DIR=str(data_dir))
    # A restarted one-file app must extract its own libraries, rather than reuse
    # the old process's temporary directory after the old bootloader removes it.
    return subprocess.Popen([str(arg) for arg in args], cwd=str(cwd), env=environment,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True)


def _load_job(jobfile):
    jobfile = Path(jobfile).absolute()
    _regular(jobfile)
    job = _read_json(jobfile)
    if job.get('schema') != 1 or not re.fullmatch(r'[0-9a-f]{32}', str(job.get('id', ''))):
        raise ValueError('更新任务版本或标识无效。')
    for name in ('data_dir', 'job_dir', 'target', 'downloaded', 'staged', 'backup'):
        if not isinstance(job.get(name), str) or not Path(job[name]).is_absolute():
            raise ValueError('更新任务路径无效。')
    directory = Path(job['job_dir'])
    target = Path(job['target'])
    if (jobfile.resolve() != directory / 'job.json' or
            directory != Path(job['data_dir']) / 'updates' / job['id'] or
            Path(job['backup']) != directory / 'previous.exe' or
            Path(job['staged']) != target.with_name('.' + target.name + '.update-' + job['id'] + '.exe') or
            target.suffix.lower() != '.exe' or Path(job['downloaded']) == target):
        raise ValueError('更新任务包含不匹配的文件位置。')
    if any(not re.fullmatch(r'[0-9a-f]{64}', str(job.get(key, ''))) for key in ('sha256', 'old_sha256')):
        raise ValueError('更新任务校验值无效。')
    if type(job.get('parent_pid')) is not int or job['parent_pid'] <= 0:
        raise ValueError('更新任务原进程无效。')
    return job


def install_update(downloaded, sha256, data_dir):
    """Prepare and commit a helper; the caller may exit only after this returns."""
    if not getattr(sys, 'frozen', False):
        raise ValueError('源码运行模式不支持覆盖安装；请从发布页下载 EXE。')
    if not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', sha256):
        raise ValueError('新版本 SHA-256 校验值无效。')
    downloaded, target = Path(downloaded).absolute(), Path(sys.executable).absolute()
    _regular(downloaded)
    identity = _regular(target)
    downloaded, target = downloaded.resolve(), target.resolve()
    sha256 = sha256.lower()
    if target.suffix.lower() != '.exe' or downloaded.suffix.lower() != '.exe' or os.path.samefile(downloaded, target):
        raise ValueError('必须使用独立下载的新 EXE 更新当前 EXE。')
    if _sha256(downloaded) != sha256:
        raise ValueError('下载文件 SHA-256 不匹配，未启动安装。')
    data_dir = Path(data_dir).resolve()
    identifier = uuid.uuid4().hex
    updates = data_dir / 'updates'
    updates.mkdir(parents=True, exist_ok=True)
    info = updates.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('更新目录不能是符号链接或重解析点。')
    directory = updates / identifier
    directory.mkdir(exist_ok=False)
    staged = target.with_name('.' + target.name + '.update-' + identifier + '.exe')
    backup = directory / 'previous.exe'
    job = dict(schema=1, id=identifier, data_dir=str(data_dir), job_dir=str(directory),
               target=str(target), downloaded=str(downloaded), staged=str(staged), backup=str(backup),
               sha256=sha256, old_sha256='', old_identity=identity, parent_pid=os.getpid())
    try:
        # Exclusive creation proves directory write permission while the old UI
        # is still running, and prevents overwriting an existing staging file.
        with staged.open('xb') as output, downloaded.open('rb') as source:
            shutil.copyfileobj(source, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(staged) != sha256:
            raise ValueError('同目录暂存文件校验失败。')
        shutil.copy2(target, backup)
        job['old_sha256'] = _sha256(backup)
        if _regular(target) != identity or _sha256(target) != job['old_sha256']:
            raise ValueError('准备更新时原程序发生变化，停止更新。')
        jobfile = directory / 'job.json'
        _write_json(jobfile, job)
        helper = _spawn([downloaded, '--apply-update', jobfile], data_dir, directory)
        ready = _wait_for(job, lambda: _read_marker(job, 'ready.json'), READY_TIMEOUT,
                          '等待独立更新助手', helper)
        process = _Process(ready.get('pid', 0))
        try:
            if process.path != downloaded or process.exited():
                raise RuntimeError('更新助手身份验证失败。')
        finally:
            process.close()
        _marker(job, 'commit.json')
        _wait_for(job, lambda: _read_marker(job, 'accepted.json'), COMMIT_TIMEOUT,
                  '等待更新助手接受任务', helper)
    except Exception as exc:
        with contextlib.suppress(OSError):
            _marker(job, 'cancel.json', error=str(exc))
            _marker(job, 'result.json', ok=False, status='failed', error=str(exc), target=str(target))
        # Remove only this task's verified temporary copy; keep the old backup.
        with contextlib.suppress(OSError, ValueError):
            if staged.exists() and _regular(staged) and _sha256(staged) == sha256:
                staged.unlink()
        raise


def _check_original(job):
    target = Path(job['target'])
    if _regular(target) != job.get('old_identity') or _sha256(target) != job['old_sha256']:
        raise ValueError('原 EXE 已被外部更改，拒绝覆盖。')


def _replace(job, source, expected_hash, original_identity=False):
    deadline = time.monotonic() + REPLACE_TIMEOUT
    while True:
        _cancelled(job)
        _regular(source)
        if _sha256(source) != (job['sha256'] if original_identity else job['old_sha256']):
            raise ValueError('待替换文件校验失败，保留当前 EXE。')
        if original_identity:
            _check_original(job)
        else:
            _regular(job['target'])
            if _sha256(job['target']) != expected_hash:
                raise ValueError('目标 EXE 已被外部更改，拒绝覆盖。')
        try:
            os.replace(source, job['target'])
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise TimeoutError('原程序或启动器仍占用 EXE，未完成文件替换。')
            time.sleep(.2)


def _new_ready(job, process):
    marker = _read_marker(job, 'new-ready.json')
    if not marker:
        return False
    if process.poll() is not None:
        raise RuntimeError('新版本启动后已退出。')
    running = _Process(marker.get('pid', 0))
    try:
        if running.path != Path(job['target']) or running.exited():
            raise RuntimeError('新版本启动验证失败。')
    finally:
        running.close()
    return True


def _stop_started_process(process):
    if process is None or process.poll() is not None:
        return
    taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
    result = subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
    if result.returncode and process.poll() is None:
        raise OSError('无法关闭本次启动的新版本；保留备份，停止自动回滚。')
    process.wait(timeout=10)


def run_update_helper(jobfile):
    """Helper entry point, dispatched before creating QApplication or any probes."""
    job = None
    parent = None
    new_process = None
    replaced = False
    parent_exited = False
    try:
        if not getattr(sys, 'frozen', False):
            raise ValueError('更新助手只能由打包 EXE 运行。')
        job = _load_job(jobfile)
        if Path(sys.executable).resolve() != Path(job['downloaded']):
            raise ValueError('更新助手不是本次下载的 EXE。')
        parent = _Process(job['parent_pid'])
        if parent.path != Path(job['target']) or parent.exited():
            raise ValueError('原程序身份不匹配或已经退出。')
        for name, digest in [('downloaded', job['sha256']), ('staged', job['sha256']), ('backup', job['old_sha256'])]:
            _regular(job[name])
            if _sha256(job[name]) != digest:
                raise ValueError('更新文件或旧版备份校验失败。')
        _check_original(job)
        _marker(job, 'ready.json', pid=os.getpid())
        _wait_for(job, lambda: _read_marker(job, 'commit.json'), READY_TIMEOUT, '等待原程序确认')
        _marker(job, 'accepted.json', pid=os.getpid())
        _wait_for(job, parent.exited, PARENT_TIMEOUT, '等待原程序退出')
        parent_exited = True
        parent.close()
        parent = None
        _replace(job, job['staged'], job['old_sha256'], original_identity=True)
        replaced = True
        if _sha256(job['target']) != job['sha256']:
            raise ValueError('替换后的 EXE 校验失败。')
        new_process = _spawn([job['target'], '--update-complete', str(Path(job['job_dir']) / 'job.json')],
                             job['data_dir'], Path(job['target']).parent)
        _wait_for(job, lambda: _new_ready(job, new_process), START_TIMEOUT, '验证新版本界面启动', new_process)
        # A diagnostic write failure must not undo a verified running new GUI.
        with contextlib.suppress(OSError):
            _marker(job, 'result.json', ok=True, status='success', target=job['target'], backup=job['backup'],
                    completed=datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
        return 0
    except Exception as exc:
        error = str(exc)
        status = 'failed'
        restarted = False
        if job is not None and replaced:
            try:
                _stop_started_process(new_process)
                _regular(job['target'])
                _regular(job['backup'])
                if _sha256(job['target']) != job['sha256'] or _sha256(job['backup']) != job['old_sha256']:
                    raise ValueError('目标或旧版备份已改变，未自动覆盖；请保留备份手动检查。')
                rollback = Path(job['target']).with_name('.' + Path(job['target']).name + '.rollback-' + job['id'] + '.exe')
                with rollback.open('xb') as output, Path(job['backup']).open('rb') as source:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if _sha256(rollback) != job['old_sha256']:
                    raise ValueError('回滚文件校验失败。')
                _replace(job, rollback, job['sha256'])
                status = 'rolled_back'
                _spawn([job['target']], job['data_dir'], Path(job['target']).parent)
                restarted = True
            except Exception as rollback_exc:
                error += '\n恢复旧版：' + str(rollback_exc)
        elif job is not None and parent_exited:
            try:
                _check_original(job)
                _spawn([job['target']], job['data_dir'], Path(job['target']).parent)
                restarted = True
            except Exception as restart_exc:
                error += '\n重新打开旧版：' + str(restart_exc)
        if job is not None:
            with contextlib.suppress(OSError):
                _marker(job, 'result.json', ok=False, status=status, error=error,
                        target=job['target'], backup=job['backup'], old_restart_requested=restarted)
        return 1
    finally:
        if parent is not None:
            parent.close()


def update_data_dir(jobfile):
    job = _load_job(jobfile)
    if not getattr(sys, 'frozen', False) or Path(sys.executable).resolve() != Path(job['target']):
        raise ValueError('更新完成参数与当前 EXE 不匹配。')
    return Path(job['data_dir'])


def mark_update_ready(jobfile):
    """Call from the new window's event loop after Window.show() completes."""
    update_data_dir(jobfile)
    job = _load_job(jobfile)
    if _sha256(job['target']) != job['sha256']:
        raise ValueError('新启动程序与下载校验值不匹配。')
    _marker(job, 'new-ready.json', pid=os.getpid())
