param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    python -m venv $VenvPath
    $Install = $true
}

if ($Install) {
    & $PythonPath -m pip install --upgrade pip
    & $PythonPath -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
}

& $PythonPath (Join-Path $ProjectRoot "main.py")

