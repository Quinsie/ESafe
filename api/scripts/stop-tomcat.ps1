param(
    [string]$TomcatHome = "C:\Users\user\dev\apache-tomcat-8.5.100",
    [string]$JavaHome = "C:\Users\user\dev\jdk-11.0.25+9"
)

$ErrorActionPreference = "Stop"

$shutdownBat = Join-Path $TomcatHome "bin\shutdown.bat"
if (-not (Test-Path $shutdownBat)) { throw "shutdown.bat not found: $shutdownBat" }

$env:CATALINA_HOME = $TomcatHome
$env:CATALINA_BASE = $TomcatHome
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
Push-Location (Join-Path $TomcatHome "bin")
try {
    cmd /c "shutdown.bat" | Out-Host
} finally {
    Pop-Location
}
Write-Host "Tomcat stop requested."
