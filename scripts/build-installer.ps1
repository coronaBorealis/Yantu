param(
    [string]$PythonPath = "",
    [string]$InnoCompiler = "",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $projectRoot

function Assert-ProjectChild([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
    if (-not $full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path is outside the repository: $full"
    }
    return $full
}

function Invoke-HiddenProcess([string]$FilePath, [string[]]$ArgumentList) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList `
        -Wait -PassThru -WindowStyle Hidden
    return $process.ExitCode
}

function Find-PlannerPython {
    if ($PythonPath -and (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }
    if ($env:YANTU_PLANNER_PYTHON -and (Test-Path -LiteralPath $env:YANTU_PLANNER_PYTHON -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $env:YANTU_PLANNER_PYTHON).Path
    }
    $environmentFile = Join-Path $env:USERPROFILE ".conda\environments.txt"
    if (Test-Path -LiteralPath $environmentFile) {
        foreach ($environmentRoot in Get-Content -LiteralPath $environmentFile) {
            if ((Split-Path -Leaf $environmentRoot.Trim()) -eq "planner") {
                $candidate = Join-Path $environmentRoot.Trim() "python.exe"
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
            }
        }
    }
    throw "planner Python was not found. Pass -PythonPath or set YANTU_PLANNER_PYTHON."
}

function Find-InnoCompiler {
    if ($InnoCompiler -and (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $InnoCompiler).Path
    }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    throw "Inno Setup compiler was not found. Install it with: winget install --id JRSoftware.InnoSetup --exact"
}

$python = Find-PlannerPython
$version = (& $python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Could not read the project version." }

$buildRoot = Assert-ProjectChild (Join-Path $projectRoot "build\pyinstaller")
$distRoot = Assert-ProjectChild (Join-Path $projectRoot "dist")
foreach ($target in @($buildRoot, (Join-Path $distRoot "Yantu"), (Join-Path $distRoot "installer"))) {
    $safeTarget = Assert-ProjectChild $target
    if (Test-Path -LiteralPath $safeTarget) { Remove-Item -LiteralPath $safeTarget -Recurse -Force }
}

Write-Host "Building Yantu $version with $python"
& $python -m PyInstaller --noconfirm --clean --workpath $buildRoot --distpath $distRoot "packaging\yantu.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$application = Join-Path $distRoot "Yantu\Yantu.exe"
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) { throw "Yantu.exe was not created." }
$smokeData = Assert-ProjectChild (Join-Path $projectRoot "build\installer-smoke-data")
if (Test-Path -LiteralPath $smokeData) { Remove-Item -LiteralPath $smokeData -Recurse -Force }
$smokeExitCode = Invoke-HiddenProcess $application @(
    "--smoke-test", "--data-dir", "`"$smokeData`""
)
if (Test-Path -LiteralPath $smokeData) {
    Remove-Item -LiteralPath $smokeData -Recurse -Force
}
if ($smokeExitCode -ne 0) { throw "The packaged desktop smoke test failed with exit code $smokeExitCode." }

if ($SkipInstaller) {
    Write-Host "Desktop bundle ready: $application"
    exit 0
}

$iscc = Find-InnoCompiler
& $iscc "/DMyAppVersion=$version" "packaging\yantu.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }

$installer = Join-Path $distRoot "installer\Yantu-Setup-$version-x64.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "The installer was not created." }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
$hashFile = "$installer.sha256"
[System.IO.File]::WriteAllText($hashFile, "$hash  $(Split-Path -Leaf $installer)`r`n", [System.Text.UTF8Encoding]::new($false))

$installRoot = Assert-ProjectChild (Join-Path $projectRoot "build\installed-smoke-app")
$installData = Assert-ProjectChild (Join-Path $projectRoot "build\installed-smoke-data")
foreach ($target in @($installRoot, $installData)) {
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}
$installExitCode = Invoke-HiddenProcess $installer @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", "/TASKS=", "/DIR=`"$installRoot`""
)
if ($installExitCode -ne 0) { throw "Silent installer smoke test failed with exit code $installExitCode." }
$installedApplication = Join-Path $installRoot "Yantu.exe"
if (-not (Test-Path -LiteralPath $installedApplication -PathType Leaf)) {
    throw "The installed Yantu.exe was not found."
}
$installedSmokeExitCode = Invoke-HiddenProcess $installedApplication @(
    "--smoke-test", "--data-dir", "`"$installData`""
)
if ($installedSmokeExitCode -ne 0) {
    throw "The installed desktop smoke test failed with exit code $installedSmokeExitCode."
}
$uninstaller = Join-Path $installRoot "unins000.exe"
if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw "The uninstaller was not created." }
$uninstallExitCode = Invoke-HiddenProcess $uninstaller @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
)
if ($uninstallExitCode -ne 0) { throw "Silent uninstall smoke test failed with exit code $uninstallExitCode." }
if (Test-Path -LiteralPath $installData) { Remove-Item -LiteralPath $installData -Recurse -Force }

Write-Host "Installer ready: $installer"
Write-Host "SHA256: $hash"
