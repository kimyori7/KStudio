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
    # 48000Hz * 2ch * 2byte = 192000 B/s. 0.5s 부재 가드를 넘기려면 충분히 커야 한다.
    audio_raw.write_bytes(b"\x00" * 200_000)
    out_path = tmp_path / "out.mp4"

    proc_video = MagicMock(); proc_video.stdin.closed = False
    proc_video.poll.return_value = None; proc_video.wait.return_value = 0; proc_video.returncode = 0
    proc_audio = MagicMock(); proc_audio.wait.return_value = 0; proc_audio.returncode = 0
    proc_mux = MagicMock(); proc_mux.wait.return_value = 0; proc_mux.returncode = 0

    # 실제 녹화는 항상 영상 프레임이 있다 — 0프레임이면 인코더가 캡처 실패로 보고
    # mux 전에 중단하므로, mux 경로를 검증하려면 프레임을 최소 1개 넣어야 한다.
    q = queue.Queue()
    q.put(np.zeros((10, 10, 4), dtype=np.uint8).tobytes())
    q.put(None)

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


def test_encoder_skips_mux_when_audio_essentially_absent(tmp_path):
    """조용한 화면 녹화: raw 가 WASAPI 한 chunk(4096B≈21ms) 만 있으면 mux 하지
    않고 영상만 살린다. -shortest 로 16s 영상이 21ms 로 잘리는 사고 방지 +
    사용자에겐 'mux 실패'가 아니라 '오디오 없음'을 알린다."""
    audio_raw = tmp_path / "out.audio.raw"
    audio_raw.write_bytes(b"\x00" * 4096)  # 1 chunk = 21ms @ 48k/2ch
    out_path = tmp_path / "out.mp4"

    proc_video = MagicMock(); proc_video.stdin.closed = False
    proc_video.poll.return_value = None; proc_video.wait.return_value = 0; proc_video.returncode = 0

    # 영상 프레임 몇 개 — video_dur > 0, raw 의 audio_dur(0.021s) 보다 훨씬 큼
    q = queue.Queue()
    for _ in range(5):
        q.put(np.zeros((10, 10, 4), dtype=np.uint8).tobytes())
    q.put(None)

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

    def fake_popen(argv, *args, **kwargs):
        try:
            Path(argv[-1]).write_bytes(b"\x00" * 16)
        except Exception:
            pass
        return proc_video

    with patch("subprocess.Popen", side_effect=fake_popen) as popen:
        enc.start()
        enc.join(timeout=2.0)
        # 오직 영상 인코드 1회만 — audio encode/mux 단계 진입 안 함
        assert popen.call_count == 1
    # 오디오 부재는 '실패'가 아니라 정상 결과 → error 가 아니라 notice 로 알린다(팝업 X).
    assert enc.error is None
    assert enc.notice is not None
    assert "오디오" in enc.notice
    assert "mux failed" not in enc.notice


def test_encoder_discards_streamless_output_when_no_frames(tmp_path):
    """프레임이 0개면 ffmpeg 가 스트림 없는 깡통 mp4(헤더만, ~수백 byte)를 남긴다 —
    사용자에겐 '저장 안 됨'으로 보인다. 깡통 파일을 지우고 명확한 캡처 실패 에러를
    남겨야 한다(2026-06-09: 영역이 두 모니터에 걸쳐 캡처 스레드가 즉사한 경우)."""
    out_path = tmp_path / "out.mp4"
    proc = MagicMock(); proc.stdin.closed = False
    proc.poll.return_value = None; proc.wait.return_value = 0; proc.returncode = 0

    q = queue.Queue(); q.put(None)  # 프레임 0개

    enc = VideoEncoder(
        video_settings=VideoSettings(),
        sound_settings=SoundSettings(system_audio_enabled=False),
        width=10, height=10,
        ffmpeg_path=Path("ffmpeg"),
        output_path=out_path,
        frame_queue=q,
    )

    def fake_popen(argv, *args, **kwargs):
        try:
            Path(argv[-1]).write_bytes(b"\x00" * 262)  # 스트림 없는 깡통 mp4 흉내
        except Exception:
            pass
        return proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        enc.start()
        enc.join(timeout=2.0)

    assert not out_path.exists(), "깡통 mp4 를 폐기해야 한다"
    assert enc.error is not None
    assert ("프레임" in enc.error) or ("캡처" in enc.error)


def test_encoder_no_frames_reports_capture_failure_not_audio(tmp_path):
    """오디오가 켜진 상태에서 0프레임이면, 잘못된 '오디오 없음'이 아니라 '화면 캡처
    실패'를 알려야 한다 (사용자가 실제로 본 혼동). video.tmp 도 정리한다."""
    audio_raw = tmp_path / "out.audio.raw"
    audio_raw.write_bytes(b"")  # 조용한 녹화 → 오디오도 없음
    out_path = tmp_path / "out.mp4"

    proc = MagicMock(); proc.stdin.closed = False
    proc.poll.return_value = None; proc.wait.return_value = 0; proc.returncode = 0

    q = queue.Queue(); q.put(None)  # 0프레임

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

    def fake_popen(argv, *args, **kwargs):
        try:
            Path(argv[-1]).write_bytes(b"\x00" * 262)
        except Exception:
            pass
        return proc

    with patch("subprocess.Popen", side_effect=fake_popen) as popen:
        enc.start()
        enc.join(timeout=2.0)

    assert popen.call_count == 1  # 영상 인코드만; audio/mux 단계 진입 안 함
    assert not out_path.exists()
    assert not out_path.with_suffix(".video.tmp.mp4").exists()
    assert enc.error is not None
    assert ("프레임" in enc.error) or ("캡처" in enc.error)
    assert "오디오" not in enc.error  # '오디오 없음' 메시지가 아님


def test_encoder_joins_audio_thread_before_mux(tmp_path):
    """인코더는 raw 를 읽기 전에 캡처 스레드를 join 해야 한다 — 안 그러면
    버퍼에 4096B 가 있어도 디스크엔 아직 0B 인 파일을 읽어 '오디오 0바이트'
    로 오인한다 (캡처가 stop 후 잠깐 더 도는 경우의 레이스)."""
    audio_raw = tmp_path / "out.audio.raw"
    audio_raw.write_bytes(b"\x00" * 200_000)
    out_path = tmp_path / "out.mp4"

    proc = MagicMock(); proc.stdin.closed = False
    proc.poll.return_value = None; proc.wait.return_value = 0; proc.returncode = 0

    # 영상 프레임 1개 이상 — 0프레임이면 캡처 실패로 보고 mux 전에 중단한다.
    q = queue.Queue()
    q.put(np.zeros((10, 10, 4), dtype=np.uint8).tobytes())
    q.put(None)
    fake_audio_thread = MagicMock()

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
        audio_thread=fake_audio_thread,
    )

    def fake_popen(argv, *args, **kwargs):
        try:
            Path(argv[-1]).write_bytes(b"\x00" * 16)
        except Exception:
            pass
        return proc

    with patch("subprocess.Popen", side_effect=fake_popen):
        enc.start()
        enc.join(timeout=2.0)

    fake_audio_thread.join.assert_called()
