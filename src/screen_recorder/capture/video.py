"""dxcam 기반 비디오 캡처 스레드."""
from __future__ import annotations
import queue
import threading
import time
from typing import Optional

try:
    import dxcam  # type: ignore
except ImportError:
    dxcam = None  # type: ignore

from .targets import CaptureTarget


class VideoCaptureThread(threading.Thread):
    def __init__(self, target: CaptureTarget, fps: int, output_queue: queue.Queue):
        super().__init__(daemon=True, name="VideoCapture")
        self.target = target
        self.fps = fps
        self.output_queue = output_queue
        self._stop_event = threading.Event()
        self.dropped_count = 0
        self._cam = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        rect = self.target.current_rect()
        if rect is None:
            return
        self._cam = dxcam.create(output_color="BGRA")
        self._cam.start(target_fps=self.fps, region=rect.as_dxcam_region())

        period = 1.0 / max(self.fps, 1)
        next_tick = time.perf_counter()

        try:
            while not self._stop_event.is_set():
                rect_now = self.target.current_rect()
                if rect_now is None:
                    time.sleep(period)
                    continue

                frame = self._cam.get_latest_frame()
                if frame is None:
                    time.sleep(period / 2)
                    continue

                try:
                    self.output_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self.output_queue.get_nowait()
                        self.output_queue.put_nowait(frame)
                        self.dropped_count += 1
                    except queue.Empty:
                        pass

                next_tick += period
                sleep_for = next_tick - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_tick = time.perf_counter()
        finally:
            try:
                self._cam.stop()
            except Exception:
                pass
