$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$gpuPython = (Get-Command python -ErrorAction Stop).Source
& $gpuPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $gpuPython -m unittest discover -s . -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
$gpuOldPath = $env:PATH
try {
    # Avoid collecting unrelated runtime DLLs from other software on PATH.
    $env:PATH = "$env:WINDIR\System32;$env:WINDIR;$(Split-Path -Parent $gpuPython)"
    & $gpuPython -m PyInstaller --clean --noconfirm GPUSelector.spec
} finally {
    $env:PATH = $gpuOldPath
}
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
