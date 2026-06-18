Write-Host "=== Stopping MBTA Agntcy System ===" -ForegroundColor Cyan

Write-Host "
Stopping Docker services..." -ForegroundColor Yellow
docker-compose -f docker-compose-observability.yml down 2>$null
Write-Host "  OK Docker services stopped" -ForegroundColor Green

Write-Host "
Stopping Python services..." -ForegroundColor Yellow
$ports = @(8100, 8101, 8001, 8002, 8003, 3000)
$stopped = 0

foreach ($port in $ports) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($conn) {
            $pid = $conn | Select-Object -ExpandProperty OwningProcess -Unique
            Stop-Process -Id $pid -Force 2>$null
            Write-Host "  OK Stopped service on port $port" -ForegroundColor Green
            $stopped++
        }
    } catch {}
}

if ($stopped -eq 0) {
    Write-Host "  No services were running" -ForegroundColor Yellow
}

Write-Host "
SUCCESS: System stopped" -ForegroundColor Green
