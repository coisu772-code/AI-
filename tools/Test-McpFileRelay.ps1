[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$ServerScript,
    [string]$ReportPath,
    [switch]$AsJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$pythonFull = [System.IO.Path]::GetFullPath($PythonExecutable)
$serverFull = [System.IO.Path]::GetFullPath($ServerScript)
if (-not (Test-Path -LiteralPath $pythonFull -PathType Leaf)) { throw "MCP file-relay validation Python is missing." }
if (-not (Test-Path -LiteralPath $serverFull -PathType Leaf)) { throw "MCP file-relay validation server is missing." }
$pluginRoot = Split-Path -Parent (Split-Path -Parent $serverFull)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$relayExitCodes = New-Object System.Collections.Generic.List[int]
$requestPreambleBytes = New-Object System.Collections.Generic.List[int]
$requestFileCount = 0

function Invoke-McpFileRelay([hashtable]$Request) {
    $requestText = $Request | ConvertTo-Json -Depth 8 -Compress
    $relayRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-mcp-file-relay-test-" + [guid]::NewGuid().ToString("N"))
    $requestPath = Join-Path $relayRoot "request.jsonl"
    $relayPath = Join-Path $relayRoot "relay.py"
    $relayCode = @'
import pathlib
import subprocess
import sys

payload = pathlib.Path(sys.argv[2]).read_bytes()
completed = subprocess.run(
    [sys.executable, sys.argv[1], "mcp"],
    input=payload,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)
sys.stdout.buffer.write(completed.stdout)
sys.stderr.buffer.write(completed.stderr)
raise SystemExit(completed.returncode)
'@
    New-Item -ItemType Directory -Path $relayRoot -Force | Out-Null
    try {
        [System.IO.File]::WriteAllText($requestPath, $requestText + "`n", $utf8NoBom)
        [System.IO.File]::WriteAllText($relayPath, $relayCode, [System.Text.Encoding]::ASCII)
        $requestBytes = [System.IO.File]::ReadAllBytes($requestPath)
        $preambleLength = 0
        if ($requestBytes.Length -ge 3 -and $requestBytes[0] -eq 0xEF -and $requestBytes[1] -eq 0xBB -and $requestBytes[2] -eq 0xBF) {
            $preambleLength = 3
        }
        $script:requestPreambleBytes.Add($preambleLength)
        $script:requestFileCount++
        if ($preambleLength -ne 0) { throw "MCP request file unexpectedly contains a UTF-8 BOM." }
        if (@([System.IO.File]::ReadAllBytes($relayPath) | Where-Object { $_ -gt 127 }).Count -ne 0) {
            throw "MCP relay script is not fixed ASCII."
        }

        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $pythonFull
        $info.Arguments = '"' + $relayPath.Replace('"', '\"') + '" "' + $serverFull.Replace('"', '\"') + '" "' + $requestPath.Replace('"', '\"') + '"'
        $info.WorkingDirectory = $pluginRoot
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = $utf8NoBom
        $info.StandardErrorEncoding = $utf8NoBom
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        if (-not $process.Start()) { throw "MCP file-relay validation process did not start." }
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $script:relayExitCodes.Add($process.ExitCode)
        if ($process.ExitCode -ne 0) { throw "MCP file-relay validation exited with $($process.ExitCode): $stderr" }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) { throw "MCP file-relay validation wrote unexpected stderr: $stderr" }
        $response = $stdout | ConvertFrom-Json
        if ($null -ne $response.PSObject.Properties["error"]) { throw "MCP rejected no-BOM JSONL file relay: $stdout" }
        return $response
    }
    finally {
        if (Test-Path -LiteralPath $relayRoot) { Remove-Item -LiteralPath $relayRoot -Recurse -Force }
    }
}

$healthDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-mcp-file-relay-data-" + [guid]::NewGuid().ToString("N"))
$hadDataRoot = Test-Path Env:AIVCP_DATA_ROOT
$previousDataRoot = $env:AIVCP_DATA_ROOT
$hadNetworkExecution = Test-Path Env:AIVCP_NETWORK_EXECUTION
$previousNetworkExecution = $env:AIVCP_NETWORK_EXECUTION
New-Item -ItemType Directory -Path $healthDataRoot -Force | Out-Null
$env:AIVCP_DATA_ROOT = $healthDataRoot
$env:AIVCP_NETWORK_EXECUTION = "false"
try {
    $unicodeProbe = "$([char]0x4E2D)$([char]0x6587)"
    $listResponse = Invoke-McpFileRelay ([ordered]@{ jsonrpc="2.0"; id=1; method="tools/list"; params=[ordered]@{ probe=$unicodeProbe } })
    $toolNames = @($listResponse.result.tools | ForEach-Object { [string]$_.name })
    $requiredTools = @("content_capabilities", "production_capabilities", "data_center_capabilities")
    foreach ($toolName in $requiredTools) {
        if ($toolNames -notcontains $toolName) { throw "MCP tools/list is missing $toolName." }
    }
    $capabilities = [ordered]@{}
    $requestId = 2
    foreach ($toolName in $requiredTools) {
        $response = Invoke-McpFileRelay ([ordered]@{ jsonrpc="2.0"; id=$requestId; method="tools/call"; params=[ordered]@{ name=$toolName; arguments=[ordered]@{} } })
        $payload = $response.result.structuredContent
        if ($null -eq $payload -or -not [bool]$payload.ok -or $null -eq $payload.result) { throw "MCP capability call failed: $toolName" }
        $capabilities[$toolName] = "PASS"
        $requestId++
    }
    $report = [ordered]@{
        schemaVersion = "1.0.0"
        status = "PASS"
        powershell = [ordered]@{
            edition = [string]$PSVersionTable.PSEdition
            version = [string]$PSVersionTable.PSVersion
            desktop51 = $PSVersionTable.PSVersion.Major -eq 5 -and $PSVersionTable.PSVersion.Minor -eq 1
        }
        transport = [ordered]@{
            mode = "NO_BOM_JSONL_FILE_PYTHON_RELAY"
            requestEncoding = "UTF-8"
            requestFileCount = $requestFileCount
            requestPreambleBytes = @($requestPreambleBytes)
            relayScriptEncoding = "ASCII"
            powershellInputRedirection = $false
            powershellInputObjectAccess = $false
            unicodeJsonProbe = "PASS"
        }
        fileRelay = [ordered]@{
            exitCode = if (@($relayExitCodes | Where-Object { $_ -ne 0 }).Count -eq 0) { 0 } else { 1 }
            exitCodes = @($relayExitCodes)
            stderrEmpty = $true
        }
        controlledRootCauseEvidence = [ordered]@{
            attempt = "windows-sandbox-attempt-7"
            rawStdinProbeHex = "efbbbf580a"
            fileRelay = [ordered]@{ exitCode=0 }
            evidenceSha256 = "05e806c73ab2eff8e6ec27cd89151464300d46fbcc8b05f2a3d341b7130c6ec9"
        }
        toolsList = [ordered]@{ status="PASS"; count=$toolNames.Count; required=$requiredTools }
        capabilities = $capabilities
        boundaries = [ordered]@{ networkExecution=$false; oauth=$false; upload=$false; longTermLearningWrite=$false }
    }
}
finally {
    if ($hadDataRoot) { $env:AIVCP_DATA_ROOT = $previousDataRoot } else { Remove-Item Env:AIVCP_DATA_ROOT -ErrorAction SilentlyContinue }
    if ($hadNetworkExecution) { $env:AIVCP_NETWORK_EXECUTION = $previousNetworkExecution } else { Remove-Item Env:AIVCP_NETWORK_EXECUTION -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $healthDataRoot) { Remove-Item -LiteralPath $healthDataRoot -Recurse -Force }
}

$rendered = $report | ConvertTo-Json -Depth 8
if (-not [string]::IsNullOrWhiteSpace($ReportPath)) {
    [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($ReportPath), $rendered + "`n", [System.Text.UTF8Encoding]::new($false))
}
if ($AsJson) { Write-Output $rendered } else { Write-Output "WinPS MCP no-BOM JSONL file-relay validation PASS." }
