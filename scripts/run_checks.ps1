$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Check {
    param(
        [string] $Name,
        [scriptblock] $Command
    )

    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Invoke-Check "Backend pytest" {
    .\.venv\Scripts\python.exe -m pytest
}

Invoke-Check "V4 semantic regression" {
    .\.venv\Scripts\python.exe scripts\test_v4_semantics.py
}

Invoke-Check "V4 context regression" {
    .\.venv\Scripts\python.exe scripts\test_v4_context.py
}

Invoke-Check "Flutter analyze" {
    Push-Location flutter_app
    try {
        flutter analyze
    }
    finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "All checks passed." -ForegroundColor Green
