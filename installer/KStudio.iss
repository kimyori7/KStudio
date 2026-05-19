; KStudio Inno Setup script
; - 빌드: dist/KStudio/  (PyInstaller onedir 출력) 을 그대로 패키징
; - 설치: 기본 Program Files (관리자 권한 필요), 사용자가 거부 시 %LocalAppData%\Programs\KStudio 로 폴백
;   (PrivilegesRequiredOverridesAllowed=dialog — 사내 admin 권한 제한 환경에서도 설치 가능하게).
; - 결과: dist/installer/KStudio-Setup-<version>.exe
; - 코드 서명 안 함 — SmartScreen 경고 발생 가능 (내부 배포 가정)

#define AppName       "KStudio"
#define AppVersion    "0.1.0"
#define AppPublisher  "kimyori"
#define AppExeName    "KStudio.exe"

[Setup]
AppId={{8B6E5A1F-2E8D-4A1B-9F3C-7D2A0C4E1F6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
; 기본 admin 권한으로 Program Files 에 설치. 사용자가 UAC 다이얼로그에서 거부하면
; Inno Setup 가 자동으로 LocalAppData\Programs 폴백 옵션 제공 (override=dialog).
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\resources\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; LZMA2 max 는 압축률 우선 — KStudio 폴더 521MB → 약 100~150MB 인스톨러 예상
LZMAUseSeparateProcess=yes
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "associatekstudio"; Description: ".kstudio 파일을 KStudio 와 연결"; GroupDescription: "파일 연결:"; Flags: unchecked

[Dirs]
; 기본 저장 폴더 미리 생성 — settings.json 의 save_dir/output_dir 가 빈 문자열일 때
; 앱이 떨어지는 기본 경로 (Path.home() / "KStudio" / ...). 사용자가 처음 캡처/녹화
; 했을 때 폴더가 없어 실패하는 것 방지. uninstaller 는 이 폴더를 건드리지 않음
; (사용자 파일이 들어있을 수 있으므로). uninsneveruninstall 플래그로 보호.
Name: "{%USERPROFILE}\KStudio"; Flags: uninsneveruninstall
Name: "{%USERPROFILE}\KStudio\Image"; Flags: uninsneveruninstall
Name: "{%USERPROFILE}\KStudio\Video"; Flags: uninsneveruninstall

[Files]
; PyInstaller 가 빌드한 결과물 전체를 그대로 복사.
; recursesubdirs + createallsubdirs 로 _internal 트리까지 보존.
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; .kstudio 파일 연결 — Tasks 에서 선택했을 때만. 미선택 시에는 앱 첫 실행 때
; windows_assoc.ensure_associated() 가 HKCU 에 등록함 (idempotent).
Root: HKCU; Subkey: "Software\Classes\.kstudio"; ValueType: string; ValueName: ""; ValueData: "KStudio.Document"; Flags: uninsdeletevalue; Tasks: associatekstudio
Root: HKCU; Subkey: "Software\Classes\KStudio.Document"; ValueType: string; ValueName: ""; ValueData: "KStudio Document"; Flags: uninsdeletekey; Tasks: associatekstudio
Root: HKCU; Subkey: "Software\Classes\KStudio.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: associatekstudio
Root: HKCU; Subkey: "Software\Classes\KStudio.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associatekstudio

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller _internal 안에 런타임이 만들 수 있는 캐시. 깔끔히 비우고 폴더 제거.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\resources"
