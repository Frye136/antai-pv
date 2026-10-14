; Installateur Windows d'ANTAI PV (Inno Setup 6).
;   ISCC.exe /DAppVersion=1.6.0 installer\AntaiPV.iss      -> dist\AntaiPV-Setup.exe
; Installation dans le profil de l'utilisateur, sans droits administrateur : le dossier reste accessible en
; écriture, ce qui permet à l'application de se mettre à jour elle-même (app/updater.py).
; Les données (Documents\AntaiPV) ne sont jamais touchées, ni à l'installation ni à la désinstallation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7D3F6A2B-9C1E-4F5A-8B2D-3E6C1A9F4B70}
AppName=ANTAI PV
AppVersion={#AppVersion}
AppVerName=ANTAI PV {#AppVersion}
AppPublisher=Projet libre ANTAI PV
AppPublisherURL=https://github.com/Frye136/antai-pv
AppSupportURL=https://github.com/Frye136/antai-pv/issues
AppUpdatesURL=https://github.com/Frye136/antai-pv/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\AntaiPV
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AntaiPV-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AntaiPV.exe
UninstallDisplayName=ANTAI PV
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AntaiPV.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ANTAI PV"; Filename: "{app}\AntaiPV.exe"; Comment: "Dénonciation des contraventions"
Name: "{autodesktop}\ANTAI PV"; Filename: "{app}\AntaiPV.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AntaiPV.exe"; Description: "{cm:LaunchProgram,ANTAI PV}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; reste éventuel d'une mise à jour automatique
Type: files; Name: "{app}\AntaiPV.old.exe"

[Messages]
french.FinishedLabel=ANTAI PV est installé.%n%nVos données sont enregistrées dans Documents\AntaiPV (modifiable dans les Paramètres). Le logiciel se mettra à jour automatiquement.
