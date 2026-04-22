import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from screen_recorder.core.settings import GifSettings
from screen_recorder.encode.gif_encoder import GifEncoder


def test_gif_encoder_runs_three_ffmpeg_processes(tmp_path):
    proc1 = MagicMock(); proc1.stdin.closed = False; proc1.poll.return_value = None; proc1.wait.return_value = 0
    proc2 = MagicMock(); proc2.wait.return_value = 0
    proc3 = MagicMock(); proc3.wait.return_value = 0

    q = queue.Queue()
    q.put(np.zeros((10, 10, 4), dtype=np.uint8).tobytes())
    q.put(None)

    enc = GifEncoder(
        gif_settings=GifSettings(),
        width=10, height=10,
        ffmpeg_path=Path("ffmpeg"),
        output_path=tmp_path / "out.gif",
        frame_queue=q,
    )
    with patch("subprocess.Popen", side_effect=[proc1, proc2, proc3]) as popen:
        enc.start()
        enc.join(timeout=2.0)
        assert popen.call_count == 3
