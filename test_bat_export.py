import base64
import json
import os
from pathlib import Path
import subprocess
import unittest

from bat_export import DX_FUNCTION, build_bat


def decode_payload(bat):
    chunks = [line.removeprefix('::GPU_DATA:') for line in bat.splitlines() if line.startswith('::GPU_DATA:')]
    return base64.b64decode(''.join(chunks)).decode('utf-16le')


def powershell(script):
    path = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not path.is_file():
        raise unittest.SkipTest('Windows PowerShell is not available')
    script = '[Console]::OutputEncoding = [Text.UTF8Encoding]::new();\n' + script
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    result = subprocess.run([str(path), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class BatExportTests(unittest.TestCase):
    def test_dx_preserves_preferences_at_execution_time(self):
        # Execute only the pure string helper, never the exported registry code.
        script = DX_FUNCTION + r'''
$cases = @(
    (Get-DxSetting 'HighPerfAdapter=OLD;SwapEffectUpgradeEnable=1;AutoHDREnable=1;VRROptimizeEnable=1;' 'NEW'),
    (Get-DxSetting 'Other=7;highperfadapter=OLD;HIGHPerfAdapter=OLDER;' 'NEW'),
    (Get-DxSetting '' 'NEW')
)
ConvertTo-Json -InputObject $cases -Compress
'''
        self.assertEqual(json.loads(powershell(script)), [
            'HighPerfAdapter=NEW;SwapEffectUpgradeEnable=1;AutoHDREnable=1;VRROptimizeEnable=1;',
            'HighPerfAdapter=NEW;Other=7;SwapEffectUpgradeEnable=0;',
            'HighPerfAdapter=NEW;SwapEffectUpgradeEnable=0;',
        ])

    def test_unicode_and_metacharacters_are_in_encoded_payload_only(self):
        dll = 'C:\\驱动 & 100%\\O\'Brien!"a.dll'
        plan = [{'root': 'HKLM', 'path': 'SOFTWARE\\Example', 'name': 'DLL', 'view': 32, 'value': [dll, 1]}]
        bat = build_bat('GL', plan=plan)
        payload = decode_payload(bat)
        self.assertTrue(bat.isascii())
        self.assertNotIn(dll, bat)
        self.assertIn("O''Brien", payload)
        self.assertIn('Registry64', payload)
        self.assertIn('Registry32', payload)
        self.assertIn('DoNotExpandEnvironmentNames', payload)
        self.assertIn('GetValueKind', payload)
        self.assertIn('Sysnative', bat)
        self.assertIn('%SystemRoot%\\System32\\WindowsPowerShell', bat)
        self.assertIn(r'\v1.0\powershell.exe', bat)
        self.assertNotIn('\v', bat)
        self.assertIn('DisableDelayedExpansion', bat)
        # Evaluate only JSON decoding, with no registry functions or operations.
        plan_line = next(line for line in payload.splitlines() if line.startswith('$plan = ConvertFrom-Json'))
        restored = json.loads(powershell(plan_line + '\nConvertTo-Json -InputObject @($plan | ForEach-Object { $_ }) -Depth 10 -Compress'))
        self.assertEqual(restored, plan)

    def test_large_plans_stay_under_cmd_line_limit(self):
        plan = [{'root': 'HKLM', 'path': 'SOFTWARE\\Example\\' + str(i), 'name': 'DLL',
                 'view': 64, 'value': ['C:\\' + ('longpath\\' * 30) + 'driver.dll', 1]} for i in range(100)]
        bat = build_bat('GL', plan=plan)
        self.assertGreater(len(bat), 8191)
        self.assertLess(max(map(len, bat.splitlines())), 8191)
        self.assertIn('Example', decode_payload(bat))

    def test_payload_and_bootstrap_parse_without_execution(self):
        plan = [{'root': 'HKLM', 'path': 'SOFTWARE\\Example', 'name': 'DLL', 'view': 32, 'value': ['中文.dll', 1]},
                {'root': 'HKLM', 'path': 'SOFTWARE\\Example', 'name': 'Old', 'view': 64, 'value': None}]
        for bat in (build_bat('DX', did='10DE&ABCD&12345678'), build_bat('GL', plan=plan)):
            encoded = next(line.split('-EncodedCommand ', 1)[1] for line in bat.splitlines() if '-EncodedCommand ' in line)
            for script in (base64.b64decode(encoded).decode('utf-16le'), decode_payload(bat)):
                data = base64.b64encode(script.encode('utf-16le')).decode('ascii')
                check = "$s = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('" + data + "')); "
                check += '$tokens = $null; $errors = $null; '
                check += '[void][System.Management.Automation.Language.Parser]::ParseInput($s, [ref]$tokens, [ref]$errors); '
                check += 'if ($errors.Count) { throw ($errors | Out-String) }; Write-Output OK'
                self.assertEqual(powershell(check), 'OK')

    def test_invalid_mode_and_missing_input(self):
        for mode, kwargs in [('other', {}), ('DX', {}), ('GL', {})]:
            with self.assertRaises(ValueError):
                build_bat(mode, **kwargs)


if __name__ == '__main__':
    unittest.main()
