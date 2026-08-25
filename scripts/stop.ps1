$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dataRoot = if ($env:YANTU_DATA_DIR) { [System.IO.Path]::GetFullPath($env:YANTU_DATA_DIR) } else { Join-Path $projectRoot "data" }
$runtimeFile = Join-Path $dataRoot "runtime.json"

if (-not (Test-Path -LiteralPath $runtimeFile)) {
    Write-Host "Yantu is not running (no runtime file was found)."
    exit 0
}

try {
    $runtime = Get-Content -Raw -LiteralPath $runtimeFile | ConvertFrom-Json
    $headers = @{ "X-Yantu-Shutdown" = $runtime.shutdown_token }
    Invoke-RestMethod -Method Post -Uri ($runtime.url + "/api/shutdown") -Headers $headers -TimeoutSec 3 | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 100
        if (-not (Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue)) {
            Write-Host "Yantu stopped cleanly."
            exit 0
        }
    }
    throw "The backend did not stop within three seconds. Close its startup window."
}
catch {
    if (-not (Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $runtimeFile -Force -ErrorAction SilentlyContinue
        Write-Host "Yantu was already stopped; stale runtime information was removed."
        exit 0
    }
    Write-Host "STOP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
