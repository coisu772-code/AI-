[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [string]$BackupName,
    [switch]$SkipCodexRegistration,
    [ValidateSet("None", "AfterSwitch", "AfterMcpDescriptorBinding", "AfterMarkerWrite", "AfterLocatorWrite", "AfterCodexRegistration")]
    [string]$FailureInjectionPoint = "None"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "CodexCli.ps1")

$operationLock = Enter-AivcpOperationLock
try {
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
    $candidateOriginalPath = [string]$candidate.FullName
    $candidateDescriptorSnapshot = Get-AivcpFileSnapshot (Join-Path $candidateOriginalPath "plugins\ai-video-channel-production\.mcp.json")
    $markerSnapshot = Get-AivcpFileSnapshot $marker
    $locatorSnapshot = Get-AivcpFileSnapshot (Get-AivcpRuntimeLocatorPath)
    $switched = $false
    $codex = $null
    try {
        if (Test-Path -LiteralPath $currentPath) {
            Move-Item -LiteralPath $currentPath -Destination $rollbackBackup
        }
        Move-Item -LiteralPath $candidate.FullName -Destination $currentPath
        $switched = $true
        if ($FailureInjectionPoint -eq "AfterSwitch") { throw "TEST_FAILURE_INJECTION:AfterSwitch" }

        $candidateDataProperty = $candidateState.PSObject.Properties["userDataRoot"]
        $restoredDataRoot = if ($null -ne $candidateDataProperty) { [string]$candidateDataProperty.Value } else { Get-AivcpDefaultDataRoot $installFull }
        $candidateReleaseProperty = $candidateState.PSObject.Properties["releaseManifestSha256"]
        if ($null -eq $candidateReleaseProperty -or [string]$candidateReleaseProperty.Value -notmatch "^[a-fA-F0-9]{64}$") {
            throw "Selected backup is missing a valid release manifest binding."
        }
        $null = Write-AivcpRuntimeBoundMcpDescriptor -PluginRoot (Join-Path $currentPath "plugins\ai-video-channel-production") -InstallRoot $installFull -DataRoot $restoredDataRoot -ProductVersion ([string]$candidateState.productVersion) -ReleaseManifestSha256 ([string]$candidateReleaseProperty.Value)
        if ($FailureInjectionPoint -eq "AfterMcpDescriptorBinding") { throw "TEST_FAILURE_INJECTION:AfterMcpDescriptorBinding" }
        Write-AivcpJsonFile -Value ([ordered]@{
            schemaVersion = "2.0.0"
            productId = "ai-video-channel-production"
            activeVersion = [string]$candidateState.productVersion
            activeRoot = "current"
            userDataRoot = $restoredDataRoot
            releaseManifestSha256 = if ($null -ne $candidateReleaseProperty) { [string]$candidateReleaseProperty.Value } else { $null }
        }) -PathValue $marker
        if ($FailureInjectionPoint -eq "AfterMarkerWrite") { throw "TEST_FAILURE_INJECTION:AfterMarkerWrite" }
        $null = Write-AivcpRuntimeLocator -InstallRoot $installFull -DataRoot $restoredDataRoot -ProductVersion ([string]$candidateState.productVersion) -Operation rollback -AllowTakeover
        if ($FailureInjectionPoint -eq "AfterLocatorWrite") { throw "TEST_FAILURE_INJECTION:AfterLocatorWrite" }

        if (-not $SkipCodexRegistration) {
            $codex = Get-CompatibleCodexPluginCli
            if ($null -eq $codex) {
                $guide = Write-AivcpCodexSetupGuide -CurrentRoot $currentPath -Reason "Rollback completed, but no compatible Codex CLI was found."
                Write-Warning "Rollback completed. Manual Codex refresh instructions: $guide"
            }
            else {
                & $codex plugin marketplace add $currentPath --json | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Codex marketplace refresh failed after rollback." }
                & $codex plugin add "ai-video-channel-production@novel-manga-production" --json | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Codex plugin refresh failed after rollback." }
            }
        }
        if ($FailureInjectionPoint -eq "AfterCodexRegistration") { throw "TEST_FAILURE_INJECTION:AfterCodexRegistration" }
    }
    catch {
        $failure = $_
        if ($switched -and (Test-Path -LiteralPath $currentPath)) {
            Move-Item -LiteralPath $currentPath -Destination $candidateOriginalPath
        }
        Restore-AivcpFileSnapshot $candidateDescriptorSnapshot
        if (Test-Path -LiteralPath $rollbackBackup) {
            Move-Item -LiteralPath $rollbackBackup -Destination $currentPath
        }
        Restore-AivcpFileSnapshot $markerSnapshot
        Restore-AivcpFileSnapshot $locatorSnapshot
        if (-not $SkipCodexRegistration -and $null -ne $codex -and (Test-Path -LiteralPath $currentPath -PathType Container)) {
            try {
                & $codex plugin marketplace add $currentPath --json | Out-Null
                & $codex plugin add "ai-video-channel-production@novel-manga-production" --json | Out-Null
            }
            catch { Write-Warning "Program rollback was restored, but Codex registration also needs manual repair." }
        }
        throw "Rollback failed and current program, marker, and runtime locator were restored. $($failure.Exception.Message)"
    }
    Write-Output "Rollback completed. Restart Codex and open a new task."
}
}
finally {
    Exit-AivcpOperationLock $operationLock
}
