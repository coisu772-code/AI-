[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$AssetRoot = $PSScriptRoot,
    [string]$DownloadBaseUrl,
    [ValidateSet("Auto", "Offline", "Online")]
    [string]$InstallMode = "Auto",
    [string]$InstallRoot,
    [string]$DataRoot,
    [switch]$NonInteractive,
    [switch]$SkipCodexRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

function Get-RecommendedAivcpDataRoot {
    $systemDrive = [string]$env:SystemDrive
    $candidate = [System.IO.DriveInfo]::GetDrives() |
        Where-Object {
            $_.DriveType -eq [System.IO.DriveType]::Fixed -and
            $_.IsReady -and
            $_.Name.TrimEnd("\") -ne $systemDrive
        } |
        Sort-Object AvailableFreeSpace -Descending |
        Select-Object -First 1
    if ($null -ne $candidate) {
        return Join-Path $candidate.RootDirectory.FullName "AI Video Channel Production Data"
    }
    return Join-Path ([Environment]::GetFolderPath("MyVideos")) "AI Video Channel Production Data"
}

$defaultInstallRoot = Join-Path $env:LOCALAPPDATA "AIVCP"
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    if ($NonInteractive) {
        $InstallRoot = $defaultInstallRoot
    }
    else {
        $answer = Read-Host "Program folder (Enter keeps $defaultInstallRoot)"
        $InstallRoot = if ([string]::IsNullOrWhiteSpace($answer)) { $defaultInstallRoot } else { $answer }
    }
}
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$installationPath = Join-Path $installFull "installation.json"
$existingDataRoot = $null
if (Test-Path -LiteralPath $installationPath -PathType Leaf) {
    $installation = Get-Content -LiteralPath $installationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $property = $installation.PSObject.Properties["userDataRoot"]
    if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        $existingDataRoot = Resolve-AivcpFullPath ([string]$property.Value)
    }
}

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($existingDataRoot)) {
        $DataRoot = $existingDataRoot
        Write-Output "Existing user data folder will be preserved: $DataRoot"
    }
    elseif ($NonInteractive) {
        throw "A fresh non-interactive installation requires -DataRoot so large user files are not silently placed on the system drive."
    }
    else {
        $recommendedDataRoot = Get-RecommendedAivcpDataRoot
        $answer = Read-Host "User data folder for sources, documents, audio, images and video (Enter keeps $recommendedDataRoot)"
        $DataRoot = if ([string]::IsNullOrWhiteSpace($answer)) { $recommendedDataRoot } else { $answer }
    }
}
$dataFull = Resolve-AivcpDataRoot -InstallRoot $installFull -RequestedDataRoot $DataRoot
if (-not [string]::IsNullOrWhiteSpace($existingDataRoot) -and -not $existingDataRoot.Equals($dataFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "This installation already owns user data at $existingDataRoot. Back up and restore through the supported data migration workflow instead of silently rebinding it to $dataFull."
}

Write-Output "Program folder: $installFull"
Write-Output "User data folder: $dataFull"
if ([System.IO.Path]::GetPathRoot($dataFull).TrimEnd("\") -eq [string]$env:SystemDrive) {
    Write-Warning "The selected user data folder is on the system drive. Large source, audio, image and video files will consume system-drive space."
}

& (Join-Path $PSScriptRoot "Install-AIVideoChannelProduction.ps1") `
    -ManifestPath $ManifestPath `
    -AssetRoot $AssetRoot `
    -DownloadBaseUrl $DownloadBaseUrl `
    -InstallMode $InstallMode `
    -InstallRoot $installFull `
    -DataRoot $dataFull `
    -SkipCodexRegistration:$SkipCodexRegistration
