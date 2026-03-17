param(
    [string]$TomcatHome = $(if ($env:CATALINA_HOME) { $env:CATALINA_HOME } else { "$env:USERPROFILE\dev\apache-tomcat-8.5.100" }),
    [string]$JavaHome = $(if ($env:JAVA_HOME) { $env:JAVA_HOME } else { "$env:USERPROFILE\dev\jdk-11.0.25+9" })
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
