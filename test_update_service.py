import ctypes as c
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import app_version
import update_service as service


PAYLOAD = b'MZ-test-release-executable'


def release(version='3.0.0', payload=PAYLOAD):
    tag = 'v' + version
    name = f'GPUSelector-v{version}-windows-x64.exe'
    return {'tag_name': tag, 'draft': False, 'prerelease': '-' in version,
            'html_url': f'{service.REPOSITORY_URL}/releases/tag/{tag}',
            'assets': [{'name': name, 'state': 'uploaded', 'size': len(payload),
                        'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
                        'browser_download_url': f'{service.REPOSITORY_URL}/releases/download/{tag}/{name}'}]}


def info(version='3.0.0', payload=PAYLOAD):
    item = release(version, payload)
    asset = item['assets'][0]
    return service.UpdateInfo(version, item['tag_name'], item['html_url'], asset['name'],
                              asset['browser_download_url'], len(payload), asset['digest'][7:])


@contextmanager
def response(status=200, headers=None, chunks=None):
    yield status, headers or {}, iter([PAYLOAD] if chunks is None else chunks)


class CheckTests(unittest.TestCase):
    def check(self, current, releases):
        with patch.object(service, '_get_json', return_value=releases):
            return service.check_for_update(current)

    def test_numeric_version_order(self):
        result = self.check('2.9.0', [release('2.10.0'), release('2.9.9')])
        self.assertEqual(result.version, '2.10.0')

    def test_prerelease_order_and_number(self):
        versions = ['2.1.0-alpha', '2.1.0-beta', '2.1.0-beta.2', '2.1.0-beta.10', '2.1.0-rc', '2.1.0']
        self.assertEqual(sorted(versions, key=service._version_key), versions)
        self.assertEqual(self.check('2.1.0-beta', [release(v) for v in versions]).version, '2.1.0')

    def test_stable_skips_prerelease_and_selects_stable(self):
        result = self.check('2.1.0', [release('4.0.0-beta'), release('2.2.0')])
        self.assertEqual(result.version, '2.2.0')

    def test_stable_skips_prerelease_flag_on_stable_tag(self):
        item = release('3.0.0')
        item['prerelease'] = True
        self.assertIsNone(self.check('2.1.0', [item]))

    def test_stable_skips_beta_tag_even_if_flag_is_false(self):
        item = release('3.0.0-beta')
        item['prerelease'] = False
        self.assertIsNone(self.check('2.1.0', [item]))

    def test_beta_can_get_higher_beta(self):
        self.assertEqual(self.check('2.1.0-beta', [release('2.2.0-beta')]).version, '2.2.0-beta')

    def test_no_downgrade_same_or_older(self):
        self.assertIsNone(self.check('3.0.0', [release('2.10.0'), release('3.0.0'), release('3.0.0-rc')]))

    def test_draft_and_nonversion_tags_ignored(self):
        draft = release('8.0.0')
        draft['draft'] = True
        other = release('9.0.0')
        other['tag_name'] = 'nightly'
        self.assertIsNone(self.check('3.0.0', [draft, other]))

    def test_invalid_current_version_fails_before_network(self):
        with patch.object(service, '_get_json') as network:
            for value in ('oops', '1.2', '01.2.3', '../3.0.0', None):
                with self.subTest(value=value), self.assertRaises(service.UpdateError):
                    service.check_for_update(value)
            network.assert_not_called()

    def test_releases_endpoint_includes_pagination(self):
        with patch.object(service, '_get_json', side_effect=[[release('1.0.0')] * 100, [release('3.0.0')]]) as network:
            self.assertEqual(service.check_for_update('2.1.0').version, '3.0.0')
        self.assertEqual(network.call_args_list[0].args[0], service.RELEASES_URL + '?per_page=100&page=1')
        self.assertIn('page=2', network.call_args_list[1].args[0])

    def test_missing_and_invalid_digests_fail_closed(self):
        for digest in (None, '', 'md5:' + 'a' * 32, 'sha256:' + 'z' * 64):
            item = release()
            item['assets'][0]['digest'] = digest
            with self.subTest(digest=digest), self.assertRaises(service.UpdateError):
                self.check('2.1.0', [item])

    def test_exact_asset_name_required(self):
        item = release()
        item['assets'][0]['name'] = 'GPU默认显卡选择器.exe'
        with self.assertRaises(service.UpdateError):
            self.check('2.1.0', [item])

    def test_wrong_repository_and_size_rejected(self):
        for field, value in [('html_url', 'https://github.com/other/repo/releases/tag/v3.0.0'),
                             ('browser_download_url', 'https://evil.invalid/update.exe'),
                             ('size', 0), ('size', True), ('size', service.MAX_ASSET_BYTES + 1)]:
            item = release()
            target = item if field == 'html_url' else item['assets'][0]
            target[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(service.UpdateError):
                self.check('2.1.0', [item])

    def test_duplicate_matching_assets_rejected(self):
        item = release()
        item['assets'].append(item['assets'][0].copy())
        with self.assertRaises(service.UpdateError):
            self.check('2.1.0', [item])

    def test_bad_json_and_http_rate_limit(self):
        for status, body in [(403, b'{}'), (429, b'{}'), (200, b'not-json')]:
            with self.subTest(status=status), patch.object(service, '_request', return_value=response(status, chunks=[body])):
                with self.assertRaises(service.UpdateError):
                    service.check_for_update('2.1.0')

    def test_metadata_size_cap(self):
        with patch.object(service, 'MAX_METADATA_BYTES', 3), patch.object(service, '_request', return_value=response(chunks=[b'1234'])):
            with self.assertRaises(service.UpdateError):
                service.check_for_update('2.1.0')

    def test_bad_list_and_unbounded_pagination_rejected(self):
        with self.assertRaises(service.UpdateError):
            self.check('2.1.0', {'message': 'error'})
        with self.assertRaises(service.UpdateError):
            self.check('2.1.0', [release('1.0.0')] * 100)

    def test_cancelled_check_does_not_request_network(self):
        event = threading.Event()
        event.set()
        with patch.object(service, '_request') as network, self.assertRaisesRegex(service.UpdateError, '取消'):
            service.check_for_update('2.1.0', cancel_event=event)
        network.assert_not_called()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.version = patch.object(app_version, 'VERSION', '2.1.0')
        self.version.start()
        self.addCleanup(self.version.stop)

    def test_successful_stream_size_hash_and_rename(self):
        with patch.object(service, '_request', return_value=response(chunks=[PAYLOAD[:3], PAYLOAD[3:]])):
            result = service.download_update(info(), self.directory)
        self.assertEqual(result.name, info().asset_name)
        self.assertEqual(result.read_bytes(), PAYLOAD)
        self.assertEqual(list(self.directory.iterdir()), [result])

    def test_wrong_hash_truncated_or_oversized_cleanup(self):
        for content in (b'x' * len(PAYLOAD), PAYLOAD[:-1], PAYLOAD + b'extra'):
            with self.subTest(content=content), patch.object(service, '_request', return_value=response(chunks=[content])):
                with self.assertRaises(service.UpdateError):
                    service.download_update(info(), self.directory)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_network_failure_cleanup_preserves_existing_file(self):
        target = self.directory / info().asset_name
        target.write_bytes(b'existing')
        def chunks():
            yield PAYLOAD[:2]
            raise service.UpdateError('timeout')
        with patch.object(service, '_request', return_value=response(chunks=chunks())):
            with self.assertRaises(service.UpdateError):
                service.download_update(info(), self.directory)
        self.assertEqual(target.read_bytes(), b'existing')
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_github_asset_redirect_allowed(self):
        destination = 'https://release-assets.githubusercontent.com/github-production-release-asset/1/file?sig=123'
        with patch.object(service, '_request', side_effect=[response(302, {'location': destination}), response()]) as network:
            result = service.download_update(info(), self.directory)
        self.assertEqual(network.call_args_list[1].args[0], destination)
        self.assertEqual(result.read_bytes(), PAYLOAD)

    def test_external_http_credentials_and_spoofed_hosts_rejected(self):
        for destination in ('https://evil.invalid/file', 'http://release-assets.githubusercontent.com/file',
                            'https://release-assets.githubusercontent.com.evil.invalid/file',
                            'https://user:pass@release-assets.githubusercontent.com/file',
                            'https://release-assets.githubusercontent.com:444/file',
                            'https://release-assets.githubusercontent.com/file#fragment'):
            with self.subTest(destination=destination), patch.object(service, '_request', return_value=response(302, {'location': destination})) as network:
                with self.assertRaises(service.UpdateError):
                    service.download_update(info(), self.directory)
                self.assertEqual(network.call_count, 1)
            self.assertEqual(list(self.directory.iterdir()), [])

    def test_repeated_redirects_are_bounded(self):
        redirects = [response(302, {'location': f'https://objects.githubusercontent.com/file{i}'}) for i in range(6)]
        with patch.object(service, '_request', side_effect=redirects):
            with self.assertRaises(service.UpdateError):
                service.download_update(info(), self.directory)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_download_revalidates_version_and_source(self):
        bad = [info('2.1.0'), info('2.0.0'), info('4.0.0-beta'), replace(info(), asset_name='../evil.exe'),
               replace(info(), download_url='https://evil.invalid/file')]
        with patch.object(service, '_request') as network:
            for item in bad:
                with self.subTest(item=item), self.assertRaises(service.UpdateError):
                    service.download_update(item, self.directory)
            network.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cancel_during_download_cleans_partial(self):
        event = threading.Event()
        def chunks():
            yield PAYLOAD[:2]
            event.set()
            yield PAYLOAD[2:]
        with patch.object(service, '_request', return_value=response(chunks=chunks())):
            with self.assertRaisesRegex(service.UpdateError, '取消'):
                service.download_update(info(), self.directory, cancel_event=event)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_non_200_and_deadline_errors(self):
        with patch.object(service, '_request', return_value=response(404)):
            with self.assertRaises(service.UpdateError):
                service.download_update(info(), self.directory)
        with self.assertRaises(service.UpdateError):
            service._remaining_ms(time.monotonic() - 1)
        self.assertEqual(list(self.directory.iterdir()), [])


class WinHttpTests(unittest.TestCase):
    def test_failed_send_closes_handles_and_sets_tls_and_redirect_policy(self):
        class Function:
            def __init__(self, callback):
                self.callback = callback
            def __call__(self, *args):
                return self.callback(*args)
        class Library:
            pass
        dll = Library()
        closed, options = [], []
        methods = {'WinHttpOpen': lambda *args: 1, 'WinHttpConnect': lambda *args: 2,
                   'WinHttpOpenRequest': lambda *args: 3, 'WinHttpSetTimeouts': lambda *args: 1,
                   'WinHttpSetOption': lambda h, n, p, s: options.append((n, c.cast(p, c.POINTER(c.c_uint32)).contents.value)) or 1,
                   'WinHttpSendRequest': lambda *args: 0, 'WinHttpReceiveResponse': lambda *args: 1,
                   'WinHttpQueryHeaders': lambda *args: 1, 'WinHttpReadData': lambda *args: 1,
                   'WinHttpCloseHandle': lambda h: closed.append(h) or 1}
        for name, method in methods.items():
            setattr(dll, name, Function(method))
        with patch.object(service.c, 'WinDLL', return_value=dll), patch.object(service.c, 'get_last_error', return_value=12029):
            with self.assertRaisesRegex(service.UpdateError, '12029'):
                with service._request(service.RELEASES_URL, time.monotonic() + 60):
                    self.fail('failed send cannot yield a response')
        self.assertEqual(closed, [3, 2, 1])
        self.assertIn((84, 0x800), options)
        self.assertIn((88, 0), options)
        self.assertIn((77, 2), options)
        self.assertIn((63, 4), options)
        self.assertNotIn(31, [number for number, _ in options])  # No certificate-ignore flags.

    def test_stream_read_uses_remaining_deadline_and_closes_after_cancel(self):
        class Function:
            def __init__(self, callback):
                self.callback = callback
            def __call__(self, *args):
                return self.callback(*args)
        class Library:
            pass
        event = threading.Event()
        dll = Library()
        closed, receive_timeouts = [], []
        def option(handle, number, value, size):
            if number == 6:
                receive_timeouts.append(c.cast(value, c.POINTER(c.c_uint32)).contents.value)
            return 1
        def headers(handle, kind, name, value, size, index):
            c.cast(value, c.POINTER(c.c_uint32)).contents.value = 200
            return 1
        def read(handle, buffer, size, received):
            c.memmove(buffer, PAYLOAD, len(PAYLOAD))
            c.cast(received, c.POINTER(c.c_uint32)).contents.value = len(PAYLOAD)
            event.set()
            return 1
        methods = {'WinHttpOpen': lambda *args: 1, 'WinHttpConnect': lambda *args: 2,
                   'WinHttpOpenRequest': lambda *args: 3, 'WinHttpSetTimeouts': lambda *args: 1,
                   'WinHttpSetOption': option, 'WinHttpSendRequest': lambda *args: 1,
                   'WinHttpReceiveResponse': lambda *args: 1, 'WinHttpQueryHeaders': headers,
                   'WinHttpReadData': read, 'WinHttpCloseHandle': lambda h: closed.append(h) or 1}
        for name, method in methods.items():
            setattr(dll, name, Function(method))
        with patch.object(service.c, 'WinDLL', return_value=dll), patch.object(service.time, 'monotonic', return_value=1000):
            with self.assertRaisesRegex(service.UpdateError, '取消'):
                with service._request(service.RELEASES_URL, 1000.1, event) as (status, _, chunks):
                    self.assertEqual(status, 200)
                    list(chunks)
        self.assertEqual(closed, [3, 2, 1])
        self.assertTrue(receive_timeouts)
        self.assertTrue(all(0 < value <= 101 for value in receive_timeouts))


if __name__ == '__main__':
    unittest.main()
