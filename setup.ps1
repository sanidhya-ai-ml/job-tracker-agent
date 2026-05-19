# setup.ps1 - Job Tracker Agent: Python Virtual Environment Setup (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Job Tracker Agent - Environment Setup" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check Python ──────────────────────────────────────────────────────────
Write-Host "[1/5] Checking Python version..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "      Found: $ver" -ForegroundColor Green
            break
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Host "[ERROR] Python 3 not found. Download from https://python.org" -ForegroundColor Red
    exit 1
}

# ── 2. Create virtual environment ────────────────────────────────────────────
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow
$venvPath = Join-Path $PSScriptRoot ".venv"
if (Test-Path $venvPath) {
    Write-Host "      .venv already exists, skipping creation." -ForegroundColor Gray
} else {
    & $pythonCmd -m venv $venvPath
    Write-Host "      Created .venv" -ForegroundColor Green
}

# ── 3. Upgrade pip ───────────────────────────────────────────────────────────
Write-Host "[3/5] Upgrading pip..." -ForegroundColor Yellow
$pipExe   = Join-Path $venvPath "Scripts\pip.exe"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip --quiet
Write-Host "      pip upgraded." -ForegroundColor Green

# ── 4. Install dependencies ──────────────────────────────────────────────────
Write-Host "[4/5] Installing dependencies from requirements.txt..." -ForegroundColor Yellow
$reqPath = Join-Path $PSScriptRoot "requirements.txt"
& $pipExe install -r $reqPath
Write-Host "      All packages installed." -ForegroundColor Green

# ── 5. Copy .env if not present ──────────────────────────────────────────────
Write-Host "[5/5] Setting up .env file..." -ForegroundColor Yellow
$envFile    = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "      .env created from .env.example" -ForegroundColor Green
    Write-Host "      IMPORTANT: Edit .env and fill in your API keys!" -ForegroundColor Magenta
} else {
    Write-Host "      .env already exists, skipping." -ForegroundColor Gray
}

# ── Summary ──────────────────────────────────────────────────────────────────
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Activate venv:       & '$activateScript'" -ForegroundColor White
Write-Host "  Run FastAPI locally: cd backend; uvicorn main:app --reload" -ForegroundColor White
Write-Host "  Run with Docker:     .\dev.ps1 up" -ForegroundColor White
Write-Host ""
