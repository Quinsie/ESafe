param(
    [string]$ApiBaseUrl = "http://localhost:18080",
    [string]$Username = "localadmin",
    [string]$Password = "LocalAdmin123",
    [int]$PageSize = 1000,
    [string]$GeneralCsvPath = "C:\Users\user\Downloads\kescoaitest\설비데이터\일반용 샘플 데이터2.csv",
    [string]$SelfCsvPath = "C:\Users\user\Downloads\kescoaitest\설비데이터\자가용 샘플 데이터.csv",
    [string]$OutputSqlPath = "C:\Users\user\Downloads\kescoaitest\api\src\main\resources\egovframework\spring\data-h2-facility-history.sql",
    [int]$GeneralSampleRows = 10000,
    [int]$SelfSampleRows = 10000,
    [int]$GeneralTargetInserts = 10000,
    [int]$SelfTargetInserts = 10000
)

$ErrorActionPreference = "Stop"

function New-Kr([int[]]$codes) {
    return (-join ($codes | ForEach-Object { [char]$_ }))
}

$KR_BUJEOK = New-Kr @(0xBD80, 0xC801, 0xD569) # 부적합
$KR_BULHAP = New-Kr @(0xBD88, 0xD569, 0xACA9) # 불합격
$KR_BUJAE = New-Kr @(0xBD80, 0xC7AC, 0xC885, 0xACB0) # 부재종결
$KR_YE = New-Kr @(0xC608) # 예
$KR_ANIO = New-Kr @(0xC544, 0xB2C8, 0xC624) # 아니오

function Normalize-Text([object]$v) {
    if ($null -eq $v) { return "" }
    $s = [string]$v
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    $s = $s.Trim()
    $s = $s -replace ",", " "
    $s = $s -replace "\s+", " "
    return $s
}

function Escape-Sql([string]$s) {
    return $s.Replace("'", "''")
}

function Sql-StrOrNull([string]$s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return "NULL" }
    return "'" + (Escape-Sql $s) + "'"
}

function Normalize-CustNo([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    return ($s -replace "\.0$", "")
}

function Get-Field([object]$row, [string[]]$names) {
    foreach ($name in $names) {
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $prop = $row.PSObject.Properties[$name]
        if ($null -ne $prop) {
            return $prop.Value
        }
    }
    return $null
}

function Normalize-GeneralResult([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "미입력" }
    return $s
}

function Normalize-SelfResult([object]$v) {
    $s = Normalize-Text $v
    if ($s.Contains($KR_BULHAP) -or $s.Contains($KR_BUJEOK)) { return $KR_BULHAP }
    return "합격"
}

function Normalize-OralYn([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return "" }
    if ($s -match "^(Y|y)$" -or $s.Contains($KR_YE)) { return "Y" }
    if ($s -match "^(N|n)$" -or $s.Contains($KR_ANIO)) { return "N" }
    return ""
}

function Normalize-Date([object]$v, [string]$fallbackDate) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return $fallbackDate }

    if ($s -match "^\d{8}$") {
        return "{0}-{1}-{2}" -f $s.Substring(0, 4), $s.Substring(4, 2), $s.Substring(6, 2)
    }
    if ($s -match "^\d{4}-\d{2}-\d{2}$") {
        return $s
    }

    $dt = [datetime]::MinValue
    if ([datetime]::TryParse($s, [ref]$dt)) {
        return $dt.ToString("yyyy-MM-dd")
    }

    $n = 0.0
    if ([double]::TryParse($s, [ref]$n)) {
        if ($n -ge 1 -and $n -lt 80000) {
            $excelBase = [datetime]::Parse("1899-12-30")
            return $excelBase.AddDays($n).ToString("yyyy-MM-dd")
        }
    }

    return $fallbackDate
}

function To-IntOrNull([object]$v) {
    $s = Normalize-Text $v
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    try {
        return [int][double]$s
    }
    catch {
        return $null
    }
}

function Normalize-StatusKey([string]$v) {
    $s = Normalize-Text $v
    return ($s -replace "\s+", "")
}

function Select-PrioritizedRows([object[]]$Rows, [int]$TargetRows, [scriptblock]$IsPriority) {
    $priority = New-Object System.Collections.Generic.List[object]
    $others = New-Object System.Collections.Generic.List[object]

    foreach ($r in $Rows) {
        $isPri = $false
        try {
            $isPri = [bool](& $IsPriority $r)
        }
        catch {
            $isPri = $false
        }
        if ($isPri) { $priority.Add($r) } else { $others.Add($r) }
    }

    $ordered = New-Object System.Collections.Generic.List[object]
    $ordered.AddRange($priority)
    $ordered.AddRange($others)

    if ($TargetRows -le 0 -or $ordered.Count -le $TargetRows) {
        return $ordered.ToArray()
    }
    return @($ordered | Select-Object -First $TargetRows)
}

function Fill-ToTarget(
    [System.Text.StringBuilder]$sb,
    [System.Collections.Generic.List[string]]$generatedLines,
    [int]$currentCount,
    [int]$targetCount
) {
    if ($currentCount -ge $targetCount) { return $currentCount }
    if ($generatedLines.Count -eq 0) { return $currentCount }

    $idx = 0
    while ($currentCount -lt $targetCount) {
        $null = $sb.AppendLine($generatedLines[$idx % $generatedLines.Count])
        $currentCount += 1
        $idx += 1
    }
    return $currentCount
}

if (-not (Test-Path $GeneralCsvPath)) { throw "General CSV not found: $GeneralCsvPath" }
if (-not (Test-Path $SelfCsvPath)) { throw "Self CSV not found: $SelfCsvPath" }

$cookieFile = Join-Path $env:TEMP ("risk-cookie-" + [guid]::NewGuid().ToString("N") + ".txt")
$today = (Get-Date).ToString("yyyy-MM-dd")

try {
    $loginHtml = & curl.exe --max-time 30 -c $cookieFile -s ($ApiBaseUrl + "/login.do")
    $csrfMatch = [regex]::Match($loginHtml, 'name="_csrf" value="([^"]+)"')
    if (-not $csrfMatch.Success) {
        throw "Failed to parse CSRF token from login page"
    }
    $csrf = $csrfMatch.Groups[1].Value

    & curl.exe --max-time 30 -b $cookieFile -c $cookieFile -s -o NUL -X POST ($ApiBaseUrl + "/perform_login.do") --data ("username={0}&password={1}&_csrf={2}" -f $Username, $Password, $csrf)

    $addrToSeq = @{}
    $totalCount = 0
    $page = 1

    while ($true) {
        $url = "{0}/selectCombinedList.do?pageIndex={1}&pageSize={2}" -f $ApiBaseUrl, $page, $PageSize
        $json = & curl.exe --max-time 60 -b $cookieFile -s $url
        $obj = $json | ConvertFrom-Json
        if ($page -eq 1) { $totalCount = [int]$obj.totalCount }

        foreach ($row in @($obj.data)) {
            $addr = Normalize-Text $row.addr
            if ([string]::IsNullOrWhiteSpace($addr)) { continue }
            if (-not $addrToSeq.ContainsKey($addr)) {
                $addrToSeq[$addr] = New-Object System.Collections.Generic.List[int]
            }
            $addrToSeq[$addr].Add([int]$row.bldgSeq)
        }

        if (($page * $PageSize) -ge $totalCount) { break }
        $page += 1
    }

    $generalRowsAll = Import-Csv -Path $GeneralCsvPath -Encoding UTF8
    $selfRowsAll = Import-Csv -Path $SelfCsvPath -Encoding UTF8

    $generalRows = Select-PrioritizedRows -Rows $generalRowsAll -TargetRows $GeneralSampleRows -IsPriority {
        param($row)
        $status = Normalize-StatusKey (Get-Field $row @('결과'))
        return ($status.Contains($KR_BUJEOK) -or $status.Contains($KR_BUJAE))
    }

    $selfRows = Select-PrioritizedRows -Rows $selfRowsAll -TargetRows $SelfSampleRows -IsPriority {
        param($row)
        $status = Normalize-StatusKey (Get-Field $row @('결과'))
        return $status.Contains($KR_BULHAP)
    }

    $sb = New-Object System.Text.StringBuilder
    $null = $sb.AppendLine("-- Auto-generated from facility CSV")
    $null = $sb.AppendLine("-- Generated at: " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
    $null = $sb.AppendLine(("-- General sample rows: {0}, Self sample rows: {1}" -f $generalRows.Count, $selfRows.Count))
    $null = $sb.AppendLine("DELETE FROM TB_FACILITY_GENERAL_HIST;")
    $null = $sb.AppendLine("DELETE FROM TB_FACILITY_SELF_HIST;")
    $null = $sb.AppendLine("")

    $generalInsertCount = 0
    $selfInsertCount = 0
    $generalSeenAddr = New-Object System.Collections.Generic.HashSet[string]
    $selfSeenAddr = New-Object System.Collections.Generic.HashSet[string]
    $generalDedup = New-Object System.Collections.Generic.HashSet[string]
    $selfDedup = New-Object System.Collections.Generic.HashSet[string]
    $generalGeneratedLines = New-Object System.Collections.Generic.List[string]
    $selfGeneratedLines = New-Object System.Collections.Generic.List[string]

    foreach ($r in $generalRows) {
        if ($generalInsertCount -ge $GeneralTargetInserts) { break }

        $branchNm = Normalize-Text (Get-Field $r @('사업소'))
        $addr = Normalize-Text (Get-Field $r @('주소'))
        $custNo = Normalize-CustNo (Get-Field $r @('한전고객번호', '고객번호'))
        $result = Normalize-GeneralResult (Get-Field $r @('결과'))
        $oralYn = Normalize-OralYn (Get-Field $r @('구두통보'))
        $checkDt = Normalize-Date (Get-Field $r @('점검일자', '점검일')) $today
        $failDetail = Normalize-Text (Get-Field $r @('부적합 내역', '부적합내역'))
        $lineNo = Normalize-Text (Get-Field $r @('선식번호'))
        $capacity = Normalize-Text (Get-Field $r @('용량'))
        $checkCycle = Normalize-Text (Get-Field $r @('주기'))
        $contractType = Normalize-Text (Get-Field $r @('계약종별'))
        $rawJson = ($r | ConvertTo-Json -Compress -Depth 4)

        if ([string]::IsNullOrWhiteSpace($addr)) { continue }
        if (-not $addrToSeq.ContainsKey($addr)) { continue }

        $null = $generalSeenAddr.Add($addr)
        foreach ($seq in $addrToSeq[$addr]) {
            if ($generalInsertCount -ge $GeneralTargetInserts) { break }
            $key = "{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}" -f $seq, $custNo, $result, $checkDt, $addr, $lineNo, $capacity, $checkCycle, $contractType
            if (-not $generalDedup.Add($key)) { continue }

            $line = "INSERT INTO TB_FACILITY_GENERAL_HIST " +
                    "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, CHECK_RESULT, ORAL_NOTICE_YN, NONCONFORMITY_DETAIL, LINE_NO, CAPACITY, CHECK_CYCLE, CONTRACT_TYPE, CHECK_DT, RAW_JSON) VALUES " +
                    "($seq, $(Sql-StrOrNull $branchNm), $(Sql-StrOrNull $addr), $(Sql-StrOrNull $custNo), $(Sql-StrOrNull $result), $(Sql-StrOrNull $oralYn), $(Sql-StrOrNull $failDetail), $(Sql-StrOrNull $lineNo), $(Sql-StrOrNull $capacity), $(Sql-StrOrNull $checkCycle), $(Sql-StrOrNull $contractType), DATE '$checkDt', $(Sql-StrOrNull $rawJson));"
            $null = $sb.AppendLine($line)
            $null = $generalGeneratedLines.Add($line)
            $generalInsertCount += 1
        }
    }

    foreach ($r in $selfRows) {
        if ($selfInsertCount -ge $SelfTargetInserts) { break }

        $branchNm = Normalize-Text (Get-Field $r @('사업소'))
        $custNo = Normalize-CustNo (Get-Field $r @('고객번호', '한전고객번호'))
        $addr = Normalize-Text (Get-Field $r @('지번주소', '주소', '도로명주소'))
        $checkDt = Normalize-Date (Get-Field $r @('검사일', '점검일')) $today
        $result = Normalize-SelfResult (Get-Field $r @('결과'))
        $defectCnt = To-IntOrNull (Get-Field $r @('지적건수'))
        $failDetail = Normalize-Text (Get-Field $r @('불합격 내역', '부적합 내역', '부적합내역'))
        $motorType = Normalize-Text (Get-Field $r @('원동기종류'))
        $rawJson = ($r | ConvertTo-Json -Compress -Depth 4)

        if ([string]::IsNullOrWhiteSpace($addr)) { continue }
        if (-not $addrToSeq.ContainsKey($addr)) { continue }

        $null = $selfSeenAddr.Add($addr)
        foreach ($seq in $addrToSeq[$addr]) {
            if ($selfInsertCount -ge $SelfTargetInserts) { break }
            $defectCntSql = if ($null -eq $defectCnt) { "NULL" } else { [string]$defectCnt }
            $key = "{0}|{1}|{2}|{3}|{4}|{5}|{6}" -f $seq, $custNo, $result, $checkDt, $addr, $defectCntSql, $motorType
            if (-not $selfDedup.Add($key)) { continue }

            $line = "INSERT INTO TB_FACILITY_SELF_HIST " +
                    "(BLDG_SEQ, BRANCH_NM, ADDR, KEPCO_CUST_NO, INSPECTION_RESULT, FAIL_DETAIL, DEFECT_CNT, MOTOR_TYPE, CHECK_DT, RAW_JSON) VALUES " +
                    "($seq, $(Sql-StrOrNull $branchNm), $(Sql-StrOrNull $addr), $(Sql-StrOrNull $custNo), $(Sql-StrOrNull $result), $(Sql-StrOrNull $failDetail), $defectCntSql, $(Sql-StrOrNull $motorType), DATE '$checkDt', $(Sql-StrOrNull $rawJson));"
            $null = $sb.AppendLine($line)
            $null = $selfGeneratedLines.Add($line)
            $selfInsertCount += 1
        }
    }

    $generalInsertCount = Fill-ToTarget -sb $sb -generatedLines $generalGeneratedLines -currentCount $generalInsertCount -targetCount $GeneralTargetInserts
    $selfInsertCount = Fill-ToTarget -sb $sb -generatedLines $selfGeneratedLines -currentCount $selfInsertCount -targetCount $SelfTargetInserts

    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($OutputSqlPath, $sb.ToString(), $enc)

    Write-Host ("Address map loaded: {0} unique addresses (from {1} buildings)" -f $addrToSeq.Count, $totalCount)
    Write-Host ("General inserts: {0}/{1} (matched addresses: {2})" -f $generalInsertCount, $GeneralTargetInserts, $generalSeenAddr.Count)
    Write-Host ("Self inserts   : {0}/{1} (matched addresses: {2})" -f $selfInsertCount, $SelfTargetInserts, $selfSeenAddr.Count)
    if ($generalInsertCount -lt $GeneralTargetInserts) {
        Write-Warning ("General inserts did not reach target {0}." -f $GeneralTargetInserts)
    }
    if ($selfInsertCount -lt $SelfTargetInserts) {
        Write-Warning ("Self inserts did not reach target {0}." -f $SelfTargetInserts)
    }
    Write-Host ("Output SQL     : {0}" -f $OutputSqlPath)
}
finally {
    Remove-Item -Path $cookieFile -ErrorAction SilentlyContinue
}
