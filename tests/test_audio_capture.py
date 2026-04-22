import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from screen_recorder.capture.audio import AudioCaptureThread


def test_audio_writes_chunks_to_raw_file(tmp_path):
    fake_chunk = b"\x00\x00" * 1024
    fake_stream = MagicMock()
    fake_stream.read.return_value = fake_chunk

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
