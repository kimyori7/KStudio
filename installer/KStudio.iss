; KStudio Inno Setup script
; - 빌드: dist/KStudio/  (PyInstaller onedir 출력) 을 그대로 패키징
; - 설치: 기본 사용자별 LocalAppData (관리자 불필요, 자동 업데이트 30MB 코드패치 호환).
;   사용자가 원하면 설치 다이얼로그에서 Program Files 로 격상 설치 가능 (PrivilegesRequiredOverridesAllowed=dialog).
; - 결과: dist/installer/KStudio-Setup-<version>.exe
; - 코드 서명 안 함 — 미서명 개인 배포라 SmartScreen 경고가 뜰 수 있음

#define AppName       "KStudio"
; AppVersion 은 하드코딩하지 않고 단일 소스 src\screen_recorder\__init__.py 의
; __version__ = "x.y.z" 한 줄에서 읽는다. 정보창·pyproject 도 같은 값을 쓰므로
; 버전 올리기 = bump_version.py 로 그 한 줄만 고치면 인스톨러까지 자동으로 따라온다.
#define VerFile FileOpen(AddBackslash(SourcePath) + "..\src\screen_recorder\__init__.py")
#define VerLine FileRead(VerFile)
#expr FileClose(VerFile)
#define VerRest Copy(VerLine, Pos('"', VerLine) + 1)
#define AppVersion Copy(VerRest, 1, Pos('"', VerRest) - 1)
#if AppVersion == ""
  #error __version__ 파싱 실패: ..\src\screen_recorder\__init__.py
#endif
#define AppPublisher  "kimyori"
#define AppExeName    "KStudio.exe"

[Setup]
AppId={{8B6E5A1F-2E8D-4A1B-9F3C-7D2A0C4E1F6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
; 기본은 사용자별 LocalAppData (관리자 권한 불필요). 사용자가 설치 다이얼로그에서
; Program Files 선택 시 admin 권한으로 격상 (PrivilegesRequiredOverridesAllowed=dialog).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\resources\app_icon.ico
; 위저드 브랜드 배너 — scripts/make_installer_images.py 가 생성 (수동 1회, 커밋).
; 쉼표 목록: Inno 6 가 화면 DPI(100/150/200%)에 맞는 크기를 자동 선택.
WizardImageFile=wizard_banner.bmp,wizard_banner_150.bmp,wizard_banner_200.bmp
WizardSmallImageFile=wizard_small.bmp,wizard_small_150.bmp,wizard_small_200.bmp
; 세로 배너는 환영/완료 페이지에만 나온다 — Inno 6 기본값(yes)은 환영 페이지를
; 건너뛰어 배너가 완료 화면에서야 보이므로 명시적으로 켠다.
DisableWelcomePage=no
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
; .md 는 기본 체크 — 사용자 요청. 설치하면 별도 조작 없이 탐색기 .md 더블클릭이
; KStudio 로 열린다. 원치 않으면 설치 시 체크 해제 가능.
Name: "associatemd"; Description: ".md / .markdown 파일을 KStudio 와 연결"; GroupDescription: "파일 연결:"

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
; .md / .markdown 파일 연결 — Tasks 에서 선택했을 때만. .md 는 다른 에디터와
; 공유하는 흔한 형식이라 앱 첫 실행 자동 등록(windows_assoc) 대상에는 넣지 않고,
; 설치 시 명시적으로 동의한 경우에만 등록한다. ProgID 는 .kstudio 와 구분된
; KStudio.Markdown 사용.
Root: HKCU; Subkey: "Software\Classes\.md"; ValueType: string; ValueName: ""; ValueData: "KStudio.Markdown"; Flags: uninsdeletevalue; Tasks: associatemd
Root: HKCU; Subkey: "Software\Classes\.markdown"; ValueType: string; ValueName: ""; ValueData: "KStudio.Markdown"; Flags: uninsdeletevalue; Tasks: associatemd
Root: HKCU; Subkey: "Software\Classes\KStudio.Markdown"; ValueType: string; ValueName: ""; ValueData: "KStudio Markdown Document"; Flags: uninsdeletekey; Tasks: associatemd
Root: HKCU; Subkey: "Software\Classes\KStudio.Markdown\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: associatemd
Root: HKCU; Subkey: "Software\Classes\KStudio.Markdown\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associatemd

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller _internal 안에 런타임이 만들 수 있는 캐시. 깔끔히 비우고 폴더 제거.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\resources"
