import queue
import time
from unittest.mock import MagicMock, patch

import numpy as np

from screen_recorder.capture.video import VideoCaptureThread
from screen_recorder.capture.targets import RegionTarget, Rect


def test_capture_pushes_frames_to_queue():
    fake_frame = np.zeros((100, 200, 4), dtype=np.uint8)  # BGRA
    fake_cam = MagicMock()
    fake_cam.get_latest_frame.return_value = fake_frame

    q = queue.Queue(maxsize=10)
    target = RegionTarget(Rect(0, 0, 200, 100))

    with patch("screen_recorder.capture.video.dxcam") as dx_mod:
        dx_mod.create.return_value = fake_cam
        t = VideoCaptureThread(target=target, fps=30, output_queue=q)
        t.start()
        time.sleep(0.15)
        t.stop()
        t.join(timeout=1.0)

    assert not q.empty()
    frame = q.get()
    assert frame.shape == (100, 200, 4)


def test_capture_drops_oldest_when_queue_full():
    fake_frame = np.zeros((10, 10, 4), dtype=np.uint8)
    fake_cam = MagicMock()
    fake_cam.get_latest_frame.return_value = fake_frame

    q = queue.Queue(maxsize=2)
    target = RegionTarget(Rect(0, 0, 10, 10))

    with patch("screen_recorder.capture.video.dxcam") as dx_mod:
        dx_mod.create.return_value = fake_cam
        t = VideoCaptureThread(target=target, fps=120, output_queue=q)
        t.start()
        time.sleep(0.2)
        t.stop()
        t.join(timeout=1.0)

    assert q.qsize() <= 2
    assert t.dropped_count > 0
