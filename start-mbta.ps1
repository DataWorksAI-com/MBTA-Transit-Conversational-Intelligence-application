# start-mbta.ps1
Write-Host "=== Starting MBTA Agentcy System (Hybrid A2A + MCP) ===" -ForegroundColor Cyan

# Load .env file
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2])
        }
    }
    Write-Host "Loaded environment variables from .env" -ForegroundColor Green
}

# Check API key (from .env or fallback)
if (-not $env:OPENAI_API_KEY) {
    Write-Host "ERROR: OPENAI_API_KEY not set!" -ForegroundColor Red
    exit 1
}

# Check if Docker is running
Write-Host "`nChecking Docker..." -ForegroundColor Yellow
$dockerRunning = $false
try {
    docker info | Out-Null
    $dockerRunning = $true
    Write-Host "  OK Docker is running" -ForegroundColor Green
}
catch {
    Write-Host "  WARNING: Docker is not running - observability will not be available" -ForegroundColor Yellow
    Write-Host "  System will continue without Jaeger/Grafana" -ForegroundColor Gray
}

# Start observability stack (optional)
if ($dockerRunning) {
    Write-Host "`nStarting observability stack..." -ForegroundColor Yellow
    docker-compose -f docker-compose-observability.yml up -d 2>$null

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK Observability stack started" -ForegroundColor Green
        Write-Host "     - ClickHouse: http://localhost:8123" -ForegroundColor Gray
        Write-Host "     - Jaeger:     http://localhost:16686" -ForegroundColor Gray
        Write-Host "     - Grafana:    http://localhost:3001" -ForegroundColor Gray
    }
    else {
        Write-Host "  WARNING: Observability stack skipped" -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 5
}

# Save API key for terminals
$apiKey = $env:OPENAI_API_KEY

# Start Python services
Write-Host "`nStarting Python services..." -ForegroundColor Yellow

# 1. Exchange Agent (Hybrid A2A + MCP Orchestrator)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; `$env:OPENAI_API_KEY='$apiKey'; `$host.UI.RawUI.WindowTitle = 'Exchange Agent (8100) - Hybrid Orchestrator'; python -m src.exchange_agent.exchange_server"
Write-Host "  OK Exchange Agent (8100) - Hybrid A2A + MCP" -ForegroundColor Green
Start-Sleep -Seconds 5

# 2. Alerts Agent (A2A)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; `$host.UI.RawUI.WindowTitle = 'Alerts Agent (8001)'; python -m uvicorn src.agents.alerts.main:app --host 0.0.0.0 --port 8001 --reload"
Write-Host "  OK Alerts Agent (8001) - A2A" -ForegroundColor Green
Start-Sleep -Seconds 2

# 3. Planner Agent (A2A)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; `$host.UI.RawUI.WindowTitle = 'Planner Agent (8002)'; python -m uvicorn src.agents.planner.main:app --host 0.0.0.0 --port 8002 --reload"
Write-Host "  OK Planner Agent (8002) - A2A" -ForegroundColor Green
Start-Sleep -Seconds 2

# 4. StopFinder Agent (A2A)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; `$host.UI.RawUI.WindowTitle = 'StopFinder Agent (8003)'; python -m uvicorn src.agents.stopfinder.main:app --host 0.0.0.0 --port 8003 --reload"
Write-Host "  OK StopFinder Agent (8003) - A2A" -ForegroundColor Green
Start-Sleep -Seconds 2

# 5. Frontend UI (Optional)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; `$host.UI.RawUI.WindowTitle = 'Frontend UI (3000)'; python -m uvicorn src.frontend.chat_server:app --host 0.0.0.0 --port 3000 --reload"
Write-Host "  OK Frontend UI (3000)" -ForegroundColor Green

Write-Host "`nWaiting for services to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 8

Write-Host "`n=====================================================================" -ForegroundColor Green
Write-Host "SUCCESS! MBTA Agentcy System Started" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green

Write-Host "`nSystem Architecture:" -ForegroundColor Cyan
Write-Host "  Exchange Agent:  http://localhost:8100 (Hybrid Orchestrator)" -ForegroundColor White
Write-Host "     - MCP Fast Path: ~50-100ms for simple queries" -ForegroundColor Gray
Write-Host "     - A2A Path: ~500-800ms for complex queries" -ForegroundColor Gray
Write-Host "     - 32 MCP tools available" -ForegroundColor Gray
Write-Host ""
Write-Host "  Alerts Agent:    http://localhost:8001 (A2A)" -ForegroundColor White
Write-Host "  Planner Agent:   http://localhost:8002 (A2A)" -ForegroundColor White
Write-Host "  StopFinder Agent: http://localhost:8003 (A2A)" -ForegroundColor White
Write-Host "  Frontend UI:     http://localhost:3000" -ForegroundColor White

Write-Host "`nObservability:" -ForegroundColor Cyan
Write-Host "  Jaeger:          http://localhost:16686" -ForegroundColor White
Write-Host "  Grafana:         http://localhost:3001 (admin/admin)" -ForegroundColor White

Write-Host "`nQuick Tests:" -ForegroundColor Yellow
Write-Host "  Health Check:" -ForegroundColor White
Write-Host "    irm http://localhost:8100/" -ForegroundColor Gray

Write-Host "`n  MCP Fast Path (simple query):" -ForegroundColor White
Write-Host "    irm http://localhost:8100/chat -Method Post -ContentType 'application/json' -Body '{`"query`": `"Red Line delays?`"}'" -ForegroundColor Gray

Write-Host "`n  A2A Path (complex query):" -ForegroundColor White
Write-Host "    irm http://localhost:8100/chat -Method Post -ContentType 'application/json' -Body '{`"query`": `"How do I get from Harvard to MIT?`"}'" -ForegroundColor Gray

Write-Host "`nTo Stop All Services:" -ForegroundColor Yellow
Write-Host "  .\stop-mbta.ps1" -ForegroundColor Gray
Write-Host ""