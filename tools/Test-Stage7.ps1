[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$outputs = [System.IO.Path]::GetFullPath((Join-Path $root ".stage7-output-isolated"))
if (-not $outputs.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unexpected stage 7 output root."
}
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required for stage 7 validation." }

Push-Location $root
try {
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    & $uv.Source sync --locked
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 dependency synchronization failed." }

    $checks = @(
        @("run", "python", "tools/validate_plugin.py"),
        @("run", "python", "tools/validate_contracts.py"),
        @("run", "python", "tools/validate_release_manifest.py"),
        @("run", "python", "tools/check_repository_safety.py"),
        @("run", "python", "-m", "unittest", "-q", "tests.test_stage7_data_center")
    )
    foreach ($arguments in $checks) {
        & $uv.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Stage 7 validation failed: uv $($arguments -join ' ')" }
    }

    if (Test-Path -LiteralPath $outputs) { Remove-Item -LiteralPath $outputs -Recurse -Force }
    & $uv.Source run python "tools/generate_stage7_fixture_outputs.py" --output $outputs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 three-market fixture generation failed." }
    & $uv.Source run python "tools/validate_stage7_outputs.py" --output $outputs
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 three-market output validation failed." }

    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "tools\Test-Stage7-Plugin.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Stage 7 plugin installation validation failed." }
}
finally {
    Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $outputs) { Remove-Item -LiteralPath $outputs -Recurse -Force }
    Pop-Location
}

Write-Output "Stage 7 local data center, three-market fixtures, reports, recommendations, and isolated installation passed."
