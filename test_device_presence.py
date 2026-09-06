import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import patch

from device_presence import present_pci_ids


class Function:
    def __init__(self, callback):
        self.callback = callback
    def __call__(self, *args):
        return self.callback(*args)


class Config:
    def __init__(self, payload='pci\\A\\1\0PCI\\B\\2\0\0', size_result=0, list_results=None):
        self.payload = payload
        self.size_result = size_result
        self.list_results = list_results or [0]
        self.size_calls = 0
        self.list_calls = 0
        self.CM_Get_Device_ID_List_SizeW = Function(self.size)
        self.CM_Get_Device_ID_ListW = Function(self.ids)
    def size(self, length, enumerator, flags):
        assert enumerator == 'PCI' and flags == 0x101
        self.size_calls += 1
        ctypes.cast(length, ctypes.POINTER(wintypes.ULONG))[0] = len(self.payload)
        return self.size_result
    def ids(self, enumerator, buffer, length, flags):
        assert enumerator == 'PCI' and flags == 0x101
        result = self.list_results[min(self.list_calls, len(self.list_results) - 1)]
        self.list_calls += 1
        if result == 0:
            for i, ch in enumerate(self.payload):
                buffer[i] = ch
        return result


class PresenceTests(unittest.TestCase):
    def call(self, config):
        with patch('device_presence.ctypes.WinDLL', return_value=config):
            return present_pci_ids()
    def test_all_multisz_entries_and_case_normalization(self):
        self.assertEqual(self.call(Config()), {'PCI\\A\\1', 'PCI\\B\\2'})
    def test_successful_empty_list(self):
        self.assertEqual(self.call(Config(payload='\0\0')), set())
    def test_size_failure_is_not_empty_list(self):
        with self.assertRaisesRegex(OSError, '0x00000033'):
            self.call(Config(size_result=0x33))
    def test_list_failure_is_not_empty_list(self):
        with self.assertRaisesRegex(OSError, '0x0000001D'):
            self.call(Config(list_results=[0x1d]))
    def test_buffer_growth_repeats_size_query(self):
        config = Config(list_results=[0x1a, 0])
        self.assertEqual(len(self.call(config)), 2)
        self.assertEqual(config.size_calls, 2)
    def test_continuous_buffer_growth_fails_boundedly(self):
        config = Config(list_results=[0x1a])
        with self.assertRaises(OSError):
            self.call(config)
        self.assertEqual(config.list_calls, 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
