; TidyDek Inno Setup 6 script.
;
; Version discipline: APP_NAME and VERSION are parsed out of src/version.py
; at compile time via ISPP. There are deliberately NO version literals here,
; and tests/test_version_ssot.py guards that invariant.

#define AppVersionSrc "..\src\version.py"

#define VerHandle FileOpen(AppVersionSrc)
#define VerSource FileRead(VerHandle)

#define NameMarker 'APP_NAME = "'
#define NameStart Pos(NameMarker, VerSource)
#if NameStart == 0
  #error 'APP_NAME = "..."' marker not found in src/version.py
#endif
#define NameBody Copy(VerSource, NameStart + Len(NameMarker), Len(VerSource))
#define AppName Trim(Copy(NameBody, 1, Pos('"', NameBody) - 1))

#define VersionMarker 'VERSION = "'
#define VersionStart Pos(VersionMarker, VerSource)
#if VersionStart == 0
  #error 'VERSION = "..."' marker not found in src/version.py
#endif
#define VersionBody Copy(VerSource, VersionStart + Len(VersionMarker), Len(VerSource))
#define AppVersion Trim(Copy(VersionBody, 1, Pos('"', VersionBody) - 1))

[Setup]
AppId={{7E2A6C41-9F0D-4B8E-A5C3-1D4F7B90E2A8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName} Team
SetupIconFile=..\assets\icon.ico
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename={#AppName}-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppName}.exe

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppName}.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent unchecked
