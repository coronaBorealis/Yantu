#ifndef MyAppVersion
  #define MyAppVersion "0.2.1"
#endif

#define MyAppName "Yantu 研途"
#define MyAppExeName "Yantu.exe"
#define MyAppPublisher "Yantu contributors"
#define MyAppURL "https://github.com/coronaBorealis/Yantu"
#define MyAppId "{{8EAA093B-3C62-4C9B-9555-A7DB272E35B3}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\Yantu
DefaultGroupName=Yantu 研途
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=Yantu-Setup-{#MyAppVersion}-x64
SetupIconFile=..\src\yantu\web\assets\yantu.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=Yantu.exe
RestartApplications=no
AppMutex=Yantu-8EAA093B-3C62-4C9B-9555-A7DB272E35B3
ChangesEnvironment=no
ChangesAssociations=no

[Languages]
Name: "chinesesimp"; MessagesFile: ".\languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Files]
Source: "..\dist\Yantu\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Yantu 研途"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Yantu 研途"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 Yantu 研途"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
