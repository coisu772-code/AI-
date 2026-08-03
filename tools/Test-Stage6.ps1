[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$upstream = [System.IO.Path]::GetFullPath((Join-Path $root ".stage6-upstream-isolated"))
$outputs = [System.IO.Path]::GetFullPath((Join-Path $root ".stage6-output-isolated"))
foreach ($path in @($upstream, $outputs)) {
    if (-not $path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected stage 6 output root."
    }
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 6 validation." }
if ($null -eq (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "ffmpeg is required for stage 6 validation." }
if ($null -eq (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw "ffprobe is required for stage 6 validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 dependency synchronization failed." }

    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "-m", "unittest", "-q", "tests.test_stage6_publish_package_v2")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 6 validation failed: uv $($arguments -join ' ')" }
    }

    foreach ($path in @($upstream, $outputs)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    & $uv.Source run python "tools/generate_stage5_fixture_outputs.py" --output $upstream | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 Stage5 upstream fixture generation failed." }
    & $uv.Source run python "tools/generate_stage6_fixture_packages.py" --stage5-output $upstream --output $outputs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 three-market package generation failed." }
    & $uv.Source run python "tools/validate_stage6_outputs.py" --output $outputs
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 three-market package validation failed." }

    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "tools\Test-Stage6-Plugin.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Stage 6 plugin installation validation failed." }
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    foreach ($path in @($upstream, $outputs)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
    Pop-Location
}

Write-Output "Stage 6 publish package v2, safety gates, three-market fixtures, tools, and isolated installation passed."
