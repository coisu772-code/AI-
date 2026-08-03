Set-StrictMode -Version Latest

$script:AivcpProductId = "ai-video-channel-production"
$script:AivcpMarketplaceName = "novel-manga-production"

function Resolve-AivcpFullPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Test-AivcpSafeRoot {
    param(
        [Parameter(Mandatory = $true)][string]$PathValue,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $full = Resolve-AivcpFullPath $PathValue
    if ($full -eq [System.IO.Path]::GetPathRoot($full) -or $full.Length -lt 12) {
        throw "$Label is too broad; refusing operation: $full"
    }
    return $full
}

function Get-AivcpRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)][string]$FilePath
    )
    $rootWithSlash = $RootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $rootUri = [System.Uri]::new($rootWithSlash)
    $fileUri = [System.Uri]::new($FilePath)
    return [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString())
}

function Get-AivcpNormalizedFileBytes {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    $textExtensions = @(".cmd", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml")
    $extension = [System.IO.Path]::GetExtension($FilePath).ToLowerInvariant()
    if ($textExtensions -contains $extension) {
        $content = [System.IO.File]::ReadAllText($FilePath)
        $normalized = $content.Replace("`r`n", "`n").Replace("`r", "`n")
        return [System.Text.UTF8Encoding]::new($false).GetBytes($normalized)
    }
    return [System.IO.File]::ReadAllBytes($FilePath)
}

function Get-AivcpSha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-AivcpFileSha256 {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    return (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-AivcpTreeHash {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $rootFull = Resolve-AivcpFullPath $RootPath
    $lines = New-Object System.Collections.Generic.List[string]
    $relativePaths = New-Object System.Collections.Generic.List[string]
    $filesByRelativePath = [System.Collections.Generic.Dictionary[string,System.IO.FileInfo]]::new([System.StringComparer]::Ordinal)
    Get-ChildItem -LiteralPath $rootFull -File -Recurse |
        Where-Object { $_.Extension -ne ".pyc" -and $_.FullName -notmatch "[\\/]__pycache__[\\/]" } |
        ForEach-Object {
            $relative = Get-AivcpRelativePath $rootFull $_.FullName
            $relativePaths.Add($relative)
            $filesByRelativePath.Add($relative, $_)
        }
    $relativePaths.Sort([System.StringComparer]::Ordinal)
    foreach ($relative in $relativePaths) {
        $file = $filesByRelativePath[$relative]
        $fileBytes = Get-AivcpNormalizedFileBytes $file.FullName
        $hash = Get-AivcpSha256Hex $fileBytes
        $lines.Add("$relative`t$($fileBytes.Length)`t$hash`n")
    }
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($lines -join ""))
    return Get-AivcpSha256Hex $bytes
}

function Get-AivcpDefaultDataRoot {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $statePath = Join-Path $installFull "current\install-state.json"
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $dataProperty = $state.PSObject.Properties["userDataRoot"]
        if ($null -ne $dataProperty -and -not [string]::IsNullOrWhiteSpace([string]$dataProperty.Value)) {
            return Resolve-AivcpFullPath ([string]$dataProperty.Value)
        }
    }
    $legacy = Join-Path $installFull "data"
    if (Test-Path -LiteralPath $legacy -PathType Container) {
        return Resolve-AivcpFullPath $legacy
    }
    return Resolve-AivcpFullPath (Join-Path $env:LOCALAPPDATA "AI Video Channel Production Data")
}

function Resolve-AivcpDataRoot {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [string]$RequestedDataRoot
    )
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $dataFull = if ([string]::IsNullOrWhiteSpace($RequestedDataRoot)) {
        Get-AivcpDefaultDataRoot $installFull
    }
    else {
        Resolve-AivcpFullPath $RequestedDataRoot
    }
    if ($dataFull -eq $installFull) {
        throw "User data root must not equal the program installation root."
    }
    $currentPrefix = (Join-Path $installFull "current").TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if ($dataFull.StartsWith($currentPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "User data root must not be placed inside the active program version."
    }
    return Test-AivcpSafeRoot $dataFull "DataRoot"
}

function Get-AivcpInstallation {
    param([Parameter(Mandatory = $true)][string]$InstallRoot)
    $installFull = Resolve-AivcpFullPath $InstallRoot
    $marker = Join-Path $installFull "installation.json"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        throw "Installation marker is missing: $marker"
    }
    $installation = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$installation.productId -ne $script:AivcpProductId) {
        throw "Installation marker does not belong to this product."
    }
    return $installation
}

function Test-AivcpNoReparsePoints {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $rootFull = Resolve-AivcpFullPath $RootPath
    $reparse = Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction Stop |
        Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($null -ne $reparse) {
        throw "Reparse points are not allowed in this operation: $($reparse.FullName)"
    }
}
