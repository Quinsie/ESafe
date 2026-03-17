param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("oracle", "h2")]
    [string]$Profile
)

$ErrorActionPreference = "Stop"

$springDir = Join-Path $PSScriptRoot "..\src\main\resources\egovframework\spring"
$activeFile = Join-Path $springDir "risk-db.properties"
$srcFile = Join-Path $springDir ("risk-db-" + $Profile + ".properties")

if (-not (Test-Path $srcFile)) {
    throw "Profile file not found: $srcFile"
}

Copy-Item -Path $srcFile -Destination $activeFile -Force
Write-Host "Switched DB profile to '$Profile'"
Write-Host "Active file: $activeFile"
