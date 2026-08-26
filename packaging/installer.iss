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

[InstallDelete]
; PyInstaller package layouts change between dependency versions. Remove the
; previous private runtime before copying so obsolete modules cannot survive
; an in-place upgrade and be imported alongside the new build.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\narratible\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
	ResultCode: Integer;
begin
	{ The frozen runtime cannot be replaced reliably while the app is running. }
	Exec(
		ExpandConstant('{cmd}'),
		'/C taskkill /F /IM narratible.exe >nul 2>&1',
		'',
		SW_HIDE,
		ewWaitUntilTerminated,
		ResultCode
	);
	Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
	ResultCode: Integer;
	VerifyExecutable: String;
begin
	if CurStep = ssPostInstall then
	begin
		VerifyExecutable := ExpandConstant('{app}\narratible.exe');
		if (not Exec(
			VerifyExecutable,
			'--verify-tts-imports',
			ExpandConstant('{app}'),
			SW_HIDE,
			ewWaitUntilTerminated,
			ResultCode
		)) or (ResultCode <> 0) then
			RaiseException(
				'Installed runtime verification failed (exit code ' +
				IntToStr(ResultCode) + ').'
			);
	end;
end;

[Icons]
Name: "{group}\narratible"; Filename: "{app}\narratible.exe"; IconFilename: "{app}\logo.ico"

[Run]
; Silently install FFmpeg via Windows Package Manager to avoid GPL distribution violations
Filename: "cmd.exe"; Parameters: "/c winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"; Description: "Installing FFmpeg (Required for audio merging)..."; Flags: runhidden
; Launch the app
Filename: "{app}\narratible.exe"; Description: "Launch narratible"; Flags: nowait postinstall skipifsilent
