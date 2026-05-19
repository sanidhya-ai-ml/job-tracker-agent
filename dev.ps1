# ─────────────────────────────────────────────────────────────────────────────
# dev.ps1  —  Job Tracker Agent · Docker Compose helper for Windows
# Usage:
#   .\dev.ps1 up            → Build & start all services (detached)
#   .\dev.ps1 down          → Stop all services
#   .\dev.ps1 logs          → Tail logs from all services
#   .\dev.ps1 logs fastapi  → Tail logs from a specific service
#   .\dev.ps1 ps            → Show running containers
#   .\dev.ps1 clean         → Stop + remove containers, volumes, images
#   .\dev.ps1 import        → Import n8n workflows via API
#   .\dev.ps1 shell         → Open a shell inside the fastapi container
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$action = if ($args.Count -gt 0) { $args[0] } else { "help" }

function Print-Header {
    Write-Host ""
    Write-Host "  Job Tracker Agent — Docker Dev Helper" -ForegroundColor Cyan
    Write-Host ""
}

function Ensure-Env {
    if (-not (Test-Path ".\.env")) {
        Write-Host "[WARN] .env not found — copying from .env.example" -ForegroundColor Yellow
        Copy-Item ".\.env.example" ".\.env"
        Write-Host "[WARN] Fill in .env with your API keys before continuing!" -ForegroundColor Magenta
    }
}

function Check-Docker {
    try { docker info | Out-Null } catch {
        Write-Host "[ERROR] Docker is not running. Start Docker Desktop first." -ForegroundColor Red
        exit 1
    }
}

Print-Header
Check-Docker

switch ($action) {

    "up" {
        Ensure-Env
        Write-Host "[up] Building images and starting services..." -ForegroundColor Yellow
        docker compose up --build -d
        Write-Host ""
        Write-Host "  Services started:" -ForegroundColor Green
        Write-Host "    FastAPI  → http://localhost:8000/docs" -ForegroundColor White
        Write-Host "    n8n      → http://localhost:5678" -ForegroundColor White
        Write-Host "    Postgres → localhost:5432" -ForegroundColor White
        Write-Host ""
        Write-Host "  Run '.\dev.ps1 logs' to watch output." -ForegroundColor Gray
    }

    "down" {
        Write-Host "[down] Stopping services..." -ForegroundColor Yellow
        docker compose down
        Write-Host "  Done." -ForegroundColor Green
    }

    "logs" {
        $svc = if ($args.Count -gt 1) { $args[1] } else { "" }
        Write-Host "[logs] Streaming logs (Ctrl+C to stop)..." -ForegroundColor Yellow
        if ($svc) {
            docker compose logs -f $svc
        } else {
            docker compose logs -f
        }
    }

    "ps" {
        docker compose ps
    }

    "clean" {
        Write-Host "[clean] Stopping and removing all containers, volumes, images..." -ForegroundColor Red
        $confirm = Read-Host "  This deletes ALL data (Postgres, n8n). Continue? (y/N)"
        if ($confirm -eq "y" -or $confirm -eq "Y") {
            docker compose down -v --remove-orphans
            Write-Host "  Cleaned." -ForegroundColor Green
        } else {
            Write-Host "  Aborted." -ForegroundColor Gray
        }
    }

    "import" {
        Write-Host "[import] Importing n8n workflows..." -ForegroundColor Yellow
        Write-Host "  Waiting for n8n to be healthy..."

        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:5678/healthz" -UseBasicParsing -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
            Start-Sleep -Seconds 3
        }

        if (-not $ready) {
            Write-Host "[ERROR] n8n did not become healthy in time. Run '.\dev.ps1 logs n8n'" -ForegroundColor Red
            exit 1
        }

        # Load credentials from .env
        $envVars = @{}
        Get-Content ".\.env" | ForEach-Object {
            if ($_ -match "^([^#=]+)=(.*)$") { $envVars[$Matches[1].Trim()] = $Matches[2].Trim() }
        }
        $n8nUser = if ($envVars["N8N_USER"]) { $envVars["N8N_USER"] } else { "admin" }
        $n8nPass = if ($envVars["N8N_PASSWORD"]) { $envVars["N8N_PASSWORD"] } else { "changeme" }

        $creds = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${n8nUser}:${n8nPass}"))
        $headers = @{ Authorization = "Basic $creds"; "Content-Type" = "application/json" }

        Get-ChildItem ".\workflows\*.json" | ForEach-Object {
            Write-Host "  Importing $($_.Name)..." -ForegroundColor White
            $body = Get-Content $_.FullName -Raw
            try {
                Invoke-RestMethod -Uri "http://localhost:5678/api/v1/workflows" `
                    -Method POST -Headers $headers -Body $body
                Write-Host "  ✓ Imported $($_.Name)" -ForegroundColor Green
            } catch {
                Write-Host "  ✗ Failed: $_" -ForegroundColor Red
            }
        }
        Write-Host ""
        Write-Host "  Done. Activate workflows in the n8n UI → http://localhost:5678" -ForegroundColor Cyan
    }

    "shell" {
        Write-Host "[shell] Opening shell in fastapi container..." -ForegroundColor Yellow
        docker compose exec fastapi /bin/sh
    }

    default {
        Write-Host "  Usage: .\dev.ps1 <command>" -ForegroundColor White
        Write-Host ""
        Write-Host "  Commands:" -ForegroundColor Gray
        Write-Host "    up           Build + start all Docker services" -ForegroundColor White
        Write-Host "    down         Stop all services" -ForegroundColor White
        Write-Host "    logs [svc]   Stream logs (optionally for one service)" -ForegroundColor White
        Write-Host "    ps           Show container status" -ForegroundColor White
        Write-Host "    clean        Remove all containers + volumes" -ForegroundColor White
        Write-Host "    import       Import n8n workflows via API" -ForegroundColor White
        Write-Host "    shell        Open shell in fastapi container" -ForegroundColor White
        Write-Host ""
    }
}
