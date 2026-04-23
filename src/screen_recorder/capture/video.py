"""dxcam 기반 비디오 캡처 스레드."""
from __future__ import annotations
import logging
import queue
import threading
import time
from typing import Optional

try:
    import dxcam  # type: ignore
except ImportError:
    dxcam = None  # type: ignore

from .targets import CaptureTarget, Rect


class VideoCaptureThread(threading.Thread):
    def __init__(self, target: CaptureTarget, fps: int, output_queue: queue.Queue):
        super().__init__(daemon=True, name="VideoCapture")
        self.target = target
        self.fps = fps
        self.output_queue = output_queue
        self._stop_event = threading.Event()
        self.dropped_count = 0
        self._cam = None
        # 캡처 시작 후 외부에서 영역만 갱신할 수 있도록 (위치 이동 지원).
        # 크기는 인코더 입력 해상도와 일치해야 하므로 변경하지 않음.
        self._pending_origin: Optional[tuple[int, int]] = None
        self._fixed_size: Optional[tuple[int, int]] = None

    def stop(self) -> None:
        self._stop_event.set()

    def update_origin(self, x: int, y: int) -> None:
        """외부에서 캡처 영역의 좌상단을 갱신 요청. 다음 루프에서 dxcam 재시작."""
        self._pending_origin = (int(x), int(y))

    def run(self) -> None:
        log = logging.getLogger(__name__)
        rect = self.target.current_rect()
        if rect is None:
            return
        self._fixed_size = (rect.w, rect.h)
        self._cam = dxcam.create(output_color="BGRA")
        self._cam.start(target_fps=self.fps, region=rect.as_dxcam_region())

        period = 1.0 / max(self.fps, 1)
        next_tick = time.perf_counter()

        try:
            while not self._stop_event.is_set():
                # 외부에서 위치 변경 요청이 오면 dxcam 영역 재시작 (크기는 고정)
                if self._pending_origin is not None:
                    nx, ny = self._pending_origin
                    self._pending_origin = None
                    fw, fh = self._fixed_size or (rect.w, rect.h)
                    new_rect = Rect(nx, ny, fw, fh)
                    try:
                        self._cam.stop()
                    except Exception as e:
                        log.warning("dxcam stop failed during region update: %s", e)
                    try:
                        self._cam.start(target_fps=self.fps, region=new_rect.as_dxcam_region())
                    except Exception as e:
                        log.error("dxcam restart failed: %s", e)
                        # 다시 원래 영역으로 복귀
                        try:
                            self._cam.start(target_fps=self.fps, region=rect.as_dxcam_region())
                        except Exception:
                            pass
                    rect = new_rect

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
