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
    # 수정하면 "custom" 으로 자동 전환. 값: "" | "windows-standard" | "goom-pot" | "custom"
    preset_name: str = ""


@dataclass
class ScreenshotSettings:
    save_dir: str = ""  # 빈 문자열이면 ~/KStudio/Image
    filename_pattern: str = "screenshot_{date}_{time}"
    format: str = "png"
    magnifier_enabled: bool = True
    # 뷰어 창 위치/크기 (-1이면 미설정)
    viewer_x: int = -1
    viewer_y: int = -1
    viewer_w: int = -1
    viewer_h: int = -1


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


@dataclass
class PlayerSettings:
    skip_seconds: int = 1            # ← / →
    skip_medium_seconds: int = 5     # Shift + ← / →
    skip_large_seconds: int = 10     # Ctrl + ← / →


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
    # 파일
    file_save: str = "Ctrl+S"
    file_save_as: str = "Ctrl+Shift+S"
    file_export_png: str = "Ctrl+E"
    file_open: str = "Ctrl+O"
    # 보기
    view_actual_size: str = "Ctrl+0"
    view_fit: str = "Ctrl+1"


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
    editor_shortcuts: EditorShortcuts = field(default_factory=EditorShortcuts)


def save(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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
