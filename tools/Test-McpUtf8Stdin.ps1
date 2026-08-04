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
if (-not (Test-Path -LiteralPath $pythonFull -PathType Leaf)) { throw "MCP stdin validation Python is missing." }
if (-not (Test-Path -LiteralPath $serverFull -PathType Leaf)) { throw "MCP stdin validation server is missing." }
$pluginRoot = Split-Path -Parent (Split-Path -Parent $serverFull)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$inputEncodingPropertyAvailable = $false
$inputEncodingPropertySet = $false
$rawBaseStreamWrite = $false

function Invoke-McpRequest([hashtable]$Request) {
    $requestText = $Request | ConvertTo-Json -Depth 8 -Compress
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $pythonFull
    $info.Arguments = '"' + $serverFull.Replace('"', '\"') + '" mcp'
    $info.WorkingDirectory = $pluginRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $script:inputEncodingPropertyAvailable = $null -ne $info.PSObject.Properties["StandardInputEncoding"]
    if ($script:inputEncodingPropertyAvailable) {
        $info.StandardInputEncoding = $utf8NoBom
        $script:inputEncodingPropertySet = $true
    }
    $info.StandardOutputEncoding = $utf8NoBom
    $info.StandardErrorEncoding = $utf8NoBom
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    if (-not $process.Start()) { throw "MCP stdin validation process did not start." }
    $inputBytes = $utf8NoBom.GetBytes($requestText + "`n")
    $inputStream = $process.StandardInput.BaseStream
    $inputStream.Write($inputBytes, 0, $inputBytes.Length)
    $inputStream.Flush()
    $inputStream.Close()
    $script:rawBaseStreamWrite = $true
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "MCP stdin validation exited with $($process.ExitCode): $stderr" }
    if (-not [string]::IsNullOrWhiteSpace($stderr)) { throw "MCP stdin validation wrote unexpected stderr: $stderr" }
    $response = $stdout | ConvertFrom-Json
    if ($null -ne $response.PSObject.Properties["error"]) { throw "MCP rejected no-BOM UTF-8 stdin: $stdout" }
    return $response
}

$healthDataRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aivcp-mcp-stdin-" + [guid]::NewGuid().ToString("N"))
$hadDataRoot = Test-Path Env:AIVCP_DATA_ROOT
$previousDataRoot = $env:AIVCP_DATA_ROOT
$hadNetworkExecution = Test-Path Env:AIVCP_NETWORK_EXECUTION
$previousNetworkExecution = $env:AIVCP_NETWORK_EXECUTION
New-Item -ItemType Directory -Path $healthDataRoot -Force | Out-Null
$env:AIVCP_DATA_ROOT = $healthDataRoot
$env:AIVCP_NETWORK_EXECUTION = "false"
try {
    $unicodeProbe = "$([char]0x4E2D)$([char]0x6587)"
    $listResponse = Invoke-McpRequest ([ordered]@{ jsonrpc="2.0"; id=1; method="tools/list"; params=[ordered]@{ probe=$unicodeProbe } })
    $toolNames = @($listResponse.result.tools | ForEach-Object { [string]$_.name })
    $requiredTools = @("content_capabilities", "production_capabilities", "data_center_capabilities")
    foreach ($toolName in $requiredTools) {
        if ($toolNames -notcontains $toolName) { throw "MCP tools/list is missing $toolName." }
    }
    $capabilities = [ordered]@{}
    $requestId = 2
    foreach ($toolName in $requiredTools) {
        $response = Invoke-McpRequest ([ordered]@{ jsonrpc="2.0"; id=$requestId; method="tools/call"; params=[ordered]@{ name=$toolName; arguments=[ordered]@{} } })
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
        stdin = [ordered]@{
            encoding = "UTF-8"
            preambleBytes = $utf8NoBom.GetPreamble().Length
            rawBaseStreamWrite = $rawBaseStreamWrite
            processStartInfoPropertyAvailable = $inputEncodingPropertyAvailable
            processStartInfoPropertySetWhenAvailable = (-not $inputEncodingPropertyAvailable) -or $inputEncodingPropertySet
            unicodeJsonProbe = "PASS"
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
if ($AsJson) { Write-Output $rendered } else { Write-Output "WinPS MCP no-BOM UTF-8 stdin validation PASS." }
