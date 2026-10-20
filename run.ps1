param(
    [int]$Port = 8080,
    [string]$BindHost = "127.0.0.1",
    [switch]$Open
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = $null

if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\python3.15.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\python3.exe"),
        "C:\ProgramData\chocolatey\bin\python3.15.exe",
        "C:\ProgramData\chocolatey\bin\python3.exe"
    )
    $python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notmatch "WindowsApps") {
            $python = $command.Source
        }
    }
}

if (-not $python) {
    Write-Error "Python 3 was not found. Install Python 3.12+ and run: python -m venv .venv"
    exit 1
}

& $python -c "import flask, waitress" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "The Python environment is missing Flask or Waitress." -ForegroundColor Yellow
    Write-Host "Install them with:" -ForegroundColor Yellow
    Write-Host "  $python -m pip install -r requirements.txt" -ForegroundColor Cyan
    exit 1
}

$serverArgs = @("server.py", "--host", $BindHost, "--port", "$Port")
if ($Open) {
    $serverArgs += "--open"
}

Write-Host "Starting Tawseel on http://${BindHost}:${Port}/ ..." -ForegroundColor Green
& $python @serverArgs
