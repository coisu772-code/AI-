[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [ValidateSet("Existing", "Online", "Offline")]
    [string]$RuntimeMode = "Existing",
    [string]$PythonExecutable,
    [string]$OfflineWheelhouseRoot,
    [switch]$SkipCodexRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$installer = Join-Path $SourceRoot "installer\Install-AIVideoChannelProduction.ps1"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Upgrade source does not contain the installer: $installer"
}

try {
    & $installer -SourceRoot $SourceRoot -InstallRoot $InstallRoot -DataRoot $DataRoot `
        -RuntimeMode $RuntimeMode -PythonExecutable $PythonExecutable -OfflineWheelhouseRoot $OfflineWheelhouseRoot `
        -SkipCodexRegistration:$SkipCodexRegistration -Force
}
catch {
    throw "Upgrade failed. The previous active version was restored automatically. $($_.Exception.Message)"
}
