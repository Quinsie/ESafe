param(
    [string]$JavaHome = "C:\Users\user\dev\jdk-11.0.25+9",
    [string]$MavenCmd = "C:\Users\user\dev\apache-maven-3.9.9\bin\mvn.cmd",
    [ValidateSet("h2", "oracle")]
    [string[]]$Profiles = @("h2", "oracle")
)

$ErrorActionPreference = "Stop"

$apiDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$springDir = Join-Path $apiDir "src\main\resources\egovframework\spring"
$warSrc = Join-Path $apiDir "target\risk-api-1.0.0.war"
$targetDir = Join-Path $apiDir "target"
$jarExe = Join-Path $JavaHome "bin\jar.exe"

if (-not (Test-Path $JavaHome)) { throw "JAVA_HOME not found: $JavaHome" }
if (-not (Test-Path $MavenCmd)) { throw "Maven not found: $MavenCmd" }
if (-not (Test-Path $jarExe)) { throw "jar.exe not found: $jarExe" }

$buildResults = New-Object System.Collections.Generic.List[object]

Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-EmbeddedDriver([string]$WarPath) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($WarPath)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq "WEB-INF/classes/egovframework/spring/risk-db.properties" } | Select-Object -First 1
        if (-not $entry) { return "unknown" }
        $sr = New-Object System.IO.StreamReader($entry.Open())
        try {
            $text = $sr.ReadToEnd()
        } finally {
            $sr.Dispose()
        }
    } finally {
        $zip.Dispose()
    }

    if ($text -match "risk\.db\.driver=org\.h2\.Driver") { return "h2" }
    if ($text -match "risk\.db\.driver=oracle\.jdbc\.OracleDriver") { return "oracle" }
    return "unknown"
}

function Stamp-ProfileWar([string]$Profile) {
    $profileFile = Join-Path $springDir ("risk-db-" + $Profile + ".properties")
    if (-not (Test-Path $profileFile)) { throw "Profile file not found: $profileFile" }

    $warDst = Join-Path $targetDir ("risk-api-" + $Profile + ".war")
    Copy-Item -Path $warSrc -Destination $warDst -Force

    $tmpRoot = Join-Path $env:TEMP ("risk-war-profile-" + $Profile + "-" + [guid]::NewGuid().ToString("N"))
    $tmpSpring = Join-Path $tmpRoot "WEB-INF\classes\egovframework\spring"
    New-Item -Path $tmpSpring -ItemType Directory -Force | Out-Null
    Copy-Item -Path $profileFile -Destination (Join-Path $tmpSpring "risk-db.properties") -Force

    try {
        & $jarExe uf $warDst -C $tmpRoot "WEB-INF/classes/egovframework/spring/risk-db.properties"
    } finally {
        if (Test-Path $tmpRoot) { Remove-Item -Path $tmpRoot -Recurse -Force }
    }

    $driver = Get-EmbeddedDriver -WarPath $warDst
    if ($driver -ne $Profile) {
        throw "Embedded profile mismatch: expected '$Profile', got '$driver' in $warDst"
    }

    $item = Get-Item $warDst
    return [pscustomobject]@{
        Profile = $Profile
        WarPath = $item.FullName
        Size = $item.Length
        SHA256 = (Get-FileHash -Path $warDst -Algorithm SHA256).Hash
        EmbeddedProfile = $driver
        BuiltAt = (Get-Date)
    }
}

Write-Host "=== Build base WAR (single Maven package) ==="
$env:JAVA_HOME = $JavaHome
$env:Path = "$JavaHome\bin;$env:Path"
Push-Location $apiDir
try {
    & $MavenCmd -q -DskipTests package
} finally {
    Pop-Location
}

if (-not (Test-Path $warSrc)) { throw "WAR not found after build: $warSrc" }

foreach ($profile in $Profiles) {
    Write-Host ""
    Write-Host "=== Stamp WAR profile: $profile ==="
    $result = Stamp-ProfileWar -Profile $profile
    $buildResults.Add($result) | Out-Null
}

Write-Host ""
Write-Host "Build complete."
$buildResults | Select-Object Profile, EmbeddedProfile, WarPath, Size, SHA256, BuiltAt | Format-Table -AutoSize
