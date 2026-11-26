# SPECForge on Windows PowerShell (no make needed).
#   .\scripts\dev.ps1            build + start everything, wait until ready
#   .\scripts\dev.ps1 down | clean | logs | ps | seed | e2e | e2e-ci
param([string]$Target = "dev")
# Not "Stop": Windows PowerShell 5.1 turns native stderr (docker compose's normal
# progress output) into terminating errors when output is redirected. Native
# commands are checked via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Checked([scriptblock]$Cmd, [string]$What) {
    & $Cmd
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}
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

function Invoke-E2E {
    Push-Location frontend
    try {
        if (-not (Test-Path node_modules)) { Invoke-Checked { npm ci --no-audit --no-fund } "npm ci" }
        Invoke-Checked { npx playwright install chromium } "playwright install"
        $env:E2E_BASE_URL = $WebUrl
        Invoke-Checked { npx playwright test } "playwright"
    } finally { Pop-Location }
}

switch ($Target) {
    "dev" {
        Invoke-Checked { docker compose up -d --build } "docker compose up"
        Wait-Ready
        Write-Host "SPECForge is up: $WebUrl  (API docs: $WebUrl/docs)"
    }
    "down" { Invoke-Checked { docker compose down } "docker compose down" }
    "clean" { Invoke-Checked { docker compose down -v } "docker compose down -v" }
    "logs" { docker compose logs -f --tail=100 }
    "ps" { docker compose ps }
    "seed" { Invoke-Checked { docker compose run --rm seed } "seed" }
    "e2e" { Invoke-E2E }
    "e2e-ci" {
        # Deterministic: offline LLM, generous limits (same as `make e2e-ci`).
        $env:LLM_PROVIDERS = '["demo"]'
        $env:GENERATE_LIMIT_PER_IP_HOUR = "1000"; $env:GENERATE_LIMIT_PER_USER_HOUR = "1000"
        $env:DEMO_LOGIN_LIMIT_PER_IP_HOUR = "1000"
        Invoke-Checked { docker compose up -d --build } "docker compose up"
        Wait-Ready
        Invoke-E2E
    }
    default { throw "unknown target '$Target' (dev, down, clean, logs, ps, seed, e2e, e2e-ci)" }
}
