param(
    [string]$BranchCsvPath = "",
    [string]$GeneralCsvPath = "",
    [string]$SelfCsvPath = "",
    [string]$OutputSqlPath = "",
    [int]$TargetRows = 10000,
    [int]$GeneralSampleRows = 10000,
    [int]$SelfSampleRows = 10000
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

if (-not $BranchCsvPath) { $BranchCsvPath = Join-Path $projectRoot "사업소별 분석결과\광주전남본부\광주전남본부직할\통합위험분석_광주전남본부직할_20260303.csv" }
if (-not $GeneralCsvPath) { $GeneralCsvPath = Join-Path $projectRoot "설비데이터\일반용 샘플 데이터2.csv" }
if (-not $SelfCsvPath) { $SelfCsvPath = Join-Path $projectRoot "설비데이터\자가용 샘플 데이터.csv" }
if (-not $OutputSqlPath) { $OutputSqlPath = Join-Path $projectRoot "api\src\main\resources\egovframework\spring\data-h2.sql" }

function Normalize-Text([object]$v) {
    if ($null -eq $v) { return "" }
    $s = [string]$v
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    return (($s.Trim()) -replace "\s+", " ")
}

function Normalize-Status([object]$v) {
    return (Normalize-Text $v) -replace "\s+", ""
}

function Normalize-Address([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    $s = [regex]::Replace($s, "\s+\d{3,}\s+\d+\s+(?:일반건축물|집합건축물)$", "")
    $s = [regex]::Replace($s, "\s+\d+\s+일반\s+", " ")
    $s = ($s -replace "\s+", " ").Trim()
    return $s
}

function Sql-Escape([string]$s) {
    if ($null -eq $s) { return "" }
    return $s.Replace("'", "''")
}

function To-IntOrNull([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "NULL" }
    try {
        return [string]([int][double]$s)
    }
    catch {
        return "NULL"
    }
}

function To-DoubleOrZero([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "0" }
    try {
        return ([double]$s).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        return "0"
    }
}

function Grade-ToCode([string]$v) {
    $x = Normalize-Text $v
    if ($x -in @('A','B','C','D','E')) { return $x }
    switch ($x) {
        '안전' { return 'A' }
        '양호' { return 'B' }
        '관심' { return 'B' }
        '보통' { return 'C' }
        '주의' { return 'C' }
        '노후' { return 'D' }
        '경고' { return 'D' }
        '위험' { return 'E' }
        '고령' { return 'E' }
        '매우위험' { return 'E' }
        default { return 'C' }
    }
}

function Select-Prioritized([object[]]$rows, [int]$limit, [scriptblock]$isPriority) {
    $priority = New-Object System.Collections.Generic.List[object]
    $others = New-Object System.Collections.Generic.List[object]
    foreach ($r in $rows) {
        if (& $isPriority $r) { $priority.Add($r) } else { $others.Add($r) }
    }
    $ordered = New-Object System.Collections.Generic.List[object]
    $ordered.AddRange($priority)
    $ordered.AddRange($others)
    if ($ordered.Count -le $limit) { return $ordered.ToArray() }
    return @($ordered | Select-Object -First $limit)
}

if (-not (Test-Path $BranchCsvPath)) { throw "Branch CSV not found: $BranchCsvPath" }
if (-not (Test-Path $GeneralCsvPath)) { throw "General CSV not found: $GeneralCsvPath" }
if (-not (Test-Path $SelfCsvPath)) { throw "Self CSV not found: $SelfCsvPath" }

$generalAll = Import-Csv -Path $GeneralCsvPath -Encoding UTF8
$selfAll = Import-Csv -Path $SelfCsvPath -Encoding UTF8
$branchAll = Import-Csv -Path $BranchCsvPath -Encoding UTF8

$generalSample = Select-Prioritized -rows $generalAll -limit $GeneralSampleRows -isPriority {
    param($r)
    $s = Normalize-Status $r.결과
    return ($s.Contains('부적합') -or $s.Contains('부재종결'))
}
$selfSample = Select-Prioritized -rows $selfAll -limit $SelfSampleRows -isPriority {
    param($r)
    $s = Normalize-Status $r.결과
    return $s.Contains('불합격')
}

$addrSet = New-Object System.Collections.Generic.HashSet[string]
foreach ($r in $generalSample) {
    $a = Normalize-Address $r.주소
    if ($a) { $null = $addrSet.Add($a) }
}
foreach ($r in $selfSample) {
    $a = Normalize-Address $r.지번주소
    if (-not $a) { $a = Normalize-Address $r.주소 }
    if (-not $a) { $a = Normalize-Address $r.도로명주소 }
    if ($a) { $null = $addrSet.Add($a) }
}

$matched = New-Object System.Collections.Generic.List[object]
foreach ($row in $branchAll) {
    $a = Normalize-Address $row.주소
    if ($addrSet.Contains($a)) {
        $row | Add-Member -NotePropertyName _NORM_ADDR -NotePropertyValue $a -Force
        $matched.Add($row)
    }
}

$selected = New-Object System.Collections.Generic.List[object]
if ($matched.Count -ge $TargetRows) {
    $selected.AddRange(($matched | Select-Object -First $TargetRows))
} else {
    $selected.AddRange($matched)
    if ($matched.Count -gt 0) {
        $idx = 0
        while ($selected.Count -lt $TargetRows) {
            $selected.Add($matched[$idx % $matched.Count])
            $idx += 1
        }
    }
}

$analDate = ""
if ([regex]::IsMatch((Split-Path $BranchCsvPath -Leaf), "(\d{8})")) {
    $analDate = [regex]::Match((Split-Path $BranchCsvPath -Leaf), "(\d{8})").Groups[1].Value
}
$branchNm = "광주전남본부직할"

$sb = New-Object System.Text.StringBuilder
$null = $sb.AppendLine("-- H2 sample data ($branchNm $($selected.Count) rows, matched-address-priority)")
$null = $sb.AppendLine("")

foreach ($row in $selected) {
    $a0 = Sql-Escape (Normalize-Text $row.A0)
    $a13 = Sql-Escape (Normalize-Text ($(if ($row.A13) { $row.A13 } else { $row.용도명 })))
    $a17 = Sql-Escape (Normalize-Text $row.A17)
    $a19 = Sql-Escape (Normalize-Text $row.A19)
    $regionNm = Sql-Escape (Normalize-Text $row.지역)
    $districtNm = Sql-Escape (Normalize-Text $row.구군)
    $regionCd = Sql-Escape (Normalize-Text $row.지역코드)
    $addr = Sql-Escape (Normalize-Address $row.주소)

    $lon = To-DoubleOrZero ($(if ($row.경도) { $row.경도 } else { $row.중심점X }))
    $lat = To-DoubleOrZero ($(if ($row.위도) { $row.위도 } else { $row.중심점Y }))

    $buildYear = To-IntOrNull $row.건축년도
    $buildAge = To-IntOrNull $row.건물연령
    $completionDate = Sql-Escape (Normalize-Text $row.A24)

    $ageGrade = Grade-ToCode (Normalize-Text $row.노후등급)
    $ageScore = To-IntOrNull $row.노후점수

    $floodGrade = Grade-ToCode (Normalize-Text $row.홍수등급)
    $floodScore = To-IntOrNull $row.홍수점수

    $landslideDist = To-DoubleOrZero $row.산사태거리
    $landslideGrade = Grade-ToCode (Normalize-Text $row.산사태등급)
    $landslideScore = To-IntOrNull $row.산사태점수

    $fireScore = To-IntOrNull $row.화재점수
    $prevFire = Sql-Escape (Normalize-Text $row.화재발생일)

    $landUseScore = To-IntOrNull $row.용도점수
    $totalScore = To-DoubleOrZero $row.종합점수
    $totalGrade = Sql-Escape (Normalize-Text $row.종합등급)

    $riskCd = Normalize-Text $row.위험코드
    if (-not $riskCd) { $riskCd = Grade-ToCode $totalGrade }
    $riskCd = Sql-Escape $riskCd

    $line = "INSERT INTO TB_BUILDING_RISK " +
            "(BRANCH_NM,A0,A13,A17,A19,REGION_NM,DISTRICT_NM,REGION_CD,ADDR,LON,LAT,BUILD_YEAR,BUILD_AGE,A24,AGE_GRADE,AGE_SCORE,FLOOD_GRADE,FLOOD_SCORE,LANDSLIDE_DIST,LANDSLIDE_GRADE,LANDSLIDE_SCORE,FIRE_SCORE,PREV_FIRE_OCCUR_DATE,LAND_USE_SCORE,TOTAL_SCORE,TOTAL_GRADE,RISK_CD,ANAL_DATE) VALUES " +
            "('$branchNm','$a0','$a13','$a17','$a19','$regionNm','$districtNm','$regionCd','$addr',$lon,$lat,$buildYear,$buildAge,'$completionDate','$ageGrade',$ageScore,'$floodGrade',$floodScore,$landslideDist,'$landslideGrade',$landslideScore,$fireScore,'$prevFire',$landUseScore,$totalScore,'$totalGrade','$riskCd','$analDate');"
    $null = $sb.AppendLine($line)
}

$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutputSqlPath, $sb.ToString(), $enc)

Write-Host ("General sample rows  : {0}" -f $generalSample.Count)
Write-Host ("Self sample rows     : {0}" -f $selfSample.Count)
Write-Host ("Facility addr set    : {0}" -f $addrSet.Count)
Write-Host ("Matched building rows: {0}" -f $matched.Count)
Write-Host ("Output building rows : {0}" -f $selected.Count)
Write-Host ("Output SQL           : {0}" -f $OutputSqlPath)
