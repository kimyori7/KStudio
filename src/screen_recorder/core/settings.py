"""앱 설정 모델 + JSON 저장/로드."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
import json
from pathlib import Path
from typing import get_type_hints


@dataclass
class GeneralSettings:
    output_dir: str = ""  # 빈 문자열이면 ~/Videos/KStudio
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
    toggle_record: str = "Ctrl+Shift+T"
    screenshot_region: str = "Ctrl+Shift+R"
    screenshot_full: str = ""  # 빈 문자열 = 미할당


@dataclass
class ScreenshotSettings:
    save_dir: str = ""  # 빈 문자열이면 ~/Pictures/KStudio
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


@dataclass
class PreferencesSettings:
    autostart: bool = False
    minimize_to_tray: bool = True
    use_mini_control: bool = True
    language: str = "ko"


@dataclass
class PlayerSettings:
    skip_seconds: int = 1            # ← / →
    skip_medium_seconds: int = 5     # Shift + ← / →
    skip_large_seconds: int = 10     # Ctrl + ← / →


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


def save(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _from_dict(AppSettings, raw)


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
