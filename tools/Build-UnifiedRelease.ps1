[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$RuntimeSource,
    [Parameter(Mandatory = $true)][string]$WorkshopAssetRoot,
    [Parameter(Mandatory = $true)][string]$PublisherAssetRoot,
    [string]$DenoArchive
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$uv = Get-Command uv -ErrorAction Stop
$arguments = @(
    "run", "python", (Join-Path $root "tools\build_unified_release.py"),
    "--output", $OutputRoot,
    "--runtime-source", $RuntimeSource,
    "--uv", $uv.Source,
    "--workshop-dir", $WorkshopAssetRoot,
    "--publisher-dir", $PublisherAssetRoot
)
if (-not [string]::IsNullOrWhiteSpace($DenoArchive)) {
    $arguments += @("--deno-archive", $DenoArchive)
}
& $uv.Source @arguments
if ($LASTEXITCODE -ne 0) { throw "Unified release build failed." }
