param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = 'Stop'

$pythonExe = "C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}

$resolvedScript = Resolve-Path -Path $ScriptPath -ErrorAction Stop

# Force UTF-8 console I/O for Korean text output.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

Write-Host "Python: $pythonExe"
Write-Host "Script: $resolvedScript"

& $pythonExe -X utf8 $resolvedScript @ScriptArgs
exit $LASTEXITCODE

