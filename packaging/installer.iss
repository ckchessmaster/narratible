[Setup]
AppName=Echo-Scribe
AppVersion=0.1.0
DefaultDirName={localappdata}\EchoScribe
DefaultGroupName=Echo-Scribe
OutputBaseFilename=EchoScribe_Installer
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest

[Files]
Source: "..\dist\EchoScribe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Echo-Scribe"; Filename: "{app}\EchoScribe.exe"; IconFilename: "{app}\EchoScribe.exe"

[Run]
; Silently install FFmpeg via Windows Package Manager to avoid GPL distribution violations
Filename: "cmd.exe"; Parameters: "/c winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"; Description: "Installing FFmpeg (Required for audio merging)..."; Flags: runhidden
; Launch the app
Filename: "{app}\EchoScribe.exe"; Description: "Launch Echo-Scribe"; Flags: nowait postinstall skipifsilent
