[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [switch]$SkipCodexRemoval
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "CodexCli.ps1")

$operationLock = Enter-AivcpOperationLock
try {
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
$installation = Get-AivcpInstallation $installFull
$dataProperty = $installation.PSObject.Properties["userDataRoot"]
$dataFull = if ($null -ne $dataProperty -and -not [string]::IsNullOrWhiteSpace([string]$dataProperty.Value)) {
    Resolve-AivcpFullPath ([string]$dataProperty.Value)
}
else {
    Get-AivcpDefaultDataRoot $installFull
}

if ($PSCmdlet.ShouldProcess($installFull, "Remove program files and registration owned by this installation; preserve user data")) {
    $installPrefix = $installFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $dataInsideInstall = $dataFull.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    if ($dataInsideInstall) {
        $relativeData = Get-AivcpRelativePath $installFull $dataFull
        $topDataName = ($relativeData -split "[/\\]")[0]
        foreach ($item in Get-ChildItem -LiteralPath $installFull -Force) {
            if ($item.Name -eq $topDataName) { continue }
            Remove-Item -LiteralPath $item.FullName -Recurse -Force
        }
        [ordered]@{
            schemaVersion = "1.0.0"
            productId = "ai-video-channel-production"
            status = "PROGRAM_UNINSTALLED_USER_DATA_PRESERVED"
            userDataRoot = $dataFull
            uninstalledAt = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $installFull "uninstalled-user-data.json") -Encoding UTF8
    }
    else {
        Remove-Item -LiteralPath $installFull -Recurse -Force
    }
    if (-not (Test-Path -LiteralPath $dataFull -PathType Container)) {
        throw "Program removal completed, but the configured user data root is unexpectedly missing: $dataFull"
    }
    $locatorPath = Get-AivcpRuntimeLocatorPath
    $locatorExistsAtCommit = Test-Path -LiteralPath $locatorPath -PathType Leaf
    $locatorOwnedAtCommit = Test-AivcpRuntimeLocatorOwnedBy -InstallRoot $installFull
    $locatorRemoved = if ($locatorOwnedAtCommit) { Remove-AivcpRuntimeLocatorIfOwned -InstallRoot $installFull } else { $false }
    if (-not $SkipCodexRemoval -and (-not $locatorExistsAtCommit -or $locatorOwnedAtCommit)) {
        $codex = Get-CompatibleCodexPluginCli
        if ($null -eq $codex) {
            Write-Warning "No compatible Codex CLI was found. Program files were removed; remove the plugin through Codex later if it remains listed."
        }
        else {
            & $codex plugin remove "ai-video-channel-production" --marketplace "novel-manga-production" --json | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "Codex plugin removal did not complete after program removal." }
            & $codex plugin marketplace remove "novel-manga-production" --json | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "Codex marketplace removal did not complete after program removal." }
        }
    }
    elseif (-not $SkipCodexRemoval -and $locatorExistsAtCommit) {
        Write-Warning "Codex registration belongs to another AI Video Channel Production installation; it was preserved."
    }
    Write-Output "Program files removed. User data preserved at $dataFull"
    if ($locatorRemoved) { Write-Output "The runtime locator owned by this installation was removed." }
}
}
finally {
    Exit-AivcpOperationLock $operationLock
}
