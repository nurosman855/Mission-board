param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('research', 'validation', 'monitor')]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-zA-Z0-9_-]{1,128}$')]
    [string]$RunId,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$BaseUrl = 'http://127.0.0.1:3000',
    [string]$FixturePath
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$worker = Join-Path $repo 'clearpage\worker_process.py'
$monitor = Join-Path $repo 'clearpage\recovery_supervisor.py'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf) -or
    -not (Test-Path -LiteralPath $monitor -PathType Leaf)) {
    throw 'Mission Control worker files not found in the selected repository.'
}

$stateDirectory = Join-Path $env:LOCALAPPDATA 'ClearPageDigital\State'
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$ledger = Join-Path $stateDirectory 'runs.sqlite'
$secretFile = Join-Path $env:LOCALAPPDATA "ClearPageDigital\Secrets\$Role.dpapi"
if (-not (Test-Path -LiteralPath $secretFile -PathType Leaf)) {
    throw "Missing encrypted key for $Role. Run Save-ScopedKey.ps1 first."
}
if ($Role -eq 'research' -and (-not $FixturePath -or -not (Test-Path -LiteralPath $FixturePath -PathType Leaf))) {
    throw 'Researcher requires an existing, reviewed fixture JSON file.'
}

$uri = $null
if (-not [Uri]::TryCreate($BaseUrl, [UriKind]::Absolute, [ref]$uri) -or
    ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.IsLoopback)) -or
    $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
    throw 'Only localhost HTTP or trusted HTTPS API URLs are supported.'
}

$python = Get-Command python -ErrorAction Stop
$priorKey = [Environment]::GetEnvironmentVariable('MC_API_KEY', 'Process')
$priorUrl = [Environment]::GetEnvironmentVariable('MC_BASE_URL', 'Process')
$priorPacket = [Environment]::GetEnvironmentVariable('MC_RESEARCH_PACKET_PATH', 'Process')
$secret = $null
$credential = $null
try {
    $encrypted = [System.IO.File]::ReadAllText($secretFile)
    $secret = ConvertTo-SecureString -String $encrypted
    $credential = [System.Net.NetworkCredential]::new('', $secret)
    $env:MC_API_KEY = $credential.Password
    $env:MC_BASE_URL = $BaseUrl
    if ($Role -eq 'research') { $env:MC_RESEARCH_PACKET_PATH = (Resolve-Path -LiteralPath $FixturePath).Path }
    else { Remove-Item Env:MC_RESEARCH_PACKET_PATH -ErrorAction SilentlyContinue }
    if ($Role -eq 'monitor') {
        & $python.Source $monitor --run-id $RunId --ledger $ledger --watch --poll-seconds 30 --max-checks 120
    } else {
        & $python.Source $worker --role $Role --run-id $RunId --ledger $ledger --allow-live --loop --poll-seconds 2 --timeout-seconds 180
    }
    if ($LASTEXITCODE -ne 0) { throw "$Role exited with an error; review the run before restarting." }
} finally {
    [Environment]::SetEnvironmentVariable('MC_API_KEY', $priorKey, 'Process')
    [Environment]::SetEnvironmentVariable('MC_BASE_URL', $priorUrl, 'Process')
    [Environment]::SetEnvironmentVariable('MC_RESEARCH_PACKET_PATH', $priorPacket, 'Process')
    if ($secret) { $secret.Dispose() }
}
