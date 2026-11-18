param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('research', 'validation', 'monitor', 'coordinator')]
    [string]$Role
)

$ErrorActionPreference = 'Stop'
$secretDirectory = Join-Path $env:LOCALAPPDATA 'ClearPageDigital\Secrets'
New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
$target = Join-Path $secretDirectory "$Role.dpapi"
if (Test-Path -LiteralPath $target) {
    throw 'A key already exists for this role. Back it up or rotate it explicitly before replacing it.'
}

# DPAPI protects this secret for the current Windows user on this computer.
# The Scheduled Task must run under the same account; there is no shared key.
$secureKey = Read-Host "Enter the $Role Mission Control API key" -AsSecureString
if ($secureKey.Length -eq 0) { throw 'An empty API key is not allowed.' }
$encrypted = ConvertFrom-SecureString -SecureString $secureKey
try {
    [System.IO.File]::WriteAllText($target, $encrypted, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Saved an encrypted $Role key for this Windows user."
} finally {
    $secureKey.Dispose()
}
