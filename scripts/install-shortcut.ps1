param(
    [string]$DestinationDirectory = "",
    [switch]$PassThru
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$launcherPath = Join-Path $projectRoot "start.bat"
$iconPath = Join-Path $projectRoot "src\yantu\web\assets\yantu.ico"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Yantu launcher was not found: $launcherPath"
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Yantu icon was not found: $iconPath"
}

if ([string]::IsNullOrWhiteSpace($DestinationDirectory)) {
    $DestinationDirectory = [Environment]::GetFolderPath("Desktop")
}
$destination = [System.IO.Path]::GetFullPath($DestinationDirectory)
[System.IO.Directory]::CreateDirectory($destination) | Out-Null
$shortcutName = "Yantu " + [char]0x7814 + [char]0x9014 + ".lnk"
$shortcutPath = Join-Path $destination $shortcutName

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcherPath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = "Start Yantu and open it in the browser"
$shortcut.WindowStyle = 1
$shortcut.Save()

if ($PassThru) {
    $details = [PSCustomObject]@{
        Path = $shortcutPath
        TargetPath = $launcherPath
        WorkingDirectory = $projectRoot
        IconLocation = "$iconPath,0"
    }
    $details | ConvertTo-Json -Compress
} else {
    Write-Host "Yantu desktop shortcut updated: $shortcutPath"
}
