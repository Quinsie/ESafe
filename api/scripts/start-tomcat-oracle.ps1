param(
    [string]$TomcatHome = $(if ($env:CATALINA_HOME) { $env:CATALINA_HOME } else { "$env:USERPROFILE\dev\apache-tomcat-8.5.100" }),
    [string]$JavaHome   = $(if ($env:JAVA_HOME)     { $env:JAVA_HOME }     else { "$env:USERPROFILE\dev\jdk-11.0.25+9" }),
    [string]$MavenCmd   = $(if ($env:MAVEN_HOME)    { "$env:MAVEN_HOME\bin\mvn.cmd" } elseif ($env:M2_HOME) { "$env:M2_HOME\bin\mvn.cmd" } else { "$env:USERPROFILE\dev\apache-maven-3.9.9\bin\mvn.cmd" }),
    [string]$AdminUsername = $(if ($env:RISK_ADMIN_USERNAME) { $env:RISK_ADMIN_USERNAME } else { "localadmin" }),
    [string]$AdminPassword = $(if ($env:RISK_ADMIN_PASSWORD) { $env:RISK_ADMIN_PASSWORD } else { "LocalAdmin123" }),
    [string]$UserUsername  = $(if ($env:RISK_USER_USERNAME)  { $env:RISK_USER_USERNAME }  else { "localuser" }),
    [string]$UserPassword  = $(if ($env:RISK_USER_PASSWORD)  { $env:RISK_USER_PASSWORD }  else { "LocalUser123" }),
    [string]$KmaAuthKey = $(if ($env:KMA_AUTH_KEY) { $env:KMA_AUTH_KEY } else { "FtRxuKuhQneUcbirodJ3ng" }),
    [string]$AlertZoneFile = $(if ($env:RISK_ALERT_ZONE_FILE) { $env:RISK_ALERT_ZONE_FILE } else { "" }),
    [switch]$RequireAlertZoneFile,
    [int]$HttpPort = 18080,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

# Oracle mode intentionally keeps DB schema setup manual.
# Do not auto-apply DDL during app startup on persistent DBs.
# Manual setup entrypoint:
#   C:\Users\user\Downloads\kescoaitest\db\00_oracle_full_setup.sql

$apiDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$switchScript = Join-Path $PSScriptRoot "switch-db-profile.ps1"
$serverXml = Join-Path $TomcatHome "conf\server.xml"
$warSrc = Join-Path $apiDir "target\risk-api-1.0.0.war"
$warDst = Join-Path $TomcatHome "webapps\ROOT.war"
$webRootDir = Join-Path $TomcatHome "webapps\ROOT"
$shutdownBat  = Join-Path $TomcatHome "bin\shutdown.bat"
$catalinaCmd  = Join-Path $TomcatHome "bin\catalina.bat"
$setenvBat    = Join-Path $TomcatHome "bin\setenv.bat"

if (-not (Test-Path $TomcatHome)) { throw "Tomcat not found: $TomcatHome" }
if (-not (Test-Path $JavaHome)) { throw "JAVA_HOME not found: $JavaHome" }
if (-not (Test-Path $MavenCmd)) { throw "Maven not found: $MavenCmd" }
if (-not (Test-Path $switchScript)) { throw "DB switch script not found: $switchScript" }
if (-not (Test-Path $serverXml)) { throw "server.xml not found: $serverXml" }

$kmaAuthKeyTrimmed = if ($KmaAuthKey) { $KmaAuthKey.Trim() } else { "" }
if (-not [string]::IsNullOrWhiteSpace($kmaAuthKeyTrimmed)) {
    # Keep secret in process env only; do not persist raw key in setenv.bat.
    $env:KMA_AUTH_KEY = $kmaAuthKeyTrimmed
} else {
    Write-Warning "KMA_AUTH_KEY is empty. Weather refresh API may fail in Oracle runtime."
}

$alertZoneFileTrimmed = if ($AlertZoneFile) { $AlertZoneFile.Trim() } else { "" }
if (-not [string]::IsNullOrWhiteSpace($alertZoneFileTrimmed)) {
    if (-not (Test-Path $alertZoneFileTrimmed)) {
        throw "Alert zone mapping file not found: $alertZoneFileTrimmed"
    }
    $resolvedAlertZoneFile = (Resolve-Path $alertZoneFileTrimmed).Path
    $env:RISK_ALERT_ZONE_FILE = $resolvedAlertZoneFile
    Write-Host "Using alert zone file: $resolvedAlertZoneFile"
} elseif ($RequireAlertZoneFile) {
    throw "Alert zone mapping file is required in strict mode. Set -AlertZoneFile or RISK_ALERT_ZONE_FILE."
} else {
    Remove-Item Env:\RISK_ALERT_ZONE_FILE -ErrorAction SilentlyContinue
    Write-Host "Alert zone file not set. Using classpath fallback (egovframework/spring/alert-zones.csv)."
}

Write-Host "[0/6] Configure Tomcat setenv.bat"
$setenvContent = @"
@echo off
chcp 65001 > nul
set JAVA_OPTS=%JAVA_OPTS% -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8
set CATALINA_OPTS=%CATALINA_OPTS% -Dspring.profiles.active=oracle
set CATALINA_OPTS=%CATALINA_OPTS% -Drisk.security.admin.username=$AdminUsername
set CATALINA_OPTS=%CATALINA_OPTS% -Drisk.security.admin.password=$AdminPassword
set CATALINA_OPTS=%CATALINA_OPTS% -Drisk.security.user.username=$UserUsername
set CATALINA_OPTS=%CATALINA_OPTS% -Drisk.security.user.password=$UserPassword
if not "%KMA_AUTH_KEY%"=="" set CATALINA_OPTS=%CATALINA_OPTS% -Dkma.auth.key=%KMA_AUTH_KEY%
if not "%RISK_ALERT_ZONE_FILE%"=="" set CATALINA_OPTS=%CATALINA_OPTS% -Drisk.weather.alert.zone.file="%RISK_ALERT_ZONE_FILE%"
"@
try {
    Set-Content -Path $setenvBat -Value $setenvContent -Encoding ASCII -Force
}
catch [System.UnauthorizedAccessException] {
    [System.IO.File]::WriteAllText($setenvBat, $setenvContent, [System.Text.Encoding]::ASCII)
}

Write-Host "[1/6] Switch DB profile -> oracle"
powershell -ExecutionPolicy Bypass -File $switchScript -Profile oracle | Out-Host

Write-Host "[2/6] Configure Tomcat HTTP port -> $HttpPort"
$xml = Get-Content $serverXml -Raw
$updated = [regex]::Replace($xml, 'Connector port="\d+" protocol="HTTP/1.1"', ('Connector port="' + $HttpPort + '" protocol="HTTP/1.1"'), 1)
$updated = [regex]::Replace($updated, ('(Connector port="' + $HttpPort + '" protocol="HTTP/1\.1")(?![^>]*URIEncoding=)'), '$1 URIEncoding="UTF-8" useBodyEncodingForURI="true"', 1)
if ($updated -ne $xml) {
    Set-Content -Path $serverXml -Value $updated -Encoding UTF8
} elseif ($xml -notmatch ('Connector port="' + $HttpPort + '" protocol="HTTP/1.1"')) {
    throw "Could not update HTTP connector port in server.xml"
}

if (-not $SkipBuild) {
    Write-Host "[3/6] Build WAR"
    $env:JAVA_HOME = $JavaHome
    $env:Path = "$JavaHome\bin;$env:Path"
    Push-Location $apiDir
    try {
        $env:MAVEN_OPTS = "-Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true"
        & $MavenCmd -q -DskipTests package
    } finally {
        Pop-Location
    }
} else {
    Write-Host "[3/6] Build WAR (skip)"
}

if (-not (Test-Path $warSrc)) { throw "WAR not found after build: $warSrc" }

Write-Host "[4/6] Stop Tomcat (if running)"
$env:CATALINA_HOME = $TomcatHome
$env:CATALINA_BASE = $TomcatHome
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
try { & $shutdownBat 2>&1 | Out-Null } catch { }
Start-Sleep -Seconds 3

Write-Host "[5/6] Deploy ROOT.war"
if (Test-Path $webRootDir) { Remove-Item -Path $webRootDir -Recurse -Force }
if (Test-Path $warDst) { Remove-Item -Path $warDst -Force }
Copy-Item -Path $warSrc -Destination $warDst -Force

Write-Host "[6/6] Start Tomcat (UTF-8 console)"
$cmdArg = "chcp 65001 >nul & `"$catalinaCmd`" run"
Start-Process -FilePath "cmd.exe" -ArgumentList "/k", $cmdArg

Write-Host ""
Write-Host "Tomcat started: http://localhost:$HttpPort/"
Write-Host "Dashboard: http://localhost:$HttpPort/riskDashboard.do"
Write-Host "Login (admin): $AdminUsername / $AdminPassword"
Write-Host "Login (user):  $UserUsername / $UserPassword"
