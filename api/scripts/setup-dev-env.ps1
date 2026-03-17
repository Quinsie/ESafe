$ErrorActionPreference = "Stop"
$devDir = "$env:USERPROFILE\dev"

$downloads = @(
    @{
        Name   = "Apache Tomcat 8.5.100"
        Url    = "https://archive.apache.org/dist/tomcat/tomcat-8/v8.5.100/bin/apache-tomcat-8.5.100-windows-x64.zip"
        Zip    = "$devDir\tomcat.zip"
        Expect = "$devDir\apache-tomcat-8.5.100"
    },
    @{
        Name   = "Eclipse Temurin JDK 11.0.25+9"
        Url    = "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.25%2B9/OpenJDK11U-jdk_x64_windows_hotspot_11.0.25_9.zip"
        Zip    = "$devDir\jdk.zip"
        Expect = "$devDir\jdk-11.0.25+9"
    },
    @{
        Name   = "Apache Maven 3.9.9"
        Url    = "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.9/apache-maven-3.9.9-bin.zip"
        Zip    = "$devDir\maven.zip"
        Expect = "$devDir\apache-maven-3.9.9"
    }
)

if (-not (Test-Path $devDir)) {
    New-Item -ItemType Directory -Path $devDir | Out-Null
    Write-Host "폴더 생성: $devDir"
}

foreach ($item in $downloads) {
    Write-Host ""
    Write-Host "=== $($item.Name) ==="

    if (Test-Path $item.Expect) {
        Write-Host "이미 설치됨, 건너뜀: $($item.Expect)"
        continue
    }

    Write-Host "다운로드 중..."
    Invoke-WebRequest -Uri $item.Url -OutFile $item.Zip -UseBasicParsing

    Write-Host "압축 해제 중..."
    Expand-Archive -Path $item.Zip -DestinationPath $devDir -Force

    Remove-Item $item.Zip -Force

    if (Test-Path $item.Expect) {
        Write-Host "완료: $($item.Expect)"
    } else {
        Write-Host "[경고] 예상 경로 없음: $($item.Expect)"
        Write-Host "실제 압축 해제된 항목:"
        Get-ChildItem $devDir | Select-Object Name
    }
}

Write-Host ""
Write-Host "=== 설치 완료 ==="
Write-Host "Tomcat : $devDir\apache-tomcat-8.5.100"
Write-Host "JDK    : $devDir\jdk-11.0.25+9"
Write-Host "Maven  : $devDir\apache-maven-3.9.9"
Write-Host ""
Write-Host "이제 아래 명령으로 Tomcat 기동 가능:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\start-tomcat-h2.ps1"
