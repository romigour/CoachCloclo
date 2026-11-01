; Installateur CoachCloclo (Inno Setup 6)
; Compilation : iscc /DAppVersion=0.2.0 packaging\windows\installer.iss
; Prérequis : dist\CoachCloclo\ construit par PyInstaller (coachcloclo.spec).

#ifndef AppVersion
  #error AppVersion manquant : compiler avec /DAppVersion=x.y.z
#endif

[Setup]
AppId={{8F3C2B1E-6A4D-4E7B-9C21-5D0E7A1B3C44}
AppName=CoachCloclo
AppVersion={#AppVersion}
; Installation par utilisateur : pas d'UAC
DefaultDirName={localappdata}\Programs\CoachCloclo
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=CoachCloclo-Setup-{#AppVersion}
SetupIconFile=coachcloclo.ico
UninstallDisplayIcon={app}\CoachCloclo.exe
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\CoachCloclo\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\CoachCloclo"; Filename: "{app}\CoachCloclo.exe"
Name: "{autodesktop}\CoachCloclo"; Filename: "{app}\CoachCloclo.exe"; Tasks: desktopicon

[Run]
; Pas de skipifsilent : une mise à jour silencieuse relance l'appli, sans ouvrir de
; navigateur (l'onglet existant se recharge tout seul) ; l'installation interactive
; ouvre l'appli normalement.
Filename: "{app}\CoachCloclo.exe"; Parameters: "--no-browser"; Description: "{cm:LaunchProgram,CoachCloclo}"; Flags: nowait postinstall; Check: WizardSilent
Filename: "{app}\CoachCloclo.exe"; Description: "{cm:LaunchProgram,CoachCloclo}"; Flags: nowait postinstall; Check: not WizardSilent

; [UninstallDelete] volontairement absent : les données vivent dans
; %LOCALAPPDATA%\CoachCloclo, jamais sous {app}.

[Code]
const
  MutexAppli = 'CoachCloclo.Instance';
  AttenteMaxMs = 30000;
  PasMs = 500;

{ Attend que l'appli libère son mutex ; renvoie True si elle l'a quitté à temps. }
function AttendreFermeture(): Boolean;
var
  ecoule: Integer;
begin
  ecoule := 0;
  while CheckForMutexes(MutexAppli) and (ecoule < AttenteMaxMs) do
  begin
    Sleep(PasMs);
    ecoule := ecoule + PasMs;
  end;
  Result := not CheckForMutexes(MutexAppli);
end;

function InitializeSetup(): Boolean;
begin
  Result := AttendreFermeture();
  if not Result then
    MsgBox('CoachCloclo est en cours d''exécution. Quitte-le depuis l''icône près de l''horloge, puis relance l''installation.',
      mbError, MB_OK);
end;

function InitializeUninstall(): Boolean;
begin
  Result := AttendreFermeture();
  if not Result then
    MsgBox('Quitte CoachCloclo avant de le désinstaller.', mbError, MB_OK);
end;
