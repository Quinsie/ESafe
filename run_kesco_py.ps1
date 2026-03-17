param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [string]$PythonExe = $(if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "" }),

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = 'Stop'

$pythonCommand = $null
$pythonCommandArgs = @()

if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
    if (-not (Test-Path $PythonExe)) {
        throw "Python not found: $PythonExe"
    }
    $pythonCommand = $PythonExe
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonCommandArgs = @("-3.13")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} else {
    throw "Python executable not found. Set PYTHON_EXE or install 'py' / 'python' on PATH."
}

$resolvedScript = Resolve-Path -Path $ScriptPath -ErrorAction Stop

# Force UTF-8 console I/O for Korean text output.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

Write-Host "Python: $pythonCommand $($pythonCommandArgs -join ' ')"
Write-Host "Script: $resolvedScript"

& $pythonCommand @pythonCommandArgs -X utf8 $resolvedScript @ScriptArgs
exit $LASTEXITCODE
