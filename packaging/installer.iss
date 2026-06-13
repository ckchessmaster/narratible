[Setup]
AppId={{NARRATIBLE-8A7B-4E3D-9F1C-2D5A6B7C8D9E}
AppName=narratible
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\narratible
DefaultGroupName=narratible
OutputBaseFilename=narratible_Installer
SetupIconFile=..\packaging\logo.ico
UninstallDisplayIcon={app}\narratible.exe
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
SetupMutex=narratibleSetupMutex

[Files]
Source: "..\dist\narratible\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\narratible"; Filename: "{app}\narratible.exe"; IconFilename: "{app}\logo.ico"

[Run]
; Silently install FFmpeg via Windows Package Manager to avoid GPL distribution violations
Filename: "cmd.exe"; Parameters: "/c winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"; Description: "Installing FFmpeg (Required for audio merging)..."; Flags: runhidden
; Launch the app
Filename: "{app}\narratible.exe"; Description: "Launch narratible"; Flags: nowait postinstall skipifsilent
