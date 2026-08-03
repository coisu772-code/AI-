[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [switch]$SkipCodexRemoval
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "CodexCli.ps1")

$installFull = [System.IO.Path]::GetFullPath($InstallRoot)
$marker = Join-Path $installFull "installation.json"
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw "Installation marker is missing; refusing recursive removal: $installFull"
}
$installation = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$installation.productId -ne "ai-video-channel-production") {
    throw "Installation marker does not belong to this product."
}
if ($installFull -eq [System.IO.Path]::GetPathRoot($installFull) -or $installFull.Length -lt 12) {
    throw "InstallRoot is too broad; refusing removal: $installFull"
}

if (-not $SkipCodexRemoval) {
    $codex = Get-CompatibleCodexPluginCli
    if ($null -eq $codex) {
        throw "A Codex CLI with plugin remove support was not found. Re-run with -SkipCodexRemoval to remove program files only."
    }
    & $codex plugin remove "ai-video-channel-production" --marketplace "novel-manga-production"
    if ($LASTEXITCODE -ne 0) { throw "Codex plugin removal failed." }
    & $codex plugin marketplace remove "novel-manga-production"
    if ($LASTEXITCODE -ne 0) { throw "Codex marketplace removal failed." }
}

if ($PSCmdlet.ShouldProcess($installFull, "Remove program files only")) {
    Remove-Item -LiteralPath $installFull -Recurse -Force
    Write-Output "Program files removed. Channel data and credentials were not targeted."
}
