[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA "AIVCP"),
    [string]$DataRoot,
    [string]$DestinationRoot = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "AI Video Channel Production Backups")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$installFull = Test-AivcpSafeRoot $InstallRoot "InstallRoot"
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $installation = Get-AivcpInstallation $installFull
    $property = $installation.PSObject.Properties["userDataRoot"]
    $DataRoot = if ($null -ne $property) { [string]$property.Value } else { Get-AivcpDefaultDataRoot $installFull }
}
$dataFull = Test-AivcpSafeRoot $DataRoot "DataRoot"
if (-not (Test-Path -LiteralPath $dataFull -PathType Container)) { throw "User data root does not exist: $dataFull" }
Test-AivcpNoReparsePoints $dataFull
if ([string]::IsNullOrWhiteSpace($DestinationRoot)) { throw "DestinationRoot is required." }
$destinationFull = Test-AivcpSafeRoot $DestinationRoot "DestinationRoot"
$dataPrefix = $dataFull.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if ($destinationFull.StartsWith($dataPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup destination must not be inside the user data root."
}
New-Item -ItemType Directory -Path $destinationFull -Force | Out-Null
$staging = Join-Path $destinationFull (".b-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$payload = Join-Path $staging "payload"
$archiveName = "ai-video-channel-production-data-" + (Get-Date -Format "yyyyMMdd-HHmmssfff") + ".aivcp-backup.zip"
$archivePath = Join-Path $destinationFull $archiveName
New-Item -ItemType Directory -Path $payload -Force | Out-Null
try {
    $records = New-Object System.Collections.Generic.List[object]
    $recordLines = New-Object System.Collections.Generic.List[string]
    $files = @(Get-ChildItem -LiteralPath $dataFull -File -Recurse -Force | Sort-Object FullName)
    foreach ($file in $files) {
        $relative = (Get-AivcpRelativePath $dataFull $file.FullName).Replace("\", "/")
        if ($relative -match "(?i)(?:^|/)(?:[^/]*(?:secret|credential|cookie|client_secret|access_token|refresh_token)[^/]*)$") {
            throw "BACKUP_SENSITIVE_MATERIAL_DETECTED: $relative"
        }
        $target = Join-Path $payload $relative.Replace("/", "\")
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $sha = Get-AivcpFileSha256 $target
        $size = (Get-Item -LiteralPath $target).Length
        $records.Add([ordered]@{ path = $relative; sizeBytes = $size; sha256 = $sha })
        $recordLines.Add("$relative`t$size`t$sha`n")
    }
    $payloadHash = Get-AivcpSha256Hex ([System.Text.UTF8Encoding]::new($false).GetBytes(($recordLines -join "")))
    [ordered]@{
        schemaVersion = "1.0.0"
        productId = "ai-video-channel-production"
        archiveType = "user-data-backup"
        createdAt = (Get-Date).ToUniversalTime().ToString("o")
        hashAlgorithm = "SHA-256"
        payloadHashRule = "sorted-path-size-sha256-v1"
        payloadHash = $payloadHash
        fileCount = $records.Count
        files = $records
        security = [ordered]@{
            containsProgramFiles = $false
            containsKnownCredentialNamedFiles = $false
            intendedForLocalUserCustody = $true
        }
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $staging "backup-manifest.json") -Encoding UTF8
    $items = @(Get-ChildItem -LiteralPath $staging -Force)
    Compress-Archive -LiteralPath $items.FullName -DestinationPath $archivePath -CompressionLevel Optimal
    $archiveHash = Get-AivcpFileSha256 $archivePath
    "$archiveHash  $archiveName`n" | Set-Content -LiteralPath ($archivePath + ".sha256") -Encoding ascii -NoNewline
}
finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
[ordered]@{
    status = "BACKUP_COMPLETE"
    archivePath = $archivePath
    sha256 = $archiveHash
    payloadHash = $payloadHash
    fileCount = $records.Count
} | ConvertTo-Json -Depth 4
