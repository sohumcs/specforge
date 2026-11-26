# SPECForge on Windows PowerShell (no make needed).
#   .\scripts\dev.ps1            build + start everything, wait until ready
#   .\scripts\dev.ps1 down | clean | logs | ps | seed | e2e | e2e-ci
param([string]$Target = "dev")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$WebUrl = if ($env:WEB_URL) { $env:WEB_URL } else { "http://localhost:8080" }
$env:GIT_SHA = (git rev-parse --short HEAD 2>$null)
if (-not $env:GIT_SHA) { $env:GIT_SHA = "dev" }

function Wait-Ready {
    Write-Host "waiting for $WebUrl/ready ..."
    for ($i = 0; $i -lt 90; $i++) {
        try {
            if ((Invoke-WebRequest "$WebUrl/ready" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    }
    docker compose ps
    throw "stack did not become ready"
}

switch ($Target) {
    "dev" {
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }
        Wait-Ready
        Write-Host "SPECForge is up: $WebUrl  (API docs: $WebUrl/docs)"
    }
    "down" { docker compose down }
    "clean" { docker compose down -v }
    "logs" { docker compose logs -f --tail=100 }
    "ps" { docker compose ps }
    "seed" { docker compose run --rm seed }
    "e2e" { Push-Location frontend; $env:E2E_BASE_URL = $WebUrl; npx playwright test; Pop-Location }
    "e2e-ci" {
        $env:LLM_PROVIDERS = '["demo"]'
        $env:GENERATE_LIMIT_PER_IP_HOUR = "1000"; $env:GENERATE_LIMIT_PER_USER_HOUR = "1000"
        $env:DEMO_LOGIN_LIMIT_PER_IP_HOUR = "1000"
        docker compose up -d --build; Wait-Ready
        Push-Location frontend; $env:E2E_BASE_URL = $WebUrl; npx playwright test; Pop-Location
    }
    default { throw "unknown target '$Target' (dev, down, clean, logs, ps, seed, e2e, e2e-ci)" }
}
