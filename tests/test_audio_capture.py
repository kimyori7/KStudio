import threading
from unittest.mock import MagicMock, patch

import pytest

from screen_recorder.capture.audio import AudioCaptureThread


def test_audio_writes_chunks_to_raw_file(tmp_path):
    fake_chunk = b"\x00\x00" * 1024
    fake_stream = MagicMock()
    read_called = threading.Event()

    def read(*args, **kwargs):
        read_called.set()
        return fake_chunk

    fake_stream.read.side_effect = read
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
        try:
            assert t.ready.wait(timeout=3.0)
            assert read_called.wait(timeout=3.0)
        finally:
            t.stop()
            t.join(timeout=3.0)

    assert not t.is_alive()
    assert out.exists()
    assert out.stat().st_size > 0
    assert t.sample_rate == 48000
    assert t.channels == 2


def test_audio_idle_loopback_does_not_block_stop(tmp_path):
    """조용한 화면: 루프백이 데이터를 안 줄 때(get_read_available=0) stream.read 에
    묶이지 않고 stop 에 즉시 반응해야 한다. 0바이트로 끝나 '오디오 없음'이 감지된다."""
    fake_stream = MagicMock()
    polled = threading.Event()

    def get_read_available():
        polled.set()
        return 0

    fake_stream.get_read_available.side_effect = get_read_available

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
        try:
            assert t.ready.wait(timeout=3.0)
            assert polled.wait(timeout=3.0)
        finally:
            t.stop()
            t.join(timeout=0.5)  # 짧은 타임아웃 — 블록되면 살아있어서 실패

    assert not t.is_alive()          # stop 에 즉시 반응
    assert t.bytes_written == 0      # 데이터 없음
    fake_stream.read.assert_not_called()  # idle 일 땐 read 시도 안 함


@pytest.mark.parametrize("failure", ["import", "init", "device", "format", "stream", "file"])
def test_audio_start_failure_sets_ready(tmp_path, failure):
    pa_mod = MagicMock()
    fake_pa = MagicMock()
    pa_mod.PyAudio.return_value = fake_pa
    fake_pa.get_default_wasapi_loopback.return_value = {
        "index": 0,
        "maxInputChannels": 2,
        "defaultSampleRate": 48000,
    }
    out = tmp_path / "audio.raw"
    if failure == "import":
        pa_mod = None
    elif failure == "init":
        pa_mod.PyAudio.side_effect = OSError("init failed")
    elif failure == "device":
        fake_pa.get_default_wasapi_loopback.side_effect = OSError("no device")
    elif failure == "format":
        fake_pa.get_default_wasapi_loopback.return_value["defaultSampleRate"] = 0
    elif failure == "stream":
        fake_pa.open.side_effect = OSError("open failed")
    else:
        out = tmp_path / "missing" / "audio.raw"

    with patch("screen_recorder.capture.audio.pyaudio", pa_mod):
        t = AudioCaptureThread(output_path=out)
        t.start()
        try:
            assert t.ready.wait(timeout=1.0)
            assert t.error
            assert t.sample_rate == t.channels == 0
        finally:
            t.stop()
            t.join(timeout=1.0)

    assert not t.is_alive()
