#ifndef AppSourceDir
	#define AppSourceDir "..\dist\narratible"
#endif

[Setup]
AppId={{NARRATIBLE-8A7B-4E3D-9F1C-2D5A6B7C8D9E}
AppName=narratible
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\narratible
DisableDirPage=no
DefaultGroupName=narratible
OutputBaseFilename=narratible_Installer
SetupIconFile=..\packaging\logo.ico
UninstallDisplayIcon={app}\narratible.exe
Compression=lzma2/fast
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
SetupMutex=narratibleSetupMutex

[Tasks]
Name: "localai"; Description: "Set up NVIDIA CUDA local AI and Kokoro now (downloads about 3 GB)"; GroupDescription: "Optional local AI (can be installed later from Settings > Local AI without reinstalling):"

[InstallDelete]
; PyInstaller package layouts change between dependency versions. Remove the
; previous private runtime before copying so obsolete modules cannot survive
; an in-place upgrade and be imported alongside the new build.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
procedure SetRuntimeProgress(const MessageText: String);
begin
	WizardForm.StatusLabel.Caption := MessageText;
	WizardForm.ProgressGauge.Style := npbstMarquee;
end;

procedure RestoreInstallerProgress();
begin
	WizardForm.ProgressGauge.Style := npbstNormal;
end;

function RunRuntimeOperation(
	const VerifyExecutable: String;
	const Arguments: String;
	const InitialMessage: String;
	var ExitCode: Integer
): Boolean;
var
	LaunchCode: Integer;
	ProgressFile: String;
	ResultFile: String;
	ProgressValue: Integer;
	PollCount: Integer;
	MessageText: String;
begin
	ProgressFile := ExpandConstant('{tmp}\narratible-runtime-progress.ini');
	ResultFile := ExpandConstant('{tmp}\narratible-runtime-result.ini');
	DeleteFile(ProgressFile);
	DeleteFile(ResultFile);
	SetRuntimeProgress(InitialMessage);

	Result := Exec(
		VerifyExecutable,
		Arguments +
			' --runtime-progress-file "' + ProgressFile + '"' +
			' --runtime-result-file "' + ResultFile + '"',
		ExpandConstant('{app}'),
		SW_HIDE,
		ewNoWait,
		LaunchCode
	);
	if not Result then
	begin
		ExitCode := 20;
		exit;
	end;

	PollCount := 0;
	while (not FileExists(ResultFile)) and (PollCount < 28800) do
	begin
		if FileExists(ProgressFile) then
		begin
			ProgressValue := GetIniInt('progress', 'progress', 0, 0, 100, ProgressFile);
			MessageText := GetIniString('progress', 'message', InitialMessage, ProgressFile);
			WizardForm.ProgressGauge.Style := npbstNormal;
			WizardForm.ProgressGauge.Position := ProgressValue;
			WizardForm.StatusLabel.Caption := MessageText + ' Do not close Setup.';
		end;
		Sleep(250);
		PollCount := PollCount + 1;
	end;

	if FileExists(ResultFile) then
		ExitCode := GetIniInt('result', 'exit_code', 20, 0, 255, ResultFile)
	else
	begin
		ExitCode := 20;
		Result := False;
	end;
	DeleteFile(ProgressFile);
	DeleteFile(ResultFile);
end;

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

		if (not RunRuntimeOperation(
			VerifyExecutable,
			'--runtime-update-installed',
			'Checking installed local AI profiles...',
			ResultCode
		)) or (ResultCode <> 0) then
			MsgBox(
				'narratible was updated, but one or more local AI profiles could not be refreshed. ' +
				'The previous verified runtime remains active. Use Settings > Local AI to retry. ' +
				'(Exit code ' + IntToStr(ResultCode) + ')',
				mbInformation,
				MB_OK
			);

		if WizardIsTaskSelected('localai') then
		begin
			SetRuntimeProgress('Checking NVIDIA GPU and driver support...');
			if Exec(
				VerifyExecutable,
				'--runtime-preflight',
				ExpandConstant('{app}'),
				SW_HIDE,
				ewWaitUntilTerminated,
				ResultCode
			) then
			begin
				if ResultCode = 0 then
				begin
					if (not RunRuntimeOperation(
						VerifyExecutable,
						'--runtime-bootstrap kokoro',
						'Preparing CUDA local AI and Kokoro...',
						ResultCode
					)) or (ResultCode <> 0) then
						MsgBox(
							'narratible was installed, but CUDA local AI setup did not finish. ' +
							'Open Settings > Local AI and use Repair to retry. ' +
							'(Exit code ' + IntToStr(ResultCode) + ')',
							mbInformation,
							MB_OK
						);
				end
				else if ResultCode <> 10 then
					MsgBox(
						'narratible was installed, but NVIDIA hardware detection failed. ' +
						'Local AI setup can be retried later in Settings. ' +
						'(Exit code ' + IntToStr(ResultCode) + ')',
						mbInformation,
						MB_OK
					);
			end
			else
				MsgBox(
					'narratible was installed, but the local AI setup process could not start. ' +
					'Use Settings > Local AI to retry.',
					mbInformation,
					MB_OK
				);
		end;
		RestoreInstallerProgress();
	end;
end;

[Icons]
Name: "{group}\narratible"; Filename: "{app}\narratible.exe"; IconFilename: "{app}\logo.ico"

[Run]
; Silently install FFmpeg via Windows Package Manager to avoid GPL distribution violations
Filename: "cmd.exe"; Parameters: "/c winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements"; Description: "Installing FFmpeg (Required for audio merging)..."; Flags: runhidden
; Launch the app
Filename: "{app}\narratible.exe"; Description: "Launch narratible"; Flags: nowait postinstall skipifsilent
