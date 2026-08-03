[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [switch]$SkipCodexRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$installer = Join-Path $SourceRoot "installer\Install-AIVideoChannelProduction.ps1"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Upgrade source does not contain the installer: $installer"
}

try {
    & $installer -SourceRoot $SourceRoot -InstallRoot $InstallRoot -SkipCodexRegistration:$SkipCodexRegistration -Force
}
catch {
    throw "Upgrade failed. The previous current version remains available in backups. $($_.Exception.Message)"
}
