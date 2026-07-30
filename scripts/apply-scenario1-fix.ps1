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

function Test-ComposeServiceHealthy {
    param([Parameter(Mandatory = $true)][string]$Service)

    try {
        $container = & $docker compose ps -q $Service
        if ($LASTEXITCODE -ne 0 -or -not $container) {
            return $false
        }
        $status = & $docker inspect `
            --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
            $container
        return $LASTEXITCODE -eq 0 -and $status.Trim() -eq "healthy"
    } catch {
        return $false
    }
}

function Assert-DemoDocumentArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Origin,
        [Parameter(Mandatory = $true)]
        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession,
        [Parameter(Mandatory = $true)][string]$CsrfToken,
        [Parameter(Mandatory = $true)][object[]]$Documents,
        [int]$TimeoutSeconds = 240
    )

    $retryAttempted = @{}
    $artifactsReady = $false
    for ($attempt = 0; $attempt -lt $TimeoutSeconds; $attempt += 1) {
        $pendingCount = 0
        foreach ($document in $Documents) {
            $detail = Invoke-RestMethod `
                -Uri "$Origin/demo/api/v1/documents/$($document.DocumentDraftId)" `
                -WebSession $WebSession `
                -UseBasicParsing `
                -TimeoutSec 15
            $reviewArtifacts = @($detail.data.artifacts) |
                Where-Object { $_.stage -eq "REVIEW" }
            foreach ($artifact in $reviewArtifacts) {
                if ($artifact.status -in @("QUEUED", "RUNNING")) {
                    $pendingCount += 1
                    continue
                }
                if ($artifact.status -eq "FAILED") {
                    if ($retryAttempted.ContainsKey($artifact.documentArtifactId)) {
                        throw (
                            "Document artifact failed after retry: {0}:{1}" -f
                            $artifact.documentArtifactId,
                            $artifact.errorMessage
                        )
                    }
                    $retryHeaders = @{
                        Origin = $Origin
                        "X-CSRF-Token" = $CsrfToken
                        "Idempotency-Key" = "document-contract-retry-$([guid]::NewGuid())"
                    }
                    Invoke-RestMethod `
                        -Uri "$Origin/demo/api/v1/document-artifacts/$($artifact.documentArtifactId)/retry" `
                        -Method Post `
                        -Headers $retryHeaders `
                        -WebSession $WebSession `
                        -UseBasicParsing `
                        -TimeoutSec 15 | Out-Null
                    $retryAttempted[$artifact.documentArtifactId] = $true
                    $pendingCount += 1
                }
            }
        }
        if ($pendingCount -eq 0) {
            $artifactsReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }
    if (-not $artifactsReady) {
        throw "Document artifacts did not finish within $TimeoutSeconds seconds"
    }

    foreach ($document in $Documents) {
        $detail = Invoke-RestMethod `
            -Uri "$Origin/demo/api/v1/documents/$($document.DocumentDraftId)" `
            -WebSession $WebSession `
            -UseBasicParsing `
            -TimeoutSec 15
        $reviewArtifacts = @($detail.data.artifacts) |
            Where-Object { $_.stage -eq "REVIEW" }
        foreach ($format in @("HWPX", "PDF")) {
            $artifact = $reviewArtifacts |
                Where-Object {
                    $_.format -eq $format -and $_.status -eq "SUCCEEDED"
                } |
                Select-Object -First 1
            if (-not $artifact) {
                throw (
                    "{0} did not produce a successful REVIEW {1}" -f
                    $document.Variant,
                    $format
                )
            }
            $download = Invoke-WebRequest `
                -Uri "$Origin/demo/api/v1/document-artifacts/$($artifact.documentArtifactId)/download" `
                -WebSession $WebSession `
                -UseBasicParsing `
                -TimeoutSec 60
            if ($download.StatusCode -ne 200 -or $download.RawContentLength -le 0) {
                throw (
                    "{0} {1} download verification failed" -f
                    $document.Variant,
                    $format
                )
            }
        }
        Write-Host "$($document.Variant) HWPX/PDF verified"
    }
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
Start-Transcript -LiteralPath $logPath -Force
try {
    Set-Location -LiteralPath $projectRoot

    Write-Host "[1/8] Checking Docker Desktop"
    Invoke-Docker -Arguments @("info", "--format", "{{.ServerVersion}}")

    Write-Host "[2/8] Running backend checks inside the Docker test image"
    Invoke-Docker -Arguments @(
        "build", "--file", "backend/Dockerfile", "--target", "test",
        "--tag", "esafe-backend-test:scenario1-fix", "."
    )

    Write-Host "[3/8] Building backend, document runtime, and gateway images"
    Invoke-Docker -Arguments @(
        "compose", "build",
        "api-live", "api-demo",
        "worker-live", "worker-demo",
        "sld-worker-live", "sld-worker-demo",
        "document-worker-live", "document-worker-demo",
        "gateway"
    )

    Write-Host "[4/8] Applying database migrations inside Compose"
    Invoke-Docker -Arguments @("compose", "up", "-d", "db-live", "db-demo")
    Invoke-Docker -Arguments @("compose", "run", "--rm", "--no-deps", "migrate-live")
    Invoke-Docker -Arguments @("compose", "run", "--rm", "--no-deps", "migrate-demo")

    Write-Host "[5/8] Recreating APIs, workers, and gateway"
    Invoke-Docker -Arguments @(
        "compose", "up", "-d", "--no-deps", "--force-recreate",
        "api-live", "api-demo",
        "worker-live", "worker-demo",
        "sld-worker-live", "sld-worker-demo",
        "document-worker-live", "document-worker-demo",
        "gateway"
    )

    Write-Host "[6/8] Waiting for the DEMO API, SLD worker, and document workers"
    $ready = $false
    $sldReady = $false
    $documentDemoReady = $false
    $documentLiveReady = $false
    for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
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
        $sldReady = Test-ComposeServiceHealthy -Service "sld-worker-demo"
        $documentDemoReady = Test-ComposeServiceHealthy -Service "document-worker-demo"
        $documentLiveReady = Test-ComposeServiceHealthy -Service "document-worker-live"
        if ($ready -and $sldReady -and $documentDemoReady -and $documentLiveReady) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if (
        -not $ready -or
        -not $sldReady -or
        -not $documentDemoReady -or
        -not $documentLiveReady
    ) {
        Invoke-Docker -Arguments @(
            "compose", "logs", "--tail=120",
            "api-demo", "worker-demo", "sld-worker-demo",
            "document-worker-demo", "document-worker-live", "gateway"
        )
        throw "DEMO API, SLD worker, or document worker did not become ready"
    }
    Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "sld-worker-demo",
        "python", "-c",
        "from app.sld_analysis import sld_ocr_request_hash; " +
        "assert sld_ocr_request_hash('ocr', 'a' * 64, 'analysis:v1') " +
        "!= sld_ocr_request_hash('ocr', 'a' * 64, 'analysis:v2')"
    )

    Write-Host "[7/8] Recovering and verifying all DEMO document paths"
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
    $documentLibrary = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/documents?pageSize=100" `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 15
    $retriedArtifacts = [System.Collections.Generic.List[object]]::new()
    foreach ($documentItem in @($documentLibrary.data.items)) {
        if ($null -eq $documentItem) {
            continue
        }
        $documentDetail = Invoke-RestMethod `
            -Uri "$origin/demo/api/v1/documents/$($documentItem.documentDraftId)" `
            -WebSession $webSession `
            -UseBasicParsing `
            -TimeoutSec 15
        foreach ($artifact in @($documentDetail.data.artifacts)) {
            if ($null -eq $artifact) {
                continue
            }
            if ($artifact.status -eq "FAILED") {
                Write-Host (
                    "Retrying failed artifact {0} ({1}: {2})" -f
                    $artifact.documentArtifactId,
                    $artifact.format,
                    $artifact.errorMessage
                )
                $retryHeaders = @{
                    Origin = $origin
                    "X-CSRF-Token" = $csrfCookie.Value
                    "Idempotency-Key" = "document-worker-refresh-$([guid]::NewGuid())"
                }
                Invoke-RestMethod `
                    -Uri "$origin/demo/api/v1/document-artifacts/$($artifact.documentArtifactId)/retry" `
                    -Method Post `
                    -Headers $retryHeaders `
                    -WebSession $webSession `
                    -UseBasicParsing `
                    -TimeoutSec 15 | Out-Null
                $retriedArtifacts.Add([pscustomobject]@{
                    DocumentDraftId = $documentItem.documentDraftId
                    ArtifactId = $artifact.documentArtifactId
                })
            }
        }
    }
    if ($retriedArtifacts.Count -gt 0) {
        Write-Host "Retried $($retriedArtifacts.Count) document artifact(s)"
        $artifactsReady = $false
        for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
            $pendingCount = 0
            $failedArtifacts = [System.Collections.Generic.List[object]]::new()
            foreach ($retried in $retriedArtifacts) {
                $documentDetail = Invoke-RestMethod `
                    -Uri "$origin/demo/api/v1/documents/$($retried.DocumentDraftId)" `
                    -WebSession $webSession `
                    -UseBasicParsing `
                    -TimeoutSec 15
                $artifact = @($documentDetail.data.artifacts) |
                    Where-Object {
                        $_.documentArtifactId -eq $retried.ArtifactId
                    } |
                    Select-Object -First 1
                if (-not $artifact -or $artifact.status -in @("QUEUED", "RUNNING")) {
                    $pendingCount += 1
                } elseif ($artifact.status -eq "FAILED") {
                    $failedArtifacts.Add($artifact)
                }
            }
            if ($failedArtifacts.Count -gt 0) {
                $failureSummary = $failedArtifacts |
                    ForEach-Object {
                        "$($_.documentArtifactId):$($_.errorMessage)"
                    }
                throw "Document artifact retry failed: $($failureSummary -join ', ')"
            }
            if ($pendingCount -eq 0) {
                $artifactsReady = $true
                break
            }
            Start-Sleep -Seconds 1
        }
        if (-not $artifactsReady) {
            throw "Document artifact retry did not finish within 120 seconds"
        }
        Write-Host "Document artifact recovery completed"
    } else {
        Write-Host "No existing failed document artifacts required retry"
    }

    $buildingRanking = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/risk-rankings?level=BUILDING&page=1&pageSize=1" `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 30
    $regionRanking = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/risk-rankings?level=SIDO&page=1&pageSize=1" `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 30
    $buildingTarget = @($buildingRanking.data.items) |
        Select-Object -First 1
    $regionTarget = @($regionRanking.data.items) |
        Select-Object -First 1
    if (-not $buildingTarget -or -not $regionTarget) {
        throw "Document smoke-test targets were not found"
    }
    $documentContracts = @(
        [pscustomobject]@{
            Variant = "REGION_ANALYSIS"
            TargetId = $regionTarget.entityId
        },
        [pscustomobject]@{
            Variant = "BUILDING_ANALYSIS"
            TargetId = $buildingTarget.entityId
        },
        [pscustomobject]@{
            Variant = "INSPECTION_REQUEST"
            TargetId = $buildingTarget.entityId
        }
    )
    $contractDocuments = [System.Collections.Generic.List[object]]::new()
    foreach ($contract in $documentContracts) {
        $contractHeaders = @{
            Origin = $origin
            "X-CSRF-Token" = $csrfCookie.Value
            "Idempotency-Key" = (
                "document-contract-{0}-20260731-v1" -f
                $contract.Variant.ToLowerInvariant()
            )
        }
        $createdDocument = Invoke-RestMethod `
            -Uri "$origin/demo/api/v1/standalone-documents" `
            -Method Post `
            -ContentType "application/json" `
            -Headers $contractHeaders `
            -Body (@{
                variant = $contract.Variant
                targetId = $contract.TargetId
            } | ConvertTo-Json) `
            -WebSession $webSession `
            -UseBasicParsing `
            -TimeoutSec 60
        if (-not $createdDocument.data.documentDraftId) {
            throw "Document contract did not return a draft: $($contract.Variant)"
        }
        $contractDocuments.Add([pscustomobject]@{
            Variant = $contract.Variant
            DocumentDraftId = $createdDocument.data.documentDraftId
        })
        Write-Host (
            "Created or reused {0}: {1}" -f
            $contract.Variant,
            $createdDocument.data.documentDraftId
        )
    }

    Assert-DemoDocumentArtifacts `
        -Origin $origin `
        -WebSession $webSession `
        -CsrfToken $csrfCookie.Value `
        -Documents $contractDocuments.ToArray()

    Write-Host "[8/8] Replaying DS-01 step 1 through the deployed API"
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

    Write-Host "Verifying all Case-based document variants"
    $caseLibrary = Invoke-RestMethod `
        -Uri "$origin/demo/api/v1/cases?page=1&pageSize=1&sort=updated" `
        -WebSession $webSession `
        -UseBasicParsing `
        -TimeoutSec 30
    $documentCase = @($caseLibrary.data.items) |
        Select-Object -First 1
    if (-not $documentCase) {
        throw "No DEMO Case was available for document verification"
    }
    $caseDocuments = [System.Collections.Generic.List[object]]::new()
    foreach (
        $variant in @(
            "INCIDENT_REPORT",
            "CRISIS_ASSESSMENT",
            "BASIC_NOTICE",
            "BASIC_PLAN"
        )
    ) {
        $caseDocumentHeaders = @{
            Origin = $origin
            "X-CSRF-Token" = $csrfCookie.Value
            "Idempotency-Key" = (
                "document-case-contract-{0}-20260731-v1" -f
                $variant.ToLowerInvariant()
            )
        }
        $createdDocument = Invoke-RestMethod `
            -Uri "$origin/demo/api/v1/cases/$($documentCase.caseId)/documents" `
            -Method Post `
            -ContentType "application/json" `
            -Headers $caseDocumentHeaders `
            -Body (@{ variant = $variant } | ConvertTo-Json) `
            -WebSession $webSession `
            -UseBasicParsing `
            -TimeoutSec 60
        if (-not $createdDocument.data.documentDraftId) {
            throw "Case document contract did not return a draft: $variant"
        }
        $caseDocuments.Add([pscustomobject]@{
            Variant = $variant
            DocumentDraftId = $createdDocument.data.documentDraftId
        })
        Write-Host (
            "Created or reused {0}: {1}" -f
            $variant,
            $createdDocument.data.documentDraftId
        )
    }
    Assert-DemoDocumentArtifacts `
        -Origin $origin `
        -WebSession $webSession `
        -CsrfToken $csrfCookie.Value `
        -Documents $caseDocuments.ToArray()

    Write-Host "Clearing existing SLD extraction attempts and completed history for DS-01"
    Invoke-Docker -Arguments @(
        "compose", "exec", "-T", "api-demo",
        "python", "-m", "app.cli", "clear-demo-sld-history"
    )

    Invoke-Docker -Arguments @(
        "compose", "ps",
        "api-demo", "worker-demo", "sld-worker-demo",
        "document-worker-demo", "document-worker-live", "gateway"
    )
    Write-Host ""
    Write-Host "Scenario 1 fix applied and verified inside Docker."
    Write-Host "All seven document variants produced downloadable HWPX and PDF files."
    Write-Host "DS-01 is running at step 1."
    Write-Host "The incident building is red; all buildings within 100m are orange."
    Start-Process "http://127.0.0.1:8080/demo/demo-scenarios"
    Start-Process "http://127.0.0.1:8080/demo/artifacts"
} catch {
    Write-Error $_
    Write-Host ""
    Write-Host "Apply failed. Keep this window open and notify Codex."
    Write-Host $logPath
    exit 1
} finally {
    Stop-Transcript
}
