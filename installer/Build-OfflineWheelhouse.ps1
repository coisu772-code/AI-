[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$PythonExecutable
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$output = Test-AivcpSafeRoot $OutputRoot "OutputRoot"
$requirements = Join-Path $PSScriptRoot "runtime-requirements.txt"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) { throw "uv is required to prepare the offline wheelhouse." }
if (Test-Path -LiteralPath $output) {
    if ($null -ne (Get-ChildItem -LiteralPath $output -Force | Select-Object -First 1)) {
        throw "Offline wheelhouse output must be empty: $output"
    }
}
else { New-Item -ItemType Directory -Path $output -Force | Out-Null }
$arguments = @("run", "--with", "pip", "python", "-m", "pip", "download", "--quiet", "--progress-bar", "off", "--only-binary=:all:", "--dest", $output, "--requirement", $requirements)
if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $env:UV_PYTHON = Resolve-AivcpFullPath $PythonExecutable
}
try {
    & $uv.Source @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Offline wheelhouse dependency download failed." }
}
finally { Remove-Item Env:UV_PYTHON -ErrorAction SilentlyContinue }
$records = @(Get-ChildItem -LiteralPath $output -File | Sort-Object Name | ForEach-Object {
    "{0}  {1}" -f (Get-AivcpFileSha256 $_.FullName), $_.Name
})
if ($records.Count -eq 0) { throw "Offline wheelhouse is empty." }
($records -join "`n") + "`n" | Set-Content -LiteralPath (Join-Path $output "WHEELHOUSE-SHA256SUMS.txt") -Encoding ascii -NoNewline
[ordered]@{ status = "OFFLINE_WHEELHOUSE_READY"; path = $output; wheelCount = $records.Count } | ConvertTo-Json
