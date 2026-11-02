; Inno Setup 6 script: the per-user Brainamon installer (projects/desktop-app D4).
; Built by packaging/build.py --installer, which passes /DAppVersion=<version.py>.
; Installs dist\Brainamon (the PyInstaller one-folder build) to
; %LOCALAPPDATA%\Programs\Brainamon on new installs. Interactive uninstall offers opt-in data removal.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifdef Contributor
  #define ProductId "{{893E8B4B-1FC9-483D-8715-3BFA72CBADCE}"
  #define DisplayName "Brainamon Contributor"
  #define InstallFolder "Brainamon-Contributor"
#else
  #define ProductId "{{34C58A03-4ED8-4ADC-B39B-11A4457DBA4F}"
  #define DisplayName "Brainamon"
  #define InstallFolder "Brainamon"
#endif

[Setup]
; Fixed forever: Windows matches updates to the installed app by this id.
AppId={#ProductId}
AppName={#DisplayName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Knackychan
DefaultDirName={localappdata}\Programs\{#InstallFolder}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename={#InstallFolder}-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; An update closes the running app (Restart Manager) before replacing its files.
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#DisplayName}
UninstallDisplayIcon={app}\{#InstallFolder}.exe
; The setup exe's own icon (projects/brainamon-logo/build.py); the app and its shortcuts use Brainamon.exe's.
SetupIconFile=brainamon.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\{#InstallFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update replaces the bundle wholesale, so files dropped from a newer build do not linger.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\{#DisplayName}"; Filename: "{app}\{#InstallFolder}.exe"
Name: "{userdesktop}\{#DisplayName}"; Filename: "{app}\{#InstallFolder}.exe"; Tasks: desktopicon

[Registry]
; Start with Windows is set from Settings > App; uninstall removes it (never created here).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "{#DisplayName}"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#InstallFolder}.exe"; Description: "Start {#DisplayName}"; Flags: nowait postinstall skipifsilent
; An in-app update runs the installer with /SILENT: start the app again when it is done.
Filename: "{app}\{#InstallFolder}.exe"; Flags: nowait; Check: WizardSilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Choice: Integer;
  ResultCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and not UninstallSilent then
  begin
    Choice := MsgBox('Also permanently delete {#DisplayName}''s local saved data?' + #13#10#13#10 +
      'This includes your library, notes, media, chats, settings, saved keys, logins, ' +
      'browser cache and app-managed tools.' + #13#10#13#10 +
      'Yes: review folders to delete.' + #13#10 + 'No: keep saved data.' + #13#10 +
      'Cancel: stop uninstall.', mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON2);
    if Choice = IDCANCEL then
      Abort;
    if Choice = IDYES then
    begin
      if not Exec(ExpandConstant('{app}\{#InstallFolder}.exe'), '--uninstall-data',
          ExpandConstant('{tmp}'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
        RaiseException('Could not open the local data cleanup option. Uninstall stopped.');
      if ResultCode <> 0 then
        Abort;
    end;
  end;
end;

function HasWebView2: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and
             (Version <> '') and (Version <> '0.0.0.0')) or
            (RegQueryStringValue(HKLM32, Key, 'pv', Version) and
             (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup: Boolean;
begin
  Result := HasWebView2;
  if not Result then
    MsgBox('Brainamon needs the Microsoft Edge WebView2 Runtime. Install it from ' +
      'https://developer.microsoft.com/microsoft-edge/webview2/ and run Brainamon setup again.', mbError, MB_OK);
end;
