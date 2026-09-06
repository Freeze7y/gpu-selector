"""GitHub updates over Windows WinHTTP; call from a worker, never the GUI thread.

TLS certificate verification remains enabled. No Python SSL or QtNetwork is used.
API: https://docs.github.com/en/rest/releases/releases
WinHTTP: https://learn.microsoft.com/windows/win32/winhttp/portal
"""
import ctypes as c
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urljoin, urlsplit


REPOSITORY = 'Freeze7y/gpu-selector'
RELEASES_URL = f'https://api.github.com/repos/{REPOSITORY}/releases'
REPOSITORY_URL = f'https://github.com/{REPOSITORY}'
MAX_ASSET_BYTES = 256 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024
_VERSION = re.compile(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
                      r'(?:-(alpha|beta|rc)(?:\.?([0-9]+))?)?\Z')


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag_name: str
    release_url: str
    asset_name: str
    download_url: str
    size: int
    sha256: str


def _version_key(version):
    match = _VERSION.fullmatch(version) if isinstance(version, str) and len(version) <= 64 else None
    if not match:
        raise UpdateError('版本号格式无效。')
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch),
            {None: 3, 'rc': 2, 'beta': 1, 'alpha': 0}[stage], int(number or 0))


def _validate_info(info):
    if not isinstance(info, UpdateInfo):
        raise UpdateError('更新信息无效。')
    _version_key(info.version)
    expected_name = f'GPUSelector-v{info.version}-windows-x64.exe'
    if (info.version.startswith('v') or info.tag_name != f'v{info.version}'
            or info.asset_name != expected_name
            or info.release_url != f'{REPOSITORY_URL}/releases/tag/{info.tag_name}'
            or info.download_url != f'{REPOSITORY_URL}/releases/download/{info.tag_name}/{expected_name}'
            or type(info.size) is not int or not 0 < info.size <= MAX_ASSET_BYTES
            or not isinstance(info.sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', info.sha256)):
        raise UpdateError('更新资产来源、大小或 SHA-256 校验信息无效。')


def _remaining_ms(deadline, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateError('已取消更新操作。')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise UpdateError('网络请求超时，请稍后重试。')
    return max(1, min(15000, int(remaining * 1000)))


def _https_url(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.port not in (None, 443) or parts.fragment
                or any(ord(ch) < 33 for ch in url) or '\\' in url):
            raise ValueError
        return parts
    except (TypeError, ValueError):
        raise UpdateError('拒绝不安全的更新地址。') from None


@contextmanager
def _request(url, deadline, cancel_event=None):
    """One HTTPS GET, with redirects disabled and handles closed on all exits."""
    parts = _https_url(url)
    if os.name != 'nt':
        raise UpdateError('在线更新需要 Windows。')
    dll = c.WinDLL('winhttp.dll', use_last_error=True, winmode=0x800)  # System32 only.
    handle, dword, pointer = c.c_void_p, c.c_uint32, c.c_void_p
    signatures = {
        'WinHttpOpen': ([c.c_wchar_p, dword, c.c_wchar_p, c.c_wchar_p, dword], handle),
        'WinHttpConnect': ([handle, c.c_wchar_p, c.c_ushort, dword], handle),
        'WinHttpOpenRequest': ([handle, c.c_wchar_p, c.c_wchar_p, c.c_wchar_p,
                                c.c_wchar_p, c.POINTER(c.c_wchar_p), dword], handle),
        'WinHttpSetTimeouts': ([handle, c.c_int, c.c_int, c.c_int, c.c_int], c.c_int),
        'WinHttpSetOption': ([handle, dword, pointer, dword], c.c_int),
        'WinHttpSendRequest': ([handle, c.c_wchar_p, dword, pointer, dword, dword, c.c_size_t], c.c_int),
        'WinHttpReceiveResponse': ([handle, pointer], c.c_int),
        'WinHttpQueryHeaders': ([handle, dword, c.c_wchar_p, pointer, c.POINTER(dword), pointer], c.c_int),
        'WinHttpReadData': ([handle, pointer, dword, c.POINTER(dword)], c.c_int),
        'WinHttpCloseHandle': ([handle], c.c_int),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = args, result

    def require(result):
        if not result:
            raise UpdateError(f'HTTPS 请求失败（Windows 错误 {c.get_last_error()}）。')
        return result

    def option(target, number, value):
        data = dword(value)
        require(dll.WinHttpSetOption(target, number, c.byref(data), c.sizeof(data)))

    opened = []
    try:
        session = require(dll.WinHttpOpen('GPUSelector-Updater/1.0', 4, None, None, 0))
        opened.append(session)  # Automatic proxy is supported on Windows 8.1+.
        timeout = _remaining_ms(deadline, cancel_event)
        require(dll.WinHttpSetTimeouts(session, timeout, timeout, timeout, timeout))
        option(session, 4, 1)  # CONNECT_RETRIES: keep failed connection attempts bounded.
        option(session, 84, 0x800)  # WINHTTP_OPTION_SECURE_PROTOCOLS: TLS 1.2.
        option(session, 88, 0)  # WINHTTP_OPTION_REDIRECT_POLICY: NEVER.
        connection = require(dll.WinHttpConnect(session, parts.hostname, 443, 0))
        opened.append(connection)
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        request = require(dll.WinHttpOpenRequest(connection, 'GET', path, None, None, None, 0x800000))
        opened.append(request)
        option(request, 77, 2)  # AUTOLOGON_SECURITY_LEVEL_HIGH: no default credentials.
        option(request, 63, 4)  # WINHTTP_DISABLE_AUTHENTICATION: no automatic auth retries.
        headers = 'Accept: application/vnd.github+json\r\nX-GitHub-Api-Version: 2022-11-28\r\n'
        _remaining_ms(deadline, cancel_event)
        require(dll.WinHttpSendRequest(request, headers, len(headers), None, 0, 0, 0))
        option(request, 6, _remaining_ms(deadline, cancel_event))
        require(dll.WinHttpReceiveResponse(request, None))
        _remaining_ms(deadline, cancel_event)
        status, size = dword(), dword(c.sizeof(dword))
        require(dll.WinHttpQueryHeaders(request, 19 | 0x20000000, None, c.byref(status), c.byref(size), None))
        response_headers = {}
        if status.value in (301, 302, 303, 307, 308):
            length = dword()
            dll.WinHttpQueryHeaders(request, 33, None, None, c.byref(length), None)
            if c.get_last_error() != 122 or not 0 < length.value <= 32768:
                raise UpdateError('更新重定向地址无效。')
            location = c.create_unicode_buffer(length.value // c.sizeof(c.c_wchar))
            require(dll.WinHttpQueryHeaders(request, 33, None, location, c.byref(length), None))
            response_headers['location'] = location.value

        def chunks():
            buffer, received = c.create_string_buffer(65536), dword()
            while True:
                option(request, 6, _remaining_ms(deadline, cancel_event))
                require(dll.WinHttpReadData(request, buffer, len(buffer), c.byref(received)))
                _remaining_ms(deadline, cancel_event)
                if not received.value:
                    break
                yield buffer.raw[:received.value]

        yield status.value, response_headers, chunks()
    finally:
        for opened_handle in reversed(opened):
            dll.WinHttpCloseHandle(opened_handle)


def _get_json(url, deadline, cancel_event=None):
    with _request(url, deadline, cancel_event) as (status, headers, chunks):
        if status != 200:
            raise UpdateError(f'GitHub 检查失败（HTTP {status}，可能是网络限制或请求频率限制）。')
        content = bytearray()
        for chunk in chunks:
            _remaining_ms(deadline, cancel_event)
            if len(content) + len(chunk) > MAX_METADATA_BYTES:
                raise UpdateError('GitHub 更新信息超过大小限制。')
            content.extend(chunk)
    try:
        return json.loads(content)
    except (ValueError, UnicodeError):
        raise UpdateError('GitHub 返回的更新信息不是有效 JSON。') from None


def check_for_update(current_version, *, cancel_event=None):
    """Return a newer release; stable installations stay on the stable channel."""
    current = _version_key(current_version)
    candidates, deadline = [], time.monotonic() + 60
    for page in range(1, 11):
        _remaining_ms(deadline, cancel_event)
        releases = _get_json(f'{RELEASES_URL}?per_page=100&page={page}', deadline, cancel_event)
        _remaining_ms(deadline, cancel_event)
        if not isinstance(releases, list):
            raise UpdateError('GitHub 更新列表格式无效。')
        for release in releases:
            if not isinstance(release, dict) or release.get('draft') is not False:
                continue
            tag = release.get('tag_name')
            try:
                key = _version_key(tag)
            except UpdateError:
                continue
            if current[3] == 3 and (key[3] != 3 or release.get('prerelease') is not False):
                continue
            if key > current:
                candidates.append((key, release))
        if len(releases) < 100:
            break
    else:
        raise UpdateError('GitHub 更新列表过长，无法确认最新版本。')
    if not candidates:
        return None
    release = max(candidates, key=lambda item: item[0])[1]
    tag = release['tag_name']
    version = tag.removeprefix('v')
    name = f'GPUSelector-v{version}-windows-x64.exe'
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise UpdateError('新版尚未提供完整的更新文件。')
    matches = [a for a in assets if isinstance(a, dict) and a.get('name') == name and a.get('state') == 'uploaded']
    if len(matches) != 1:
        raise UpdateError('新版尚未提供唯一、完整的 Windows x64 更新文件。')
    asset = matches[0]
    digest = asset.get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise UpdateError('GitHub 未提供有效的 SHA-256，已拒绝自动更新。')
    info = UpdateInfo(version, tag, release.get('html_url'), name,
                      asset.get('browser_download_url'), asset.get('size'), digest[7:].lower())
    _validate_info(info)
    return info


def download_update(info, directory, *, cancel_event=None):
    """Return a verified staged EXE; never modify the installed application."""
    from app_version import VERSION
    _validate_info(info)
    available, installed = _version_key(info.version), _version_key(VERSION)
    if available <= installed:
        raise UpdateError('拒绝下载相同版本或更旧版本。')
    if installed[3] == 3 and available[3] != 3:
        raise UpdateError('正式版本不会自动更新到测试版本。')
    deadline = time.monotonic() + 300
    _remaining_ms(deadline, cancel_event)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    partial = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.gpu-update-', suffix='.part', dir=directory, delete=False) as out:
            partial = Path(out.name)
            digest, count, url = hashlib.sha256(), 0, info.download_url
            for redirect in range(6):
                with _request(url, deadline, cancel_event) as (status, headers, chunks):
                    if status in (301, 302, 303, 307, 308):
                        target = urljoin(url, headers.get('location', ''))
                        parts = _https_url(target)
                        if (parts.hostname not in {'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
                                or target == url):
                            raise UpdateError('拒绝跳转到非 GitHub 更新下载服务器。')
                        url = target
                        continue
                    if status != 200:
                        raise UpdateError(f'更新下载失败（HTTP {status}）。')
                    for chunk in chunks:
                        _remaining_ms(deadline, cancel_event)
                        count += len(chunk)
                        if count > info.size:
                            raise UpdateError('更新文件大小超过 GitHub 声明。')
                        digest.update(chunk)
                        out.write(chunk)
                    break
            else:
                raise UpdateError('更新下载重定向次数过多。')
            if count != info.size or digest.hexdigest() != info.sha256:
                raise UpdateError('更新文件大小或 SHA-256 不一致，已删除下载文件。')
            out.flush()
            os.fsync(out.fileno())
        destination = directory / info.asset_name
        _remaining_ms(deadline, cancel_event)
        os.replace(partial, destination)
        partial = None
        return destination
    except OSError as exc:
        raise UpdateError(f'无法保存更新文件：{exc}') from exc
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
