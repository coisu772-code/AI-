[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$outputs = [System.IO.Path]::GetFullPath((Join-Path $root ".stage5-output-isolated"))
if (-not $outputs.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 5 output root."
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 5 validation." }
if ($null -eq (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { throw "ffmpeg is required for stage 5 validation." }
if ($null -eq (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw "ffprobe is required for stage 5 validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Stage 5 dependency synchronization failed." }

    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "-m", "unittest", "-q", "tests.test_stage5_production_handoff", "tests.test_stage5_workshop_bridge")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 5 validation failed: uv $($arguments -join ' ')" }
    }

    if (Test-Path -LiteralPath $outputs) { Remove-Item -LiteralPath $outputs -Recurse -Force }
    & $uv.Source run python "tools/generate_stage5_fixture_outputs.py" --output $outputs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage 5 three-market fixture generation failed." }
    & $uv.Source run python "tools/validate_stage5_outputs.py" --output $outputs
    if ($LASTEXITCODE -ne 0) { throw "Stage 5 three-market output validation failed." }

    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "tools\Test-Stage5-Plugin.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Stage 5 plugin installation validation failed." }
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $outputs) { Remove-Item -LiteralPath $outputs -Recurse -Force }
    Pop-Location
}

Write-Output "Stage 5 production handoff, failure paths, media gates, result packages, and isolated installation passed."
