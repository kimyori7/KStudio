"""앱 설정 모델 + JSON 저장/로드."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
import json
from pathlib import Path
from typing import get_type_hints


def default_image_dir() -> Path:
    """이미지/스크린샷 기본 저장 폴더 — 사용자 홈\\KStudio\\Image."""
    return Path.home() / "KStudio" / "Image"


def default_video_dir() -> Path:
    """영상 녹화 기본 저장 폴더 — 사용자 홈\\KStudio\\Video."""
    return Path.home() / "KStudio" / "Video"


@dataclass
class GeneralSettings:
    output_dir: str = ""  # 빈 문자열이면 ~/KStudio/Video
    filename_pattern: str = "rec_{date}_{time}"
    mode: str = "video"     # "video" | "gif"
    target: str = "fullscreen"  # "fullscreen" | "window" | "region"
    # 지정 영역 모드의 마지막 창 위치/크기. -1이면 미설정(최초 실행 시 기본값 사용).
    region_x: int = -1
    region_y: int = -1
    region_w: int = -1
    region_h: int = -1
    # 전체 화면 모드에서 녹화할 모니터 인덱스 (0=주 모니터). 모니터 연결 상태가
    # 바뀌어 범위를 벗어나면 FullScreenTarget 이 자동으로 클램프한다.
    fullscreen_monitor_index: int = 0


@dataclass
class VideoSettings:
    container: str = "mp4"          # mp4 | mkv | webm
    codec: str = "h264"             # h264 | h265 | vp9
    fps: int = 30                   # 30 | 60
    scale_percent: int = 100        # 10..100
    bitrate_kbps: int = 8000


@dataclass
class GifSettings:
    fps: int = 10
    scale_percent: int = 100        # 10..100
    colors: int = 256


@dataclass
class SoundSettings:
    system_audio_enabled: bool = True
    codec: str = "aac"              # aac | mp3
    bitrate_kbps: int = 192


@dataclass
class HotkeySettings:
    toggle_record: str = "Ctrl+Shift+T"        # 영역 녹화 (3-state 무장→시작→정지)
    screenshot_region: str = "Ctrl+Shift+R"    # 영역 스크린샷
    screenshot_full: str = ""                  # 빈 문자열 = 미할당
    # "전체 녹화" 단축키 — 환경설정 리스트에서 사용자가 지정 가능. 현재는
    # 글로벌 핫키 등록만 placeholder (별도 액션 핸들러는 후속에 추가 예정).
    toggle_record_full: str = ""
    # 단축키 프리셋 식별자. 빈 문자열 = 첫 실행 (다이얼로그 노출). 사용자가 개별 키를
    # 수정하면 "custom" 으로 자동 전환. 값: "" | "windows-standard" | "kstudio-default" | "custom"
    preset_name: str = ""
    # OS 시스템 단축키(Win+Shift+S 같은) 가로채기 — low-level keyboard hook 사용.
    # 기본 off — 켜면 OS Snipping Tool 이 KStudio 한테 가려짐 + 일부 게임 anti-cheat
    # 와 마찰 가능성. 사용자가 의도적으로 켤 때만 활성.
    intercept_system_keys: bool = False


@dataclass
class ScreenshotSettings:
    save_dir: str = ""  # 빈 문자열이면 ~/KStudio/Image
    filename_pattern: str = "screenshot_{date}_{time}"
    format: str = "png"
    magnifier_enabled: bool = True
    # 뷰어 창 위치/크기 (-1이면 미설정). 최대화 상태에서도 "일반 창" 크기로 저장됨
    # (normalGeometry 사용) — 다음 실행 시 최대화 해제하면 이 크기로 돌아온다.
    viewer_x: int = -1
    viewer_y: int = -1
    viewer_w: int = -1
    viewer_h: int = -1
    # 종료 시점 최대화 상태였는지. True 면 다음 실행 시 일반 크기 적용 후 추가로 최대화.
    viewer_maximized: bool = False


@dataclass
class AnnotationSettings:
    last_color: str = "#E53935"   # 마지막 사용 색상 (hex, #RRGGBB)
    last_thickness: int = 2        # 마지막 사용 두께 단계 (1~4)
    # 자동 누끼(rembg) 마지막 선택 모델 — 자동 누끼 다이얼로그가 기본값으로 사용.
    bg_removal_model: str = "u2net"


@dataclass
class PreferencesSettings:
    autostart: bool = False
    minimize_to_tray: bool = True
    use_mini_control: bool = True
    language: str = "ko"
    # 메인 윈도우 dock 레이아웃 — QMainWindow.saveState() 결과를 base64 로 직렬화한 문자열.
    # 빈 문자열이면 기본 레이아웃 사용. 이미지/영상 모드별로 분리해 저장.
    dock_state_b64: str = ""              # 호환성 (구버전 단일 키) — image 가 비었을 때 fallback
    dock_state_image_b64: str = ""        # 이미지 모드 dock 레이아웃
    dock_state_video_b64: str = ""        # 영상 모드 dock 레이아웃
    # KStudio UI 자체를 녹화·스크린샷에 포함시킬지. 켜면 minimize_to_tray /
    # use_mini_control 무시 + WDA_EXCLUDEFROMCAPTURE 해제 → 메인 창이 결과에 정상 포함.
    # 글로벌 툴바 ("내 화면에 보이기" 체크박스) 에서 토글.
    keep_visible_during_capture: bool = False
    # 편집 모드 — 영상 모드의 모든 탭에 전역 적용. 세션 간 영속 (사용자 결정 2026-05-11).
    edit_mode_on: bool = False
    # 배속 효과 일괄 켜기/끄기 — PlayerControls 의 ▶▶ ON/OFF 버튼 상태 영속.
    speed_effects_enabled: bool = True
    # 최근 라이브러리 항목 — 폴더 스캔 대신 "최근 연 파일" 목록 영속. 최대 50개,
    # 시작 시 path 존재 체크 통과한 것만 복원. 항목 dict 키: kind/path/display_name/
    # duration_ms/origin/created_at (ISO 문자열). 썸네일은 library_thumbs 캐시 폴더.
    recent_library_entries: list = field(default_factory=list)
    # Dock 가시성 영속 — saveState/restoreState 는 위치만 저장, 메뉴 체크 상태는 별도.
    # 사용자가 X 로 닫은 dock 이 재시작 후 다시 나타나던 회귀 fix.
    library_dock_visible: bool = True
    layers_dock_visible: bool = True
    record_status_dock_visible: bool = True
    # 에이전트 채팅 패널 (Claude/Qwen 등). 기본 True — 첫 실행 사용자에게 노출.
    agent_panel_visible: bool = True
    # 이미지 생성 패널. 기본 False — 옵트인 기능 (~6.3GB 모델 다운로드 필요).
    image_gen_dock_visible: bool = False
    # 사이드카(.kvedit) 저장 폴더. 빈 문자열 = OS 기본 (%APPDATA%\KStudio\sidecars).
    sidecar_dir: str = ""
    # 파일 → 열기 다이얼로그의 마지막 사용 폴더. 빈 문자열 = 사용자 홈.
    last_open_dir: str = ""
    # 앱 재시작 시 복원할 마지막 모드. "video" | "image" — 잘못된 값이면 "image" 폴백.
    last_mode: str = "image"


@dataclass
class PlayerSettings:
    skip_seconds: int = 1            # ← / →
    skip_medium_seconds: int = 5     # Shift + ← / →
    skip_large_seconds: int = 10     # Ctrl + ← / →


@dataclass
class PlayerHotkeys:
    """영상 플레이어 모드 한정 단축키. 글로벌 핫키와는 별개 차원."""
    frame_back: str = "D"               # 이전 프레임
    frame_forward: str = "F"            # 다음 프레임
    snapshot: str = "Ctrl+Shift+P"      # 현재 프레임 → 이미지 탭
    # 영상 플레이어 프리셋 식별자. 빈 문자열 = 첫 실행 (다이얼로그 노출).
    # 값: "" | "kstudio-default" | "goom-style" | "custom"
    preset_name: str = ""


@dataclass
class McpSettings:
    """KStudio 를 LLM CLI(Claude Code / Gemini CLI / Codex 등)가 제어할 수 있게
    하는 로컬 HTTP 브리지 설정.

    기본 OFF — 켜면 KStudio 가 시작 시 `127.0.0.1:port` 에 작은 HTTP 서버를 띄우고,
    같이 배포되는 stdio MCP 서버(`kstudio_mcp.py`) 가 그 HTTP 를 호출해 LLM 에 도구로
    노출한다. 외부에서 임의 호출되지 않도록 토큰을 항상 요구.
    """
    enabled: bool = False
    # 0 = OS 가 자동 할당. 시작 시 실제 포트가 결정되면 settings 에 저장.
    port: int = 0
    # 빈 문자열이면 시작 시 보안 토큰 자동 생성 (32 hex chars).
    token: str = ""
    # 파괴적 작업(원본 파일 덮어쓰기/삭제) 허용 여부. 기본 OFF.
    # KStudio 의 모든 저장은 충돌 회피(_NNN 자동 번호) 라 실제로는 거의 사용되지 않으나,
    # 미래 도구가 명시적으로 파괴적이라면 이 토글이 켜졌을 때만 허용한다.
    allow_destructive: bool = False


@dataclass
class EditorShortcuts:
    # 도구
    tool_select: str = "V"
    tool_crop: str = "C"
    tool_arrow: str = "A"
    tool_rect: str = "R"
    tool_text: str = "T"
    # 연산
    op_background_removal: str = "Ctrl+Shift+B"
    op_image_scale: str = "Ctrl+Shift+I"
    # 파일
    file_save: str = "Ctrl+S"
    file_save_as: str = "Ctrl+Shift+S"
    file_export_png: str = "Ctrl+E"
    file_open: str = "Ctrl+O"
    # 보기
    view_actual_size: str = "Ctrl+0"
    view_fit: str = "Ctrl+1"


@dataclass
class AgentSettings:
    """Claude Agent in-app 임베드 설정 (Phase 33).

    - model_id: ChatPanel 드롭다운으로 사용자가 선택. 다음 실행 시 복원.
    - whisper_model_size: Phase D 자막 추출용 (tiny/base/small/medium/large-v3).
      large-v3 가 한국어 정확도 가장 높음 (3GB, base 대비 ~5배 느림).
      사용자 요구 (2026-05-15) — "제일 좋은 걸로". 환경설정에서 변경 가능.
    """
    model_id: str = "claude-sonnet-4-6"
    whisper_model_size: str = "large-v3"
    # 추론(ThinkingBlock) 표시 ON/OFF — 노이즈 줄이고 싶을 때 끔.
    # OFF 여도 Claude 는 내부적으로 thinking 수행 (응답 품질 유지) — 화면 표시만 가림.
    show_thinking: bool = True


@dataclass
class AppSettings:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    gif: GifSettings = field(default_factory=GifSettings)
    sound: SoundSettings = field(default_factory=SoundSettings)
    hotkey: HotkeySettings = field(default_factory=HotkeySettings)
    preferences: PreferencesSettings = field(default_factory=PreferencesSettings)
    screenshot: ScreenshotSettings = field(default_factory=ScreenshotSettings)
    annotation: AnnotationSettings = field(default_factory=AnnotationSettings)
    player: PlayerSettings = field(default_factory=PlayerSettings)
    player_hotkeys: PlayerHotkeys = field(default_factory=PlayerHotkeys)
    editor_shortcuts: EditorShortcuts = field(default_factory=EditorShortcuts)
    mcp: McpSettings = field(default_factory=McpSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)


def save(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 자동 백업 — 기존 파일이 있으면 hourly rolling 백업 (settings.json.bak.YYYYMMDD_HH).
    # 회귀 (2026-05-13: 사용자 settings 가 pytest 통해 defaults 로 덮어써짐). 백업이
    # 있으면 영구 손실 대신 직전 시각 데이터로 복구 가능.
    # hourly granularity — 같은 시간대 안에선 한 번만 백업 (디스크 절약 + 복구 시
    # 의미 있는 시각 단위). minutely 면 부팅 직후 N번 저장 시 직전 시각 백업이
    # 의미 없는 동일 데이터로 덮어써짐.
    try:
        if path.exists():
            from datetime import datetime
            stamp = datetime.now().strftime("%Y%m%d_%H")
            bak = path.with_suffix(path.suffix + f".bak.{stamp}")
            if not bak.exists():
                import shutil
                shutil.copy2(path, bak)
                _prune_old_backups(path)
    except OSError:
        pass   # 백업 실패해도 메인 저장은 진행.
    path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


_MAX_BACKUPS = 24   # ~하루치 백업 (시간당 1개). 그 이상은 prune.


def _prune_old_backups(settings_path: Path) -> None:
    """settings.json.bak.YYYYMMDD_HH 백업 중 가장 오래된 것부터 _MAX_BACKUPS 초과분 삭제.

    오래된 백업은 보통 의미 없음 (사용자가 한 달 전 시점으로 되돌리지 않음).
    """
    parent = settings_path.parent
    stem = settings_path.name + ".bak."
    candidates = sorted(
        (p for p in parent.iterdir() if p.name.startswith(stem)),
        key=lambda p: p.name,
    )
    for old in candidates[:-_MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def settings_path() -> Path:
    """앱 어디서든 동일한 settings.json 경로를 얻기 위한 헬퍼."""
    return Path.home() / "AppData" / "Local" / "KStudio" / "settings.json"


def load(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    settings = _from_dict(AppSettings, raw)
    # 마이그레이션: 기존 사용자는 settings.json 이 이미 있는데 preset_name 필드가 없거나
    # 비어 있을 수 있다. 첫 실행 다이얼로그를 안 띄우도록 'custom' 으로 자동 마킹.
    if settings.hotkey.preset_name == "":
        settings.hotkey.preset_name = "custom"
    # 마이그레이션: 첫 릴리스에서 'goom-pot' 으로 박힌 ID 를 'kstudio-default' 로 정정.
    if settings.hotkey.preset_name == "goom-pot":
        settings.hotkey.preset_name = "kstudio-default"
    return settings


def _from_dict(cls, data: dict):
    """dict에서 dataclass 인스턴스를 만들되, 누락 필드는 기본값 사용.

    `from __future__ import annotations` 때문에 `f.type`이 문자열이 되므로
    `get_type_hints(cls)`로 실제 클래스를 확보한다.
    """
    if not is_dataclass(cls):
        return data
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        field_type = hints.get(f.name, f.type)
        if is_dataclass(field_type):
            kwargs[f.name] = _from_dict(field_type, data[f.name])
        else:
            kwargs[f.name] = data[f.name]
    return cls(**kwargs)
