"""Standalone BAT export with Unicode-safe PowerShell registry operations."""
import base64
import json
import textwrap


DX_FUNCTION = r'''
function Get-DxSetting([string]$current, [string]$did) {
    $fields = @($current.Split(';') | Where-Object {
        $_ -and $_.Split('=')[0].Trim() -ine 'HighPerfAdapter'
    })
    if (-not @($fields | Where-Object {
        $_.Split('=')[0].Trim() -ieq 'SwapEffectUpgradeEnable'
    }).Count) {
        $fields += 'SwapEffectUpgradeEnable=0'
    }
    return 'HighPerfAdapter=' + $did + ';' + ($fields -join ';') + ';'
}
'''

APPLY_FUNCTION = r'''
function Apply-RegistryOperation($op) {
    $hive = if ($op.root -eq 'HKLM') {
        [Microsoft.Win32.RegistryHive]::LocalMachine
    } else {
        [Microsoft.Win32.RegistryHive]::CurrentUser
    }
    $view = if ($op.view -eq 64) {
        [Microsoft.Win32.RegistryView]::Registry64
    } else {
        [Microsoft.Win32.RegistryView]::Registry32
    }
    $root = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
    $key = $null
    try {
        if ($null -eq $op.value) {
            $key = $root.OpenSubKey([string]$op.path, $true)
            if ($null -ne $key) {
                $key.DeleteValue([string]$op.name, $false)
                if ($key.GetValueNames() -contains $op.name) {
                    throw ('Delete verification failed: ' + $op.path + ' / ' + $op.name)
                }
            }
        } else {
            $kind = [Microsoft.Win32.RegistryValueKind][int]$op.value[1]
            $data = $op.value[0]
            switch ([int]$kind) {
                1 { $data = [string]$data }
                2 { $data = [string]$data }
                3 { $data = [byte[]]$data }
                4 { $data = [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$data), 0) }
                7 { $data = [string[]]@($data) }
                11 { $data = [BitConverter]::ToInt64([BitConverter]::GetBytes([uint64]$data), 0) }
                default { throw ('Unsupported registry type: ' + $kind) }
            }
            $key = $root.CreateSubKey([string]$op.path)
            $key.SetValue([string]$op.name, $data, $kind)
            $actual = $key.GetValue([string]$op.name, $null,
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            $expectedJson = ConvertTo-Json -InputObject $data -Compress
            $actualJson = ConvertTo-Json -InputObject $actual -Compress
            if ($key.GetValueKind([string]$op.name) -ne $kind -or $actualJson -cne $expectedJson) {
                throw ('Readback verification failed: ' + $op.path + ' / ' + $op.name)
            }
        }
    } finally {
        if ($null -ne $key) { $key.Dispose() }
        $root.Dispose()
    }
}
'''


def _ps_json(data):
    return "'" + json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace("'", "''") + "'"


def _encoded(script):
    return base64.b64encode(script.encode('utf-16le')).decode('ascii')


def build_bat(mode, did=None, plan=None):
    if mode == 'DX':
        if not did:
            raise ValueError('No PCI hardware ID')
        setup = DX_FUNCTION + r'''
$root = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
    [Microsoft.Win32.RegistryHive]::CurrentUser, [Microsoft.Win32.RegistryView]::Registry64)
$key = $null
try {
    $path = 'Software\Microsoft\DirectX\UserGpuPreferences'
    $name = 'DirectXUserGlobalSettings'
    $key = $root.OpenSubKey($path)
    $current = if ($null -ne $key) { $key.GetValue($name, '') } else { '' }
    if ($current -isnot [string]) { throw 'DirectX registry setting must be a string. No changes made.' }
} finally {
    if ($null -ne $key) { $key.Dispose() }
    $root.Dispose()
}
'''
        setup += '$did = ConvertFrom-Json -InputObject ' + _ps_json(did) + '\n'
        setup += r'''
$next = Get-DxSetting $current $did
$plan = @([pscustomobject]@{
    root = 'HKCU'; path = $path; name = $name; view = 64; value = @($next, 1)
})
'''
    elif mode == 'GL':
        if not plan:
            raise ValueError('No OpenGL registry operations')
        setup = r'''
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator required. Right-click the BAT and select Run as administrator.'
}
'''
        setup += '$plan = ConvertFrom-Json -InputObject ' + _ps_json(plan) + '\n'
    else:
        raise ValueError('Unknown BAT mode: ' + str(mode))
    script = "$ErrorActionPreference = 'Stop'\n" + APPLY_FUNCTION + '\ntry {\n' + setup + r'''
foreach ($op in $plan) { Apply-RegistryOperation $op }
Write-Host 'Registry values written and readback verified. Check runtime GPU in GPU Selector.'
exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    [Console]::Error.WriteLine('Operation did not complete; earlier values may have changed. Check GPU Selector.')
    exit 1
}
'''
    # Keep cmd.exe lines well below its 8191-character limit even with many GPUs.
    marker = '::GPU_DATA:'
    bootstrap = (
        "$ErrorActionPreference = 'Stop'; try { "
        "$data = (Get-Content -LiteralPath $env:GPU_SELECTOR_SCRIPT | "
        "Where-Object { $_.StartsWith('" + marker + "') } | "
        "ForEach-Object { $_.Substring(" + str(len(marker)) + ") }) -join ''; "
        "& ([scriptblock]::Create([Text.Encoding]::Unicode.GetString("
        "[Convert]::FromBase64String($data)))) "
        "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
    )
    lines = [
        '@echo off', 'setlocal DisableDelayedExpansion',
        'REM GPU Selector / AGPL-3.0; adaptation modified 2026-09-06',
        'REM Source: https://github.com/nethe-GitHub/select_default_GPU',
        'REM Standalone BAT has no automatic backup. Use the GUI for backup and undo.',
        'REM OpenGL: Run as Administrator. Reboot required on first use.' if mode == 'GL' else
        'REM DirectX: Applies to the current user; preserves unrelated global preferences.',
        'set "GPU_SELECTOR_SCRIPT=%~f0"',
        r'set "GPU_SELECTOR_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"',
        r'if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "GPU_SELECTOR_PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"',
        'if not exist "%GPU_SELECTOR_PS%" (echo Windows PowerShell is unavailable. & exit /b 1)',
        '"%GPU_SELECTOR_PS%" -NoLogo -NoProfile -NonInteractive -EncodedCommand ' + _encoded(bootstrap),
        'set "GPU_SELECTOR_EXIT=%errorlevel%"',
        'endlocal & exit /b %GPU_SELECTOR_EXIT%',
    ]
    lines.extend(marker + chunk for chunk in textwrap.wrap(_encoded(script), width=120))
    return '\r\n'.join(lines) + '\r\n'
