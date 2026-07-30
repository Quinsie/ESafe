$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot "storage\runtime"
$logPath = Join-Path $runtimeRoot "fire-impact-map-apply.log"
$origin = "http://127.0.0.1:8080"
$dockerCommand = Get-Command "docker" -ErrorAction SilentlyContinue
if ($null -ne $dockerCommand) {
    $docker = $dockerCommand.Source
} else {
    $dockerCandidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Docker\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe")
    )
    $docker = $dockerCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $docker) {
        throw "Docker CLI was not found. Install or start Docker Desktop."
    }
}

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & $docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed (exit $LASTEXITCODE): docker $($Arguments -join ' ')"
    }
}

function Read-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    $line = Get-Content -LiteralPath (Join-Path $projectRoot ".env") -Encoding UTF8 |
        Where-Object { $_ -match "^$([regex]::Escape($Name))=" } |
        Select-Object -First 1
    if (-not $line) {
        throw "Required environment variable is missing: $Name"
    }
    return ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
Start-Transcript -LiteralPath $logPath -Force
try {
    Set-Location -LiteralPath $projectRoot

    Write-Host "[1/7] Checking Docker Desktop"
    Invoke-Docker -Arguments @("info", "--format", "{{.ServerVersion}}")

    Write-Host "[2/7] Running backend checks inside the Docker test image"
    Invoke-Docker -Arguments @(
        "build", "--file", "backend/Dockerfile", "--target", "test",
        "--tag", "esafe-backend-test:scenario1-fix", "."
    )

    Write-Host "[3/7] Building shared backend and gateway images"
    Invoke-Docker -Arguments @(
        "compose", "build",
        "api-live", "api-demo",
        "worker-live", "worker-demo",
        "sld-worker-live", "sld-worker-demo",
        "gateway"
    )

    Write-Host "[4/7] Applying database migrations inside Compose"
    Invoke-Docker -Arguments @("compose", "up", "-d", "db-live", "db-demo")
    Invoke-Docker -Arguments @("compose", "run", "--rm", "--no-deps", "migrate-live")
    Invoke-Docker -Arguments @("compose", "run", "--rm", "--no-deps", "migrate-demo")

    Write-Host "[5/7] Recreating APIs, signal workers, SLD workers, and gateway"
    Invoke-Docker -Arguments @(
        "compose", "up", "-d", "--no-deps", "--force-recreate",
        "api-live", "api-demo",
        "worker-live", "worker-demo",
        "sld-worker-live", "sld-worker-demo",
        "gateway"
    )

    Write-Host "[6/7] Waiting for the DEMO API and SLD worker"
    $ready = $false
    $sldReady = $false
    for ($attempt = 0; $attempt -lt 90; $attempt += 1) {
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:8080/demo/api/v1/health/live" `
                -UseBasicParsing `
                -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                $ready = $true
            }
        } catch {
            $ready = $false
        }
        try {
            $sldContainer = & $docker compose ps -q "sld-worker-demo"
            if ($LASTEXITCODE -eq 0 -and $sldContainer) {
                $sldStatus = & $docker inspect `
                    --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
                    $sldContainer
                $sldReady = $LASTEXITCODE -eq 0 -and $sldStatus.Trim() -eq "healthy"
            }
        } catch {
            $sldReady = $false
        }
        if ($ready -and $sldReady) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready -or -not $sldReady) {
        Invoke-Docker -Arguments @(
            "compose", "logs", "--tail=120",
            "api-demo", "worker-demo", "sld-worker-demo", "gateway"
        )
        throw "DEMO API or SLD worker did not become ready"
    }
    Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "sld-worker-demo",
        "python", "-c",
        "from app.sld_analysis import sld_ocr_request_hash; " +
        "assert sld_ocr_request_hash('ocr', 'a' * 64, 'analysis:v1') " +
        "!= sld_ocr_request_hash('ocr', 'a' * 64, 'analysis:v2')"
    )

    Write-Host "[7/7] Replaying DS-01 step 1 through the deployed API"
    $webSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $loginBody = @{
        userId = Read-EnvValue -Name "ESAFE_PUBLIC_USER_ID"
        password = Read-EnvValue -Name "ESAFE_PUBLIC_USER_PASSWORD"
    } | ConvertTo-Json
    Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/auth/login" `
        -Method Post `
        -ContentType "application/json" `
        -Headers @{ Origin = $origin } `
        -Body $loginBody `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 15 | Out-Null

    $csrfCookie = $webSession.Cookies.GetCookies("$origin/demo/") |
        Where-Object { $_.Name -eq "esafe_demo_csrf" } |
        Select-Object -First 1
    if (-not $csrfCookie) {
        throw "DEMO CSRF cookie was not issued"
    }
    $writeHeaders = @{
        Origin = $origin
        "X-CSRF-Token" = $csrfCookie.Value
    }
    $catalog = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/demo/scenarios" `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 15
    $scenario = $catalog.data.items |
        Where-Object { $_.code -eq "DS-01" } |
        Select-Object -First 1
    $active = $catalog.data.items |
        Where-Object { $_.playback.status -in @("READY", "RUNNING", "PAUSED") } |
        Select-Object -First 1
    if (-not $scenario) {
        throw "DS-01 was not found"
    }
    $scenarioVersion = $null
    if ($null -ne $scenario.playback) {
        $scenarioVersion = $scenario.playback.version
    }
    $activeVersion = $null
    if ($null -ne $active -and $null -ne $active.playback) {
        $activeVersion = $active.playback.version
    }

    $writeHeaders["Idempotency-Key"] = "scenario1-deploy-reset-$([guid]::NewGuid())"
    $reset = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/demo/scenarios/$($scenario.scenarioId)/reset" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $writeHeaders `
        -Body (@{
            expectedVersion = $scenarioVersion
            activeExpectedVersion = $activeVersion
            confirmed = $true
        } | ConvertTo-Json) `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 120

    $writeHeaders["Idempotency-Key"] = "scenario1-deploy-start-$([guid]::NewGuid())"
    $started = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/demo/scenarios/$($scenario.scenarioId)/start" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $writeHeaders `
        -Body (@{
            expectedVersion = $reset.data.playback.version
        } | ConvertTo-Json) `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 30

    $writeHeaders["Idempotency-Key"] = "scenario1-deploy-next-$([guid]::NewGuid())"
    $advanced = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/demo/scenarios/$($scenario.scenarioId)/next" `
        -Method Post `
        -ContentType "application/json" `
        -Headers $writeHeaders `
        -Body (@{
            expectedVersion = $started.data.playback.version
        } | ConvertTo-Json) `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 120
    if (
        $advanced.data.playback.currentStep -ne 1 -or
        $advanced.data.execution.status -ne "SUCCESS"
    ) {
        throw "DS-01 replay verification did not complete step 1"
    }

    Write-Host "Clearing existing SLD extraction attempts and completed history for DS-01"
    Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "api-demo",
        "python", "-m", "app.cli", "clear-demo-sld-history"
    )

    Invoke-Docker -Arguments @(
        "compose", "ps",
        "api-demo", "worker-demo", "sld-worker-demo", "gateway"
    )
    Write-Host ""
    Write-Host "Scenario 1 fix applied and verified inside Docker."
    Write-Host "DS-01 is running at step 1."
    Write-Host "The incident building is red; all buildings within 100m are orange."
    Start-Process "http://127.0.0.1:8080/demo/demo-scenarios"
} catch {
    Write-Error $_
    Write-Host ""
    Write-Host "Apply failed. Keep this window open and notify Codex."
    Write-Host $logPath
    exit 1
} finally {
    Stop-Transcript
}
