"""Entry point for the bundled, isolated 32-bit OpenGL probe."""
import json
from pathlib import Path
import sys


def main():
    sys.dont_write_bytecode = True
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python.exe runner.py output.json')
    if sys.maxsize > 2**32:
        result = {'ok': False, 'api': 'OpenGL', 'process_bits': 64,
                  'error': '32 位探针必须使用附带的 32 位 Python 运行时。'}
    else:
        from gl_probe import probe
        result = probe()
        result['api'] = 'OpenGL'
        result['limitation'] = (
            '仅代表本次 32 位探测进程的 OpenGL 渲染器；'
            '不能证明其他程序、64 位程序或 DirectX/Vulkan 使用同一显卡。')
    Path(sys.argv[1]).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                               encoding='utf-8')


if __name__ == '__main__':
    main()
