param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $projectRoot

function Find-PlannerPython {
    if ($env:YANTU_PLANNER_PYTHON -and (Test-Path -LiteralPath $env:YANTU_PLANNER_PYTHON)) {
        return (Resolve-Path -LiteralPath $env:YANTU_PLANNER_PYTHON).Path
    }

    $registeredEnvironments = Join-Path $env:USERPROFILE ".conda\environments.txt"
    if (Test-Path -LiteralPath $registeredEnvironments) {
        foreach ($environmentRoot in Get-Content -LiteralPath $registeredEnvironments) {
            if ((Split-Path -Leaf $environmentRoot.Trim()) -eq "planner") {
                $candidate = Join-Path $environmentRoot.Trim() "python.exe"
                if (Test-Path -LiteralPath $candidate) {
                    return (Resolve-Path -LiteralPath $candidate).Path
                }
            }
        }
    }

    $fallbacks = @(
        (Join-Path $env:USERPROFILE ".conda\envs\planner\python.exe"),
        (Join-Path $env:USERPROFILE "miniconda3\envs\planner\python.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\envs\planner\python.exe")
    )
    foreach ($candidate in $fallbacks) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Conda environment 'planner' was not found. Confirm it appears in: conda env list"
}

try {
    $plannerPython = Find-PlannerPython
    $pythonVersion = & $plannerPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ($LASTEXITCODE -ne 0) {
        throw "The planner Python interpreter could not be executed: $plannerPython"
    }
    if (-not $pythonVersion.StartsWith("3.11.")) {
        throw "Yantu requires Python 3.11, but planner is using Python $pythonVersion"
    }

    Write-Host "Yantu project: $projectRoot"
    Write-Host "Python: $plannerPython ($pythonVersion)"

    & $plannerPython -c "import flask, dotenv" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Yantu dependencies are missing. Run 'conda activate planner' and then 'pip install -r requirements.txt'."
    }

    $runtimeFile = Join-Path $projectRoot "data\runtime.json"
    if (Test-Path -LiteralPath $runtimeFile) {
        try {
            $runtime = Get-Content -Raw -LiteralPath $runtimeFile | ConvertFrom-Json
            $health = Invoke-RestMethod -Uri ($runtime.url + "/api/health") -TimeoutSec 2
            $expectedDatabase = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "data\yantu.db"))
            if ($health.status -eq "ok" -and
                $health.instance_id -eq $runtime.instance_id -and
                [System.IO.Path]::GetFullPath($health.database) -eq $expectedDatabase) {
                Write-Host "Yantu is already running: $($runtime.url)"
                if (-not $NoBrowser) {
                    try {
                        Start-Process $runtime.url
                    }
                    catch {
                        Write-Host "The browser could not be opened automatically. Open this address manually: $($runtime.url)"
                    }
                }
                exit 0
            }
        }
        catch {
            Write-Host "Ignoring stale runtime information."
        }
    }

    $serverArguments = @((Join-Path $projectRoot "server.py"))
    if ($NoBrowser) {
        $serverArguments += "--no-browser"
    }
    & $plannerPython @serverArguments
    $serverExit = $LASTEXITCODE
    if ($serverExit -ne 0) {
        throw "Yantu backend stopped with exit code $serverExit"
    }
    exit 0
}
catch {
    Write-Host ""
    Write-Host "STARTUP ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
