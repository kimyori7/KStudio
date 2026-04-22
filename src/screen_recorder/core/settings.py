"""앱 설정 모델 + JSON 저장/로드."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, fields, is_dataclass
import json
from pathlib import Path
from typing import get_type_hints


@dataclass
class GeneralSettings:
    output_dir: str = ""  # 빈 문자열이면 ~/Videos/ScreenRecorder
    filename_pattern: str = "rec_{date}_{time}"
    mode: str = "video"  # "video" | "gif"


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
    toggle_record: str = "F9"


@dataclass
class PreferencesSettings:
    autostart: bool = False
    minimize_to_tray: bool = True
    use_mini_control: bool = True
    language: str = "ko"


@dataclass
class AppSettings:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    gif: GifSettings = field(default_factory=GifSettings)
    sound: SoundSettings = field(default_factory=SoundSettings)
    hotkey: HotkeySettings = field(default_factory=HotkeySettings)
    preferences: PreferencesSettings = field(default_factory=PreferencesSettings)


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
