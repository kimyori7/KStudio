"""미디어 확장자 단일 정의 — 라우팅/드롭/파일필터가 공통 참조.

오디오 파일을 영상 편집과 같은 탭 영역에서 자르기(트림/컷) 위해, 어느 확장자가
오디오인지 한 곳에서 정한다. 흩어진 하드코딩(main_window.VIDEO_EXTS 등) 옆에 둔다.
"""
from __future__ import annotations
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def is_audio(path) -> bool:
    """경로의 확장자가 오디오면 True (대소문자 무시)."""
    return Path(str(path)).suffix.lower() in AUDIO_EXTS
