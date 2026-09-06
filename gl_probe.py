"""Read-only WGL renderer probe. Run in a child process with an external timeout."""
import ctypes
from ctypes import wintypes as w
import os
import uuid


def probe():
    """Query the renderer of this process; never infer other applications' GPUs.

    GPU drivers are native code and can hang or crash. The caller must run this
    function in an isolated process and enforce a timeout on that process.
    """
    result = {
        'ok': False,
        'process_bits': ctypes.sizeof(ctypes.c_void_p) * 8,
        'limitation': '仅代表本次探测进程的 OpenGL 渲染器；不能证明其他程序、'
                      '32 位程序或 DirectX/Vulkan 使用同一显卡。',
    }
    if os.name != 'nt':
        result['error'] = '此探测仅支持 Windows。'
        return result

    class PixelFormat(ctypes.Structure):
        _fields_ = [
            ('nSize', w.WORD), ('nVersion', w.WORD), ('dwFlags', w.DWORD),
            ('iPixelType', w.BYTE), ('cColorBits', w.BYTE),
            ('cRedBits', w.BYTE), ('cRedShift', w.BYTE),
            ('cGreenBits', w.BYTE), ('cGreenShift', w.BYTE),
            ('cBlueBits', w.BYTE), ('cBlueShift', w.BYTE),
            ('cAlphaBits', w.BYTE), ('cAlphaShift', w.BYTE),
            ('cAccumBits', w.BYTE), ('cAccumRedBits', w.BYTE),
            ('cAccumGreenBits', w.BYTE), ('cAccumBlueBits', w.BYTE),
            ('cAccumAlphaBits', w.BYTE), ('cDepthBits', w.BYTE),
            ('cStencilBits', w.BYTE), ('cAuxBuffers', w.BYTE),
            ('iLayerType', w.BYTE), ('bReserved', w.BYTE),
            ('dwLayerMask', w.DWORD), ('dwVisibleMask', w.DWORD),
            ('dwDamageMask', w.DWORD),
        ]

    wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT,
                                     w.WPARAM, w.LPARAM)

    class WindowClass(ctypes.Structure):
        _fields_ = [
            ('style', w.UINT), ('lpfnWndProc', wndproc_type),
            ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
            ('hInstance', w.HINSTANCE), ('hIcon', w.HICON),
            ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH),
            ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR),
        ]

    hwnd = hdc = context = None
    registered = False
    class_name = 'GPUSelectorProbe_' + uuid.uuid4().hex
    stage = '加载 Windows OpenGL 接口'
    try:
        user = ctypes.WinDLL('user32', use_last_error=True)
        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        gl = ctypes.WinDLL('opengl32', use_last_error=True)

        kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        kernel.GetModuleHandleW.restype = w.HMODULE
        user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        user.DefWindowProcW.restype = ctypes.c_ssize_t
        user.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user.RegisterClassW.restype = w.ATOM
        user.UnregisterClassW.argtypes = [w.LPCWSTR, w.HINSTANCE]
        user.UnregisterClassW.restype = w.BOOL
        user.CreateWindowExW.argtypes = [
            w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID,
        ]
        user.CreateWindowExW.restype = w.HWND
        user.DestroyWindow.argtypes = [w.HWND]
        user.DestroyWindow.restype = w.BOOL
        user.GetDC.argtypes = [w.HWND]
        user.GetDC.restype = w.HDC
        user.ReleaseDC.argtypes = [w.HWND, w.HDC]
        user.ReleaseDC.restype = ctypes.c_int
        gdi.ChoosePixelFormat.argtypes = [w.HDC, ctypes.POINTER(PixelFormat)]
        gdi.ChoosePixelFormat.restype = ctypes.c_int
        gdi.SetPixelFormat.argtypes = [w.HDC, ctypes.c_int, ctypes.POINTER(PixelFormat)]
        gdi.SetPixelFormat.restype = w.BOOL
        gl.wglCreateContext.argtypes = [w.HDC]
        gl.wglCreateContext.restype = w.HANDLE
        gl.wglMakeCurrent.argtypes = [w.HDC, w.HANDLE]
        gl.wglMakeCurrent.restype = w.BOOL
        gl.wglDeleteContext.argtypes = [w.HANDLE]
        gl.wglDeleteContext.restype = w.BOOL
        gl.glGetString.argtypes = [w.UINT]
        gl.glGetString.restype = ctypes.c_char_p

        def checked(value):
            if not value:
                error = ctypes.get_last_error()
                raise OSError(error, ctypes.FormatError(error).strip())
            return value

        # CS_OWNDC keeps the hidden window's device context stable until cleanup.
        callback = wndproc_type(user.DefWindowProcW)
        instance = checked(kernel.GetModuleHandleW(None))
        window_class = WindowClass(style=0x20, lpfnWndProc=callback,
                                   hInstance=instance, lpszClassName=class_name)
        stage = '注册探测窗口'
        checked(user.RegisterClassW(ctypes.byref(window_class)))
        registered = True
        stage = '创建隐藏探测窗口'
        hwnd = checked(user.CreateWindowExW(0, class_name, '', 0, 0, 0, 1, 1,
                                           None, None, instance, None))
        stage = '获取窗口设备上下文'
        hdc = checked(user.GetDC(hwnd))
        pixel_format = PixelFormat(nSize=ctypes.sizeof(PixelFormat), nVersion=1,
                                   dwFlags=0x4 | 0x20 | 0x1,
                                   cColorBits=24, cDepthBits=24)
        stage = '选择 OpenGL 像素格式'
        index = checked(gdi.ChoosePixelFormat(hdc, ctypes.byref(pixel_format)))
        stage = '设置 OpenGL 像素格式'
        checked(gdi.SetPixelFormat(hdc, index, ctypes.byref(pixel_format)))
        stage = '创建 OpenGL 上下文'
        context = checked(gl.wglCreateContext(hdc))
        stage = '激活 OpenGL 上下文'
        checked(gl.wglMakeCurrent(hdc, context))
        stage = '读取 OpenGL 渲染器'
        for key, token in [('vendor', 0x1F00), ('renderer', 0x1F01), ('version', 0x1F02)]:
            value = gl.glGetString(token)
            if not value:
                raise RuntimeError('OpenGL 未返回 ' + key)
            result[key] = value.decode('utf-8', errors='replace')
        result['ok'] = True
    except (OSError, RuntimeError) as exc:
        result['error'] = stage + '失败：' + str(exc)
    finally:
        if context:
            gl.wglMakeCurrent(None, None)
            gl.wglDeleteContext(context)
        if hdc:
            user.ReleaseDC(hwnd, hdc)
        if hwnd:
            user.DestroyWindow(hwnd)
        if registered:
            user.UnregisterClassW(class_name, instance)
    return result
