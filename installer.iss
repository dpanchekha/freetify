#define AppName "Freetify"
#define AppVersion "1.0.0"
#define AppPublisher "Freetify"
#define AppExeName "Freetify.exe"

[Setup]
AppId={{B8C63D4C-6E9E-4E50-9D7A-5F1FE7FEE710}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Freetify
DefaultGroupName=Freetify
OutputBaseFilename=FreetifySetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Files]
Source: "dist\Freetify\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Freetify"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Freetify"; Filename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Freetify"; Flags: nowait postinstall skipifsilent
