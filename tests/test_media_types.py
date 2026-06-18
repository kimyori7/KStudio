from pathlib import Path

from screen_recorder.core.media_types import AUDIO_EXTS, is_audio


def test_audio_exts_contains_common_formats():
    for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
        assert ext in AUDIO_EXTS


def test_is_audio_is_case_insensitive():
    assert is_audio(Path("song.MP3")) is True
    assert is_audio(Path("clip.mp4")) is False
    assert is_audio("voice.wav") is True
