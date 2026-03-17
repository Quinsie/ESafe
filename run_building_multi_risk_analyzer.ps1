$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $projectRoot "run_kesco_py.ps1"
$script = Join-Path $projectRoot "building_multi_risk_analyzer.py"

& $runner $script @args
exit $LASTEXITCODE

