import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from screen_recorder.capture.audio import AudioCaptureThread


def test_audio_writes_chunks_to_raw_file(tmp_path):
    fake_chunk = b"\x00\x00" * 1024
    fake_stream = MagicMock()
    fake_stream.read.return_value = fake_chunk
    # 루프백 가용 프레임 폴링: 항상 한 chunk 이상 있다고 보고해 read 경로를 타게 한다.
    fake_stream.get_read_available.return_value = 4096

    fake_pa = MagicMock()
    fake_pa.get_default_wasapi_loopback.return_value = {
        "index": 0,
        "maxInputChannels": 2,
        "defaultSampleRate": 48000.0,
    }
    fake_pa.open.return_value = fake_stream

    out = tmp_path / "audio.raw"
    with patch("screen_recorder.capture.audio.pyaudio") as pa_mod:
        pa_mod.PyAudio.return_value = fake_pa
        pa_mod.paInt16 = 8

        t = AudioCaptureThread(output_path=out)
        t.start()
        time.sleep(0.1)
        t.stop()
        t.join(timeout=1.0)

    assert out.exists()
    assert out.stat().st_size > 0
    assert t.sample_rate == 48000
    assert t.channels == 2


def test_audio_idle_loopback_does_not_block_stop(tmp_path):
    """조용한 화면: 루프백이 데이터를 안 줄 때(get_read_available=0) stream.read 에
    묶이지 않고 stop 에 즉시 반응해야 한다. 0바이트로 끝나 '오디오 없음'이 감지된다."""
    fake_stream = MagicMock()
    fake_stream.get_read_available.return_value = 0  # 항상 idle

    fake_pa = MagicMock()
    fake_pa.get_default_wasapi_loopback.return_value = {
        "index": 0,
        "maxInputChannels": 2,
        "defaultSampleRate": 48000.0,
    }
    fake_pa.open.return_value = fake_stream

    out = tmp_path / "audio.raw"
    with patch("screen_recorder.capture.audio.pyaudio") as pa_mod:
        pa_mod.PyAudio.return_value = fake_pa
        pa_mod.paInt16 = 8

        t = AudioCaptureThread(output_path=out)
        t.start()
        time.sleep(0.1)
        t.stop()
        t.join(timeout=0.5)  # 짧은 타임아웃 — 블록되면 살아있어서 실패

    assert not t.is_alive()          # stop 에 즉시 반응
    assert t.bytes_written == 0      # 데이터 없음
    fake_stream.read.assert_not_called()  # idle 일 땐 read 시도 안 함


def test_audio_no_loopback_device_records_silence(tmp_path):
    fake_pa = MagicMock()
    fake_pa.get_default_wasapi_loopback.side_effect = OSError("no device")

    out = tmp_path / "audio.raw"
    with patch("screen_recorder.capture.audio.pyaudio") as pa_mod:
        pa_mod.PyAudio.return_value = fake_pa
        pa_mod.paInt16 = 8

        t = AudioCaptureThread(output_path=out)
        t.start()
        time.sleep(0.1)
        t.stop()
        t.join(timeout=1.0)

    assert t.error is not None
