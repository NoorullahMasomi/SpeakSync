; Inno Setup 6 script - tools\build.py runs it when Inno Setup is installed.
; Installs for the current user only (no admin rights needed), adds a Start menu and desktop shortcut.

#ifndef MyVersion
  #define MyVersion "1.0.0"
#endif
#ifndef MyRoot
  #define MyRoot ".."
#endif

[Setup]
AppId={{6B0E2C41-4E37-4C5B-9C1E-5D2B7A9F3E10}
AppName=SpeakSync
AppVersion={#MyVersion}
AppVerName=SpeakSync {#MyVersion}
AppPublisher=Noorullah Masomi
AppPublisherURL=https://github.com/Noorullahmasomi/SpeakSync
AppSupportURL=https://github.com/Noorullahmasomi/SpeakSync/issues
AppUpdatesURL=https://github.com/Noorullahmasomi/SpeakSync/releases
DefaultDirName={localappdata}\Programs\SpeakSync
DefaultGroupName=SpeakSync
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MyRoot}\release
OutputBaseFilename=SpeakSync-{#MyVersion}-setup
SetupIconFile={#MyRoot}\assets\icon.ico
UninstallDisplayIcon={app}\SpeakSync.exe
LicenseFile={#MyRoot}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyRoot}\dist\SpeakSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\SpeakSync"; Filename: "{app}\SpeakSync.exe"
Name: "{group}\Uninstall SpeakSync"; Filename: "{uninstallexe}"
Name: "{userdesktop}\SpeakSync"; Filename: "{app}\SpeakSync.exe"; Tasks: desktopicon

[Registry]
; double-click a project.speaksync file -> SpeakSync opens it
Root: HKCU; Subkey: "Software\Classes\.speaksync"; ValueType: string; ValueData: "SpeakSync.Project"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SpeakSync.Project"; ValueType: string; ValueData: "SpeakSync project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SpeakSync.Project\DefaultIcon"; ValueType: string; ValueData: "{app}\SpeakSync.exe,0"
Root: HKCU; Subkey: "Software\Classes\SpeakSync.Project\shell\open\command"; ValueType: string; ValueData: """{app}\SpeakSync.exe"" ""%1"""

[Run]
Filename: "{app}\SpeakSync.exe"; Description: "{cm:LaunchProgram,SpeakSync}"; Flags: nowait postinstall skipifsilent
