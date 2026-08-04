function Get-CompatibleCodexPluginCli {
    if ([Environment]::GetEnvironmentVariable("AIVCP_DISABLE_CODEX_AUTO_REGISTRATION", "Process") -eq "1") {
        return $null
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($name in @("codex.exe", "codex")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
            $candidates.Add($command.Source)
        }
    }

    $localBin = Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin"
    if (Test-Path -LiteralPath $localBin -PathType Container) {
        Get-ChildItem -LiteralPath $localBin -Filter "codex.exe" -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        $normalized = [System.IO.Path]::GetFullPath($candidate)
        if ($seen.ContainsKey($normalized)) { continue }
        $seen[$normalized] = $true
        try {
            $help = (& $normalized plugin --help 2>&1 | Out-String)
            if ($LASTEXITCODE -eq 0 -and $help -match "(?m)^\s+add\s+") {
                return $normalized
            }
        }
        catch {
            continue
        }
    }
    return $null
}
