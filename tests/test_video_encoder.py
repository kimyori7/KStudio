import queue
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from screen_recorder.core.settings import VideoSettings, SoundSettings
from screen_recorder.encode.video_encoder import VideoEncoder


def test_encoder_writes_frames_to_ffmpeg_stdin(tmp_path):
    proc = MagicMock()
    proc.stdin.closed = False
    proc.poll.return_value = None
    proc.wait.return_value = 0

    q = queue.Queue()
    q.put(np.zeros((100, 100, 4), dtype=np.uint8).tobytes())
    q.put(np.zeros((100, 100, 4), dtype=np.uint8).tobytes())
    q.put(None)

    enc = VideoEncoder(
        video_settings=VideoSettings(),
        sound_settings=SoundSettings(system_audio_enabled=False),
        width=100, height=100,
        ffmpeg_path=Path("ffmpeg"),
        output_path=tmp_path / "out.mp4",
        frame_queue=q,
    )

    with patch("subprocess.Popen", return_value=proc) as popen:
        enc.start()
        enc.join(timeout=2.0)
        assert popen.call_count == 1
        assert proc.stdin.write.call_count >= 2
        proc.stdin.close.assert_called_once()


def test_encoder_runs_mux_when_audio_present(tmp_path):
    audio_raw = tmp_path / "audio.raw"
    audio_raw.write_bytes(b"\x00" * 1024)
    out_path = tmp_path / "out.mp4"

    proc_video = MagicMock(); proc_video.stdin.closed = False
    proc_video.poll.return_value = None; proc_video.wait.return_value = 0; proc_video.returncode = 0
    proc_audio = MagicMock(); proc_audio.wait.return_value = 0; proc_audio.returncode = 0
    proc_mux = MagicMock(); proc_mux.wait.return_value = 0; proc_mux.returncode = 0

    q = queue.Queue(); q.put(None)

    enc = VideoEncoder(
        video_settings=VideoSettings(),
        sound_settings=SoundSettings(),
        width=10, height=10,
        ffmpeg_path=Path("ffmpeg"),
        output_path=out_path,
        frame_queue=q,
        audio_raw_path=audio_raw,
        audio_sample_rate=48000,
        audio_channels=2,
    )

    procs = iter([proc_video, proc_audio, proc_mux])

    def fake_popen(argv, *args, **kwargs):
        # 각 ffmpeg 호출이 출력 파일을 만든 것처럼 시뮬레이션
        # (VideoEncoder가 audio mux 단계에서 파일 존재/크기를 확인함)
        try:
            output = argv[-1]
            Path(output).write_bytes(b"\x00" * 16)
        except Exception:
            pass
        return next(procs)

    with patch("subprocess.Popen", side_effect=fake_popen) as popen:
        enc.start()
        enc.join(timeout=2.0)
        assert popen.call_count == 3
