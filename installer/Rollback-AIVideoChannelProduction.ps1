[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$BackupName,
    [switch]$SkipCodexRegistration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "CodexCli.ps1")

$installFull = [System.IO.Path]::GetFullPath($InstallRoot)
$marker = Join-Path $installFull "installation.json"
if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
    throw "Installation marker is missing; refusing rollback: $installFull"
}
$installation = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$installation.productId -ne "ai-video-channel-production") {
    throw "Installation marker does not belong to this product."
}

$backupRoot = Join-Path $installFull "backups"
if (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) {
    throw "No rollback backups are available."
}

if ([string]::IsNullOrWhiteSpace($BackupName)) {
    $candidate = Get-ChildItem -LiteralPath $backupRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
else {
    $backupRootFull = [System.IO.Path]::GetFullPath($backupRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $candidatePath = [System.IO.Path]::GetFullPath((Join-Path $backupRoot $BackupName))
    if (-not $candidatePath.StartsWith($backupRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BackupName escapes the product backup directory."
    }
    $candidate = Get-Item -LiteralPath $candidatePath -ErrorAction Stop
}
if ($null -eq $candidate -or -not $candidate.PSIsContainer -or -not (Test-Path -LiteralPath (Join-Path $candidate.FullName "install-state.json"))) {
    throw "Selected backup is not a valid product version."
}
$candidateState = Get-Content -LiteralPath (Join-Path $candidate.FullName "install-state.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$candidateState.productId -ne "ai-video-channel-production") {
    throw "Selected backup does not belong to this product."
}

$currentPath = Join-Path $installFull "current"
if ($PSCmdlet.ShouldProcess($currentPath, "Rollback to $($candidate.Name)")) {
    $rollbackBackup = Join-Path $backupRoot ("pre-rollback-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
    if (Test-Path -LiteralPath $currentPath) {
        Move-Item -LiteralPath $currentPath -Destination $rollbackBackup
    }
    try {
        Move-Item -LiteralPath $candidate.FullName -Destination $currentPath
    }
    catch {
        if (-not (Test-Path -LiteralPath $currentPath) -and (Test-Path -LiteralPath $rollbackBackup)) {
            Move-Item -LiteralPath $rollbackBackup -Destination $currentPath
        }
        throw
    }

    $candidateDataProperty = $candidateState.PSObject.Properties["userDataRoot"]
    $restoredDataRoot = if ($null -ne $candidateDataProperty) { [string]$candidateDataProperty.Value } else { Get-AivcpDefaultDataRoot $installFull }
    $candidateReleaseProperty = $candidateState.PSObject.Properties["releaseManifestContentHash"]
    [ordered]@{
        schemaVersion = "1.1.0"
        productId = "ai-video-channel-production"
        activeVersion = [string]$candidateState.productVersion
        activeRoot = "current"
        userDataRoot = $restoredDataRoot
        releaseManifestContentHash = if ($null -ne $candidateReleaseProperty) { [string]$candidateReleaseProperty.Value } else { $null }
    } | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8

    if (-not $SkipCodexRegistration) {
        $codex = Get-CompatibleCodexPluginCli
        if ($null -eq $codex) {
            $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason "Rollback completed, but no compatible Codex CLI was found."
            Write-Warning "Rollback completed. Manual Codex refresh instructions: $guide"
        }
        else {
            & $codex plugin marketplace add $currentPath --json | Out-Null
            & $codex plugin add "ai-video-channel-production@novel-manga-production" --json | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason "Rollback completed, but Codex plugin refresh failed."
                Write-Warning "Manual Codex refresh instructions: $guide"
            }
        }
    }
    Write-Output "Rollback completed. Restart Codex and open a new task."
}
