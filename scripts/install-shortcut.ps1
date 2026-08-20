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

# WScript.Shell can fail to save Unicode shortcut paths on some Windows Server
# images (including GitHub Actions). Use the native wide-character Shell Link
# interface so Chinese desktop paths and the "研途" file name remain reliable.
if (-not ("Yantu.ShortcutInterop.ShellLink" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Yantu.ShortcutInterop
{
    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    public class ShellLink { }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    public interface IShellLinkW
    {
        void GetPath(IntPtr file, int maxPath, IntPtr data, uint flags);
        void GetIDList(out IntPtr itemIdList);
        void SetIDList(IntPtr itemIdList);
        void GetDescription(IntPtr name, int maxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory(IntPtr directory, int maxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);
        void GetArguments(IntPtr arguments, int maxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int showCommand);
        void SetShowCmd(int showCommand);
        void GetIconLocation(IntPtr iconPath, int iconPathLength, out int iconIndex);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string iconPath, int iconIndex);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    public static class ShortcutWriter
    {
        public static void Save(
            string shortcutPath,
            string targetPath,
            string workingDirectory,
            string iconPath,
            string description)
        {
            IShellLinkW link = (IShellLinkW)new ShellLink();
            try
            {
                link.SetPath(targetPath);
                link.SetWorkingDirectory(workingDirectory);
                link.SetIconLocation(iconPath, 0);
                link.SetDescription(description);
                link.SetShowCmd(1);
                ((IPersistFile)link).Save(shortcutPath, true);
            }
            finally
            {
                if (Marshal.IsComObject(link))
                {
                    Marshal.FinalReleaseComObject(link);
                }
            }
        }
    }
}
"@
}

[Yantu.ShortcutInterop.ShortcutWriter]::Save(
    $shortcutPath,
    $launcherPath,
    $projectRoot,
    $iconPath,
    "Start Yantu and open it in the browser"
)

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
