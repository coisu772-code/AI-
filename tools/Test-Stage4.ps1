[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 4 validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"

    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Stage 4 dependency synchronization failed." }

    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "tools/validate_stage4_packages.py"),
        @("run", "python", "-m", "unittest", "tests.test_stage4_content_loop", "-v")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 4 validation failed: uv $($arguments -join ' ')" }
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "tools\Test-Stage4-Plugin.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Stage 4 plugin and isolated installation validation failed." }
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Output "Stage 4 content loop, failure paths, Skill routing, health checks, and isolated installation passed."
