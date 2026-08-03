[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [ValidateSet("Existing", "Online", "Offline")]
    [string]$RuntimeMode = "Online",
    [string]$PythonExecutable,
    [string]$OfflineWheelhouseRoot,
    [switch]$SkipCodexRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$installation = Get-AivcpInstallation $installFull
if ([string]::IsNullOrWhiteSpace($SourceRoot)) { $SourceRoot = Join-Path $installFull "current" }
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $dataProperty = $installation.PSObject.Properties["userDataRoot"]
    $DataRoot = if ($null -ne $dataProperty) { [string]$dataProperty.Value } else { Get-AivcpDefaultDataRoot $installFull }
}
$sourceFull = Resolve-AivcpFullPath $SourceRoot
$installer = Join-Path $sourceFull "installer\Install-AIVideoChannelProduction.ps1"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Repair source is incomplete. Download and verify the same or newer release package, then pass -SourceRoot."
}
& $installer -SourceRoot $sourceFull -InstallRoot $installFull -DataRoot $DataRoot `
    -RuntimeMode $RuntimeMode -PythonExecutable $PythonExecutable -OfflineWheelhouseRoot $OfflineWheelhouseRoot `
    -SkipCodexRegistration:$SkipCodexRegistration -Force
if ($LASTEXITCODE -ne 0) { throw "Repair failed; the previous active version was restored automatically." }
Write-Output "Repair completed without changing user data at $DataRoot"
