param(
    [string]$BaseUrl = "http://localhost:18080",
    [string]$Username = "localadmin",
    [string]$Password = "LocalAdmin123"
)

$ErrorActionPreference = "Stop"

$gDet = [string][char]0xD0D0
$gSev = [string][char]0xC2EC
$gWar = [string][char]0xACBD
$gCau = [string][char]0xC8FC
$gInt = [string][char]0xAD00
$gNon = [string][char]0x00B7

$severityRank = @{ "NONE" = 0; "INTEREST" = 1; "CAUTION" = 2; "WARNING" = 3; "SEVERE" = 4; "DETECTED" = 5 }

function New-StackStat {
    return @{ DET = 0; SEV = 0; WAR = 0; CAU = 0; INT = 0 }
}

function Normalize-Text {
    param([string]$Text)
    if ($null -eq $Text) { return "" }
    return (($Text -replace "\s+", "").Trim())
}

function Make-Key {
    param([string]$RegionNm, [string]$DistrictNm)
    return ((Normalize-Text $RegionNm) + "|" + (Normalize-Text $DistrictNm))
}

function Grade-To-Symbol {
    param([string]$Grade)
    $g = if ($null -eq $Grade) { "NONE" } else { $Grade.Trim().ToUpperInvariant() }
    switch ($g) {
        "DETECTED" { return $gDet }
        "SEVERE" { return $gSev }
        "WARNING" { return $gWar }
        "CAUTION" { return $gCau }
        "INTEREST" { return $gInt }
        default { return $gNon }
    }
}

function Grade-To-Rank {
    param([string]$Grade)
    $g = if ($null -eq $Grade) { "NONE" } else { $Grade.Trim().ToUpperInvariant() }
    if ($severityRank.ContainsKey($g)) { return [int]$severityRank[$g] }
    return 0
}

function Add-Stack {
    param($Stack, [string]$Grade)
    $g = if ($null -eq $Grade) { "NONE" } else { $Grade.Trim().ToUpperInvariant() }
    switch ($g) {
        "DETECTED" { $Stack["DET"] = [int]$Stack["DET"] + 1 }
        "SEVERE" { $Stack["SEV"] = [int]$Stack["SEV"] + 1 }
        "WARNING" { $Stack["WAR"] = [int]$Stack["WAR"] + 1 }
        "CAUTION" { $Stack["CAU"] = [int]$Stack["CAU"] + 1 }
        "INTEREST" { $Stack["INT"] = [int]$Stack["INT"] + 1 }
    }
}

function Is-ValidWgs84 {
    param([double]$Lon, [double]$Lat)
    return ($Lon -ge 124.0 -and $Lon -le 132.5 -and $Lat -ge 32.5 -and $Lat -le 39.5)
}

function Is-LikelyEpsg5186 {
    param([double]$X, [double]$Y)
    return ($X -gt 50000.0 -and $X -lt 450000.0 -and $Y -gt 100000.0 -and $Y -lt 800000.0)
}

function Meridional-Arc {
    param([double]$A, [double]$E2, [double]$Lat)
    return $A * ((1.0 - $E2 / 4.0 - 3.0 * [Math]::Pow($E2, 2) / 64.0 - 5.0 * [Math]::Pow($E2, 3) / 256.0) * $Lat `
            - (3.0 * $E2 / 8.0 + 3.0 * [Math]::Pow($E2, 2) / 32.0 + 45.0 * [Math]::Pow($E2, 3) / 1024.0) * [Math]::Sin(2.0 * $Lat) `
            + (15.0 * [Math]::Pow($E2, 2) / 256.0 + 45.0 * [Math]::Pow($E2, 3) / 1024.0) * [Math]::Sin(4.0 * $Lat) `
            - (35.0 * [Math]::Pow($E2, 3) / 3072.0) * [Math]::Sin(6.0 * $Lat))
}

function Convert-Epsg5186ToWgs84 {
    param([double]$X, [double]$Y)

    $a = 6378137.0
    $f = 1.0 / 298.257222101
    $e2 = 2 * $f - ($f * $f)
    $ep2 = $e2 / (1.0 - $e2)
    $k0 = 1.0
    $lon0 = [Math]::PI * 127.0 / 180.0
    $lat0 = [Math]::PI * 38.0 / 180.0
    $falseEasting = 200000.0
    $falseNorthing = 600000.0

    $m0 = Meridional-Arc -A $a -E2 $e2 -Lat $lat0
    $m = $m0 + ($Y - $falseNorthing) / $k0
    $mu = $m / ($a * (1.0 - $e2 / 4.0 - 3.0 * [Math]::Pow($e2, 2) / 64.0 - 5.0 * [Math]::Pow($e2, 3) / 256.0))

    $e1 = (1.0 - [Math]::Sqrt(1.0 - $e2)) / (1.0 + [Math]::Sqrt(1.0 - $e2))
    $j1 = 3.0 * $e1 / 2.0 - 27.0 * [Math]::Pow($e1, 3) / 32.0
    $j2 = 21.0 * [Math]::Pow($e1, 2) / 16.0 - 55.0 * [Math]::Pow($e1, 4) / 32.0
    $j3 = 151.0 * [Math]::Pow($e1, 3) / 96.0
    $j4 = 1097.0 * [Math]::Pow($e1, 4) / 512.0

    $fp = $mu + $j1 * [Math]::Sin(2.0 * $mu) + $j2 * [Math]::Sin(4.0 * $mu) + $j3 * [Math]::Sin(6.0 * $mu) + $j4 * [Math]::Sin(8.0 * $mu)
    $sinFp = [Math]::Sin($fp)
    $cosFp = [Math]::Cos($fp)
    $tanFp = [Math]::Tan($fp)

    $n1 = $a / [Math]::Sqrt(1.0 - $e2 * $sinFp * $sinFp)
    $r1 = $a * (1.0 - $e2) / [Math]::Pow(1.0 - $e2 * $sinFp * $sinFp, 1.5)
    $c1 = $ep2 * $cosFp * $cosFp
    $t1 = $tanFp * $tanFp
    $d = ($X - $falseEasting) / ($n1 * $k0)

    $q1 = $d * $d / 2.0
    $q2 = (5.0 + 3.0 * $t1 + 10.0 * $c1 - 4.0 * $c1 * $c1 - 9.0 * $ep2) * [Math]::Pow($d, 4) / 24.0
    $q3 = (61.0 + 90.0 * $t1 + 298.0 * $c1 + 45.0 * $t1 * $t1 - 252.0 * $ep2 - 3.0 * $c1 * $c1) * [Math]::Pow($d, 6) / 720.0
    $lat = $fp - ($n1 * $tanFp / $r1) * ($q1 - $q2 + $q3)

    $q4 = $d
    $q5 = (1.0 + 2.0 * $t1 + $c1) * [Math]::Pow($d, 3) / 6.0
    $q6 = (5.0 - 2.0 * $c1 + 28.0 * $t1 - 3.0 * $c1 * $c1 + 8.0 * $ep2 + 24.0 * $t1 * $t1) * [Math]::Pow($d, 5) / 120.0
    $lon = $lon0 + ($q4 - $q5 + $q6) / $cosFp

    return @{ lon = (180.0 * $lon / [Math]::PI); lat = (180.0 * $lat / [Math]::PI) }
}

function Normalize-GeoPoint {
    param([double]$RawX, [double]$RawY)
    if (Is-ValidWgs84 -Lon $RawX -Lat $RawY) {
        return @{ lon = $RawX; lat = $RawY }
    }
    if (Is-LikelyEpsg5186 -X $RawX -Y $RawY) {
        $p = Convert-Epsg5186ToWgs84 -X $RawX -Y $RawY
        if (Is-ValidWgs84 -Lon ([double]$p.lon) -Lat ([double]$p.lat)) {
            return $p
        }
    }
    return $null
}

function Login-WebSession {
    param([string]$BaseUrl, [string]$Username, [string]$Password)

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $loginPage = Invoke-WebRequest -Uri "$BaseUrl/login.do" -WebSession $session -UseBasicParsing

    $csrfName = ""
    $csrfToken = ""
    $tokenTag = [regex]::Match(
        $loginPage.Content,
        '<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]+)"',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if ($tokenTag.Success) {
        $csrfName = $tokenTag.Groups[1].Value
        $csrfToken = $tokenTag.Groups[2].Value
    }

    $form = @{ username = $Username; password = $Password }
    if ($csrfName -ne "") { $form[$csrfName] = $csrfToken }

    Invoke-WebRequest -Uri "$BaseUrl/perform_login.do" -Method Post -Body $form -WebSession $session -UseBasicParsing | Out-Null
    return $session
}

function Fetch-Json {
    param([string]$Uri, [Microsoft.PowerShell.Commands.WebRequestSession]$Session)
    $raw = Invoke-WebRequest -Uri $Uri -WebSession $Session -UseBasicParsing
    return ($raw.Content | ConvertFrom-Json)
}

function In-Polygon {
    param([double]$Px, [double]$Py, [array]$Poly)
    $inside = $false
    $j = $Poly.Count - 1
    for ($i = 0; $i -lt $Poly.Count; $i++) {
        $xi = [double]$Poly[$i].x; $yi = [double]$Poly[$i].y
        $xj = [double]$Poly[$j].x; $yj = [double]$Poly[$j].y
        $cross = (($yi -gt $Py) -ne ($yj -gt $Py)) -and ($Px -lt (($xj - $xi) * ($Py - $yi) / (($yj - $yi) + 1e-12) + $xi))
        if ($cross) { $inside = -not $inside }
        $j = $i
    }
    return $inside
}

function Draw-KoreaBackdrop {
    param([int]$Width, [int]$Height)

    $chars = New-Object 'char[,]' $Height, $Width
    $inside = New-Object 'bool[,]' $Height, $Width
    for ($r = 0; $r -lt $Height; $r++) {
        for ($c = 0; $c -lt $Width; $c++) {
            $chars[$r, $c] = ' '
            $inside[$r, $c] = $false
        }
    }

    $poly = @(
        @{ x = 0.46; y = 0.03 }, @{ x = 0.58; y = 0.06 }, @{ x = 0.70; y = 0.14 },
        @{ x = 0.79; y = 0.26 }, @{ x = 0.81; y = 0.40 }, @{ x = 0.86; y = 0.54 },
        @{ x = 0.82; y = 0.70 }, @{ x = 0.74; y = 0.82 }, @{ x = 0.64; y = 0.90 },
        @{ x = 0.56; y = 0.95 }, @{ x = 0.48; y = 0.89 }, @{ x = 0.40; y = 0.80 },
        @{ x = 0.33; y = 0.69 }, @{ x = 0.28; y = 0.56 }, @{ x = 0.26; y = 0.43 },
        @{ x = 0.27; y = 0.30 }, @{ x = 0.31; y = 0.19 }, @{ x = 0.37; y = 0.10 }
    )

    for ($r = 0; $r -lt $Height; $r++) {
        $ny = if ($Height -le 1) { 0.0 } else { [double]$r / [double]($Height - 1) }
        for ($c = 0; $c -lt $Width; $c++) {
            $nx = if ($Width -le 1) { 0.0 } else { [double]$c / [double]($Width - 1) }
            $main = In-Polygon -Px $nx -Py $ny -Poly $poly
            $dx = ($nx - 0.53) / 0.08
            $dy = ($ny - 0.96) / 0.04
            $jeju = (($dx * $dx) + ($dy * $dy)) -le 1.0
            if ($main -or $jeju) {
                $inside[$r, $c] = $true
                $chars[$r, $c] = [char]0x00B7
            }
        }
    }

    $dr = @(-1,1,0,0); $dc = @(0,0,-1,1)
    for ($r = 1; $r -lt ($Height - 1); $r++) {
        for ($c = 1; $c -lt ($Width - 1); $c++) {
            if (-not $inside[$r, $c]) { continue }
            for ($k = 0; $k -lt 4; $k++) {
                $nr = $r + $dr[$k]; $nc = $c + $dc[$k]
                if (-not $inside[$nr, $nc]) {
                    $chars[$r, $c] = [char]0x2588
                    break
                }
            }
        }
    }

    return @{ chars = $chars; inside = $inside }
}

$session = Login-WebSession -BaseUrl $BaseUrl -Username $Username -Password $Password

$branchRes = Fetch-Json -Uri "$BaseUrl/selectBranchSummary.do" -Session $session
$branchNames = @()
if ($branchRes -and $branchRes.data) {
    $branchNames = $branchRes.data | ForEach-Object { [string]$_.branchNm } | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
}

$coordByKey = @{}
foreach ($bn in $branchNames) {
    $u = "$BaseUrl/selectRiskMapDistrictLayer.do?branchNm=$([uri]::EscapeDataString($bn))"
    $layer = Fetch-Json -Uri $u -Session $session
    if ($null -eq $layer -or $null -eq $layer.data) { continue }

    foreach ($row in $layer.data) {
        $regionNm = [string]$row.regionNm
        $districtNm = [string]$row.districtNm
        $key = Make-Key -RegionNm $regionNm -DistrictNm $districtNm
        if ($key -eq "|") { continue }

        $rawX = 0.0
        $rawY = 0.0
        [double]::TryParse([string]$row.centerLon, [ref]$rawX) | Out-Null
        [double]::TryParse([string]$row.centerLat, [ref]$rawY) | Out-Null

        $geo = Normalize-GeoPoint -RawX $rawX -RawY $rawY
        if ($null -eq $geo) { continue }

        if (-not $coordByKey.ContainsKey($key)) {
            $coordByKey[$key] = [ordered]@{
                regionNm = $regionNm
                districtNm = $districtNm
                lon = [double]$geo.lon
                lat = [double]$geo.lat
            }
        }
    }
}

$regionRes = Fetch-Json -Uri "$BaseUrl/selectRegionSummary.do" -Session $session
$regionNames = @()
if ($regionRes -and $regionRes.data) {
    $regionNames = $regionRes.data | ForEach-Object { [string]$_.regionNm } | Where-Object { $_ -and $_.Trim() -ne "" } | Select-Object -Unique
}

$weatherByKey = @{}
$stackByRegion = @{}

foreach ($rn in $regionNames) {
    $u = "$BaseUrl/selectWeatherRiskScore.do?regionNm=$([uri]::EscapeDataString($rn))"
    $wr = Fetch-Json -Uri $u -Session $session
    if ($null -eq $wr -or $null -eq $wr.data) { continue }

    if (-not $stackByRegion.ContainsKey($rn)) {
        $stackByRegion[$rn] = New-StackStat
    }

    foreach ($row in $wr.data) {
        $regionNm = [string]$row.regionNm
        $districtNm = [string]$row.districtNm
        $grade = [string]$row.wildfireGrade
        $score = 0.0
        [double]::TryParse([string]$row.wildfireScore, [ref]$score) | Out-Null

        $key = Make-Key -RegionNm $regionNm -DistrictNm $districtNm
        if ($key -eq "|") { continue }

        $candidateRank = Grade-To-Rank -Grade $grade
        if ($weatherByKey.ContainsKey($key)) {
            $currRank = Grade-To-Rank -Grade ([string]$weatherByKey[$key].wildfireGrade)
            if ($candidateRank -gt $currRank) {
                $weatherByKey[$key] = [ordered]@{ regionNm = $regionNm; districtNm = $districtNm; wildfireGrade = $grade; wildfireScore = $score }
            }
        } else {
            $weatherByKey[$key] = [ordered]@{ regionNm = $regionNm; districtNm = $districtNm; wildfireGrade = $grade; wildfireScore = $score }
        }

        if (-not $stackByRegion.ContainsKey($regionNm)) {
            $stackByRegion[$regionNm] = New-StackStat
        }
        Add-Stack -Stack $stackByRegion[$regionNm] -Grade $grade
    }
}

$rawWidth = 160
$rawHeight = 44
try { $rawWidth = [Console]::WindowWidth; $rawHeight = [Console]::WindowHeight } catch { }
$mapWidth = [Math]::Max($rawWidth - 2, 120)
$mapHeight = [Math]::Max($rawHeight - 16, 24)

$backdrop = Draw-KoreaBackdrop -Width $mapWidth -Height $mapHeight
$chars = $backdrop.chars

$cellRank = New-Object 'int[,]' $mapHeight, $mapWidth
for ($r = 0; $r -lt $mapHeight; $r++) { for ($c = 0; $c -lt $mapWidth; $c++) { $cellRank[$r,$c] = -1 } }

$minLon = 124.0; $maxLon = 132.2
$minLat = 33.0;  $maxLat = 39.3
$matchedPointCount = 0

foreach ($k in $coordByKey.Keys) {
    $pt = $coordByKey[$k]
    $lon = [double]$pt.lon
    $lat = [double]$pt.lat
    if ($lon -lt $minLon -or $lon -gt $maxLon -or $lat -lt $minLat -or $lat -gt $maxLat) { continue }

    $x = [int]([Math]::Round((($lon - $minLon) / ($maxLon - $minLon)) * ($mapWidth - 1)))
    $y = [int]([Math]::Round((($maxLat - $lat) / ($maxLat - $minLat)) * ($mapHeight - 1)))

    $grade = "NONE"
    if ($weatherByKey.ContainsKey($k)) {
        $grade = [string]$weatherByKey[$k].wildfireGrade
        $matchedPointCount++
    }
    $rank = Grade-To-Rank -Grade $grade
    if ($rank -gt $cellRank[$y,$x]) {
        $cellRank[$y,$x] = $rank
        $chars[$y,$x] = (Grade-To-Symbol -Grade $grade)[0]
    }
}

$lines = New-Object System.Collections.Generic.List[string]
for ($r = 0; $r -lt $mapHeight; $r++) {
    $arr = New-Object 'char[]' $mapWidth
    for ($c = 0; $c -lt $mapWidth; $c++) { $arr[$c] = $chars[$r,$c] }
    $lines.Add((-join $arr)) | Out-Null
}

Clear-Host
Write-Host ("KOREA DATA MAP (RAW DATA PLOT)  " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Host ("Symbols: " + $gDet + "=탐  " + $gSev + "=심  " + $gWar + "=경  " + $gCau + "=주  " + $gInt + "=관  " + $gNon + "=none")
Write-Host ("Data counts: branches=" + $branchNames.Count + ", coord-districts=" + $coordByKey.Count + ", weather-districts=" + $weatherByKey.Count + ", matched=" + $matchedPointCount)
Write-Host ("Source: " + $BaseUrl + "/selectBranchSummary.do + /selectRiskMapDistrictLayer.do + /selectWeatherRiskScore.do")
Write-Host ""
foreach ($ln in $lines) { Write-Host $ln }

Write-Host ""
Write-Host ("Regional stacks (탐/심/경/주/관)")
$rowsOut = @()
foreach ($rn in ($stackByRegion.Keys | Sort-Object)) {
    $s = $stackByRegion[$rn]
    $rowsOut += ([pscustomobject]@{
        Region = $rn
        DET = $s["DET"]
        SEV = $s["SEV"]
        WAR = $s["WAR"]
        CAU = $s["CAU"]
        INT = $s["INT"]
    })
}
if ($rowsOut.Count -gt 0) {
    $rowsOut | Format-Table -AutoSize
} else {
    Write-Host "(no regional weather rows)"
}
