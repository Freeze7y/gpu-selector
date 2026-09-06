"""Read currently present PCI device instances through Windows Configuration Manager."""
import ctypes
from ctypes import wintypes

CM_GETIDLIST_FILTER_ENUMERATOR = 0x00000001
CM_GETIDLIST_FILTER_PRESENT = 0x00000100
CR_SUCCESS = 0x00000000
CR_BUFFER_SMALL = 0x0000001A


def present_pci_ids():
    """Return uppercase PCI instance IDs; an enumeration failure raises OSError."""
    cfg = ctypes.WinDLL('cfgmgr32')
    get_size = cfg.CM_Get_Device_ID_List_SizeW
    get_size.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR, wintypes.ULONG]
    get_size.restype = wintypes.ULONG
    get_list = cfg.CM_Get_Device_ID_ListW
    get_list.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.ULONG, wintypes.ULONG]
    get_list.restype = wintypes.ULONG
    flags = CM_GETIDLIST_FILTER_ENUMERATOR | CM_GETIDLIST_FILTER_PRESENT
    # Device arrival between the size and list calls can require a larger buffer.
    for _ in range(3):
        length = wintypes.ULONG()
        result = get_size(ctypes.byref(length), 'PCI', flags)
        if result != CR_SUCCESS:
            raise OSError(f'无法读取当前 PCI 设备列表大小：CONFIGRET=0x{result:08X}')
        buffer = ctypes.create_unicode_buffer(length.value)
        result = get_list('PCI', buffer, length.value, flags)
        if result == CR_SUCCESS:
            return {item.upper() for item in buffer[:].split('\0') if item}
        if result != CR_BUFFER_SMALL:
            raise OSError(f'无法读取当前 PCI 设备列表：CONFIGRET=0x{result:08X}')
    raise OSError('PCI 设备列表在读取期间持续变化，请刷新后重试。')
