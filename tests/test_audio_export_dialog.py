"""AudioExportSettingsDialog — 폼 ↔ AudioExportSettings 양방향."""
from __future__ import annotations

import pytest

from screen_recorder.encode.audio_export import AudioExportSettings
from screen_recorder.ui.audio_export_dialog import AudioExportSettingsDialog


@pytest.fixture
def dlg(qtbot):
    d = AudioExportSettingsDialog()
    qtbot.addWidget(d)
    return d


def test_defaults_match_settings_dataclass(dlg):
    s = dlg.current_settings()
    assert s.format == "mp3"
    assert s.channels == 2
    assert s.sample_rate == 44100
    assert s.mp3_bitrate == 192


def test_select_wav_disables_bitrate(dlg):
    """WAV 선택 시 MP3 비트레이트 콤보 비활성 (의미 없음)."""
    dlg.wav_radio.setChecked(True)
    assert not dlg.bitrate_combo.isEnabled()


def test_select_mp3_enables_bitrate(dlg):
    dlg.wav_radio.setChecked(True)   # 일단 OFF
    dlg.mp3_radio.setChecked(True)   # 다시 ON
    assert dlg.bitrate_combo.isEnabled()


def test_select_mono_reflects_in_settings(dlg):
    dlg.mono_radio.setChecked(True)
    assert dlg.current_settings().channels == 1


def test_select_stereo_reflects_in_settings(dlg):
    dlg.mono_radio.setChecked(True)
    dlg.stereo_radio.setChecked(True)
    assert dlg.current_settings().channels == 2


def test_change_sample_rate(dlg):
    dlg.sample_rate_combo.setCurrentText("48000 Hz")
    assert dlg.current_settings().sample_rate == 48000


def test_change_bitrate(dlg):
    dlg.bitrate_combo.setCurrentText("320 kbps")
    assert dlg.current_settings().mp3_bitrate == 320


def test_wav_settings_ignore_bitrate_field(dlg):
    """WAV 선택 + 비트레이트 변경해도 settings 는 WAV 그대로 (validation 통과)."""
    dlg.wav_radio.setChecked(True)
    s = dlg.current_settings()
    assert s.format == "wav"
    # mp3_bitrate 는 기본값 유지 (사용자 변경 안 했으므로).
    assert s.mp3_bitrate == 192


def test_filename_extension_matches_format(dlg):
    """suggested_filename(base) — 형식에 따라 .mp3 / .wav 자동."""
    assert dlg.suggested_extension() == ".mp3"
    dlg.wav_radio.setChecked(True)
    assert dlg.suggested_extension() == ".wav"
