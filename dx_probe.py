"""Read-only Direct3D 11 device and offscreen clear/readback probe.

Run this module only in a child process with an external timeout. Display
drivers are native code and can hang or crash outside Python's exception model.
COM slots and structures follow Microsoft's Windows SDK d3d11.h and dxgi.h.
"""
import ctypes as c
import json
import os
from pathlib import Path
import sys
import uuid


class Guid(c.Structure):
    _fields_ = [('data1', c.c_uint32), ('data2', c.c_uint16),
                ('data3', c.c_uint16), ('data4', c.c_ubyte * 8)]


class Luid(c.Structure):
    _fields_ = [('low', c.c_uint32), ('high', c.c_int32)]


class AdapterDesc(c.Structure):
    _fields_ = [('description', c.c_wchar * 128), ('vendor_id', c.c_uint32),
                ('device_id', c.c_uint32), ('subsystem_id', c.c_uint32),
                ('revision', c.c_uint32), ('dedicated_video', c.c_size_t),
                ('dedicated_system', c.c_size_t), ('shared_system', c.c_size_t),
                ('luid', Luid)]


class SampleDesc(c.Structure):
    _fields_ = [('count', c.c_uint32), ('quality', c.c_uint32)]


class TextureDesc(c.Structure):
    _fields_ = [('width', c.c_uint32), ('height', c.c_uint32),
                ('mip_levels', c.c_uint32), ('array_size', c.c_uint32),
                ('format', c.c_uint32), ('sample', SampleDesc),
                ('usage', c.c_uint32), ('bind_flags', c.c_uint32),
                ('cpu_access_flags', c.c_uint32), ('misc_flags', c.c_uint32)]


class MappedResource(c.Structure):
    _fields_ = [('data', c.c_void_p), ('row_pitch', c.c_uint32),
                ('depth_pitch', c.c_uint32)]


def _method(pointer, slot, result_type, *arg_types):
    table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
    return c.WINFUNCTYPE(result_type, c.c_void_p, *arg_types)(table[slot])


def _checked(hresult):
    if hresult < 0:
        raise OSError('HRESULT 0x%08X' % (hresult & 0xffffffff))


def _read_pixels(mapped, width, height):
    """Respect driver row padding; reject invalid or incomplete mapped data."""
    if not mapped.data or mapped.row_pitch < width * 4:
        raise RuntimeError('Direct3D 返回无效的像素映射。')
    return [list(c.string_at(mapped.data + row * mapped.row_pitch + col * 4, 4))
            for row in range(height) for col in range(width)]


def probe():
    result = {
        'ok': False, 'api': 'Direct3D 11',
        'process_bits': c.sizeof(c.c_void_p) * 8,
        'limitation': '仅代表本次探测进程通过 D3D11 默认硬件适配器创建的设备；'
                      '已验证离屏清色和像素回读，不是完整游戏渲染或性能测试。'
                      '不代表其他应用、DirectX 12、OpenGL 或 Vulkan 的实际用卡。',
    }
    if os.name != 'nt':
        result['error'] = '此探测仅支持 Windows。'
        return result

    device, context, dxgi_device, adapter, texture, view, staging = (
        c.c_void_p() for _ in range(7))
    resources = [device, context, dxgi_device, adapter, texture, view, staging]
    stage = '加载 Direct3D 11'
    is_mapped = False
    try:
        d3d = c.WinDLL('d3d11.dll')
        create = d3d.D3D11CreateDevice
        create.argtypes = [c.c_void_p, c.c_uint32, c.c_void_p, c.c_uint32,
                           c.POINTER(c.c_uint32), c.c_uint32, c.c_uint32,
                           c.POINTER(c.c_void_p), c.POINTER(c.c_uint32),
                           c.POINTER(c.c_void_p)]
        create.restype = c.c_int32
        level = c.c_uint32()
        # No explicit adapter: test this process's default hardware adapter.
        # Do not silently fall back to WARP/software when hardware fails.
        stage = '创建默认硬件设备'
        _checked(create(None, 1, None, 0, None, 0, 7, c.byref(device),
                        c.byref(level), c.byref(context)))
        result['version'] = '%d_%d' % ((level.value >> 12) & 0xf,
                                       (level.value >> 8) & 0xf)
        result['feature_level'] = result['version']
        result['feature_level_hex'] = '0x%04X' % level.value

        stage = '读取实际设备对应的 DXGI 适配器'
        iid = Guid.from_buffer_copy(
            uuid.UUID('54ec77fa-1377-44e6-8c32-88fd5f44c84c').bytes_le)
        _checked(_method(device, 0, c.c_int32, c.POINTER(Guid),
                         c.POINTER(c.c_void_p))(
                             device, c.byref(iid), c.byref(dxgi_device)))
        _checked(_method(dxgi_device, 7, c.c_int32, c.POINTER(c.c_void_p))(
            dxgi_device, c.byref(adapter)))
        desc = AdapterDesc()
        _checked(_method(adapter, 8, c.c_int32, c.POINTER(AdapterDesc))(
            adapter, c.byref(desc)))
        result.update({
            'renderer': desc.description, 'adapter': desc.description,
            'vendor': {0x10de: 'NVIDIA', 0x1002: 'AMD', 0x8086: 'Intel',
                       0x1414: 'Microsoft'}.get(desc.vendor_id,
                                               '0x%04X' % desc.vendor_id),
            'vendor_id': '0x%04X' % desc.vendor_id,
            'device_id': '0x%04X' % desc.device_id,
            'adapter_luid': '0x%08X_0x%08X' %
                            (desc.luid.high & 0xffffffff, desc.luid.low),
            'dedicated_video_mib': desc.dedicated_video // (1024 * 1024),
        })

        # R8G8B8A8_UNORM render target; endpoint colors avoid rounding variance.
        stage = '创建离屏纹理'
        texture_desc = TextureDesc(width=2, height=2, mip_levels=1, array_size=1,
                                   format=28, sample=SampleDesc(1, 0),
                                   usage=0, bind_flags=0x20)
        make_texture = _method(device, 5, c.c_int32, c.POINTER(TextureDesc),
                               c.c_void_p, c.POINTER(c.c_void_p))
        _checked(make_texture(device, c.byref(texture_desc), None,
                              c.byref(texture)))
        _checked(_method(device, 9, c.c_int32, c.c_void_p, c.c_void_p,
                         c.POINTER(c.c_void_p))(
                             device, texture, None, c.byref(view)))
        texture_desc.usage = 3  # D3D11_USAGE_STAGING
        texture_desc.bind_flags = 0
        texture_desc.cpu_access_flags = 0x20000  # D3D11_CPU_ACCESS_READ
        _checked(make_texture(device, c.byref(texture_desc), None,
                              c.byref(staging)))

        stage = '执行离屏清色并回读像素'
        color = (c.c_float * 4)(1.0, 0.0, 1.0, 1.0)
        _method(context, 50, None, c.c_void_p, c.POINTER(c.c_float))(
            context, view, color)
        _method(context, 47, None, c.c_void_p, c.c_void_p)(
            context, staging, texture)
        mapped = MappedResource()
        _checked(_method(context, 14, c.c_int32, c.c_void_p, c.c_uint32,
                         c.c_uint32, c.c_uint32, c.POINTER(MappedResource))(
                             context, staging, 0, 1, 0, c.byref(mapped)))
        is_mapped = True
        pixels = _read_pixels(mapped, 2, 2)
        expected = [255, 0, 255, 255]
        result['render_test'] = {
            'passed': all(pixel == expected for pixel in pixels),
            'method': '2×2 RGBA8 离屏纹理清色 → GPU 复制 → CPU 像素回读',
            'expected_rgba': expected, 'actual_rgba': pixels[0],
            'verified_pixels': len(pixels),
        }
        if not result['render_test']['passed']:
            raise RuntimeError('离屏纹理回读颜色不符合预期。')
        result['ok'] = True
    except (OSError, RuntimeError, ValueError) as exc:
        result['error'] = stage + '失败：' + str(exc)
    finally:
        if is_mapped:
            _method(context, 15, None, c.c_void_p, c.c_uint32)(context, staging, 0)
        for resource in reversed(resources):
            if resource:
                _method(resource, 2, c.c_uint32)(resource)
    return result


if __name__ == '__main__':
    payload = json.dumps(probe(), ensure_ascii=False, indent=2)
    if len(sys.argv) == 2:
        Path(sys.argv[1]).write_text(payload, encoding='utf-8')
    else:
        print(payload)
