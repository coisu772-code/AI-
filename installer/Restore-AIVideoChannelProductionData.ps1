[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)][string]$ArchivePath,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AI Video Channel Production"),
    [string]$DataRoot,
    [switch]$ReplaceExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Add-Type -AssemblyName System.IO.Compression.FileSystem

$archiveFull = Resolve-AivcpFullPath $ArchivePath
if (-not (Test-Path -LiteralPath $archiveFull -PathType Leaf)) { throw "Backup archive was not found: $archiveFull" }
$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $installation = Get-AivcpInstallation $installFull
    $property = $installation.PSObject.Properties["userDataRoot"]
    $DataRoot = if ($null -ne $property) { [string]$property.Value } else { Get-AivcpDefaultDataRoot $installFull }
}
$dataFull = Test-AivcpSafeRoot $DataRoot "DataRoot"
$parent = Split-Path -Parent $dataFull
$parentFull = Test-AivcpSafeRoot $parent "DataRoot parent"
$staging = Join-Path $parentFull (".r-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$previous = $null

$zip = [System.IO.Compression.ZipFile]::OpenRead($archiveFull)
try {
    $seen = @{}
    foreach ($entry in $zip.Entries) {
        $name = $entry.FullName.Replace("\", "/")
        if ([string]::IsNullOrWhiteSpace($name) -or $name.StartsWith("/") -or $name -match "^[A-Za-z]:" -or $name -match "(?:^|/)\.\.(?:/|$)") {
            throw "Backup archive contains an unsafe path: $name"
        }
        if ($seen.ContainsKey($name)) { throw "Backup archive contains a duplicate path: $name" }
        $seen[$name] = $true
    }
}
finally { $zip.Dispose() }

New-Item -ItemType Directory -Path $staging -Force | Out-Null
try {
    [System.IO.Compression.ZipFile]::ExtractToDirectory($archiveFull, $staging)
    $manifestPath = Join-Path $staging "backup-manifest.json"
    $payload = Join-Path $staging "payload"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or -not (Test-Path -LiteralPath $payload -PathType Container)) {
        throw "Backup archive is missing its manifest or payload."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$manifest.productId -ne "ai-video-channel-production" -or [string]$manifest.archiveType -ne "user-data-backup") {
        throw "Backup archive identity is invalid."
    }
    Test-AivcpNoReparsePoints $payload
    $recordLines = New-Object System.Collections.Generic.List[string]
    $expectedPaths = @{}
    foreach ($record in @($manifest.files)) {
        $relative = [string]$record.path
        if ($relative.StartsWith("/") -or $relative -match "^[A-Za-z]:" -or $relative -match "(?:^|/)\.\.(?:/|$)") {
            throw "Backup manifest contains an unsafe path: $relative"
        }
        $target = Resolve-AivcpFullPath (Join-Path $payload $relative.Replace("/", "\"))
        $payloadPrefix = (Resolve-AivcpFullPath $payload).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        if (-not $target.StartsWith($payloadPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Backup payload is missing a manifest file: $relative"
        }
        $actualSize = (Get-Item -LiteralPath $target).Length
        $actualHash = Get-AivcpFileSha256 $target
        if ($actualSize -ne [long]$record.sizeBytes -or $actualHash -ne [string]$record.sha256) {
            throw "Backup payload hash mismatch: $relative"
        }
        $expectedPaths[$relative] = $true
        $recordLines.Add("$relative`t$actualSize`t$actualHash`n")
    }
    $actualFiles = @(Get-ChildItem -LiteralPath $payload -File -Recurse -Force)
    if ($actualFiles.Count -ne $expectedPaths.Count) { throw "Backup payload file count does not match the manifest." }
    $payloadHash = Get-AivcpSha256Hex ([System.Text.UTF8Encoding]::new($false).GetBytes(($recordLines -join "")))
    if ($payloadHash -ne [string]$manifest.payloadHash) { throw "Backup payload aggregate hash mismatch." }
    $nonEmpty = (Test-Path -LiteralPath $dataFull -PathType Container) -and $null -ne (Get-ChildItem -LiteralPath $dataFull -Force | Select-Object -First 1)
    if ($nonEmpty -and -not $ReplaceExisting) { throw "Target user data root is not empty. Use -ReplaceExisting to preserve it as a pre-restore backup and continue." }

    if ($PSCmdlet.ShouldProcess($dataFull, "Restore verified user data backup")) {
        if (Test-Path -LiteralPath $dataFull) {
            $previous = Join-Path $parentFull ((Split-Path -Leaf $dataFull) + ".pre-restore-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
            Move-Item -LiteralPath $dataFull -Destination $previous
        }
        try {
            Move-Item -LiteralPath $payload -Destination $dataFull
        }
        catch {
            if (-not (Test-Path -LiteralPath $dataFull) -and $null -ne $previous -and (Test-Path -LiteralPath $previous)) {
                Move-Item -LiteralPath $previous -Destination $dataFull
            }
            throw
        }
    }
}
finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
[ordered]@{
    status = "RESTORE_COMPLETE"
    dataRoot = $dataFull
    payloadHash = $payloadHash
    previousDataPreservedAt = $previous
} | ConvertTo-Json -Depth 4
