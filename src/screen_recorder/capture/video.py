"""dxcam 기반 비디오 캡처 스레드."""
from __future__ import annotations
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import dxcam  # type: ignore
except ImportError:
    dxcam = None  # type: ignore

from .targets import CaptureTarget, Rect


@dataclass(frozen=True)
class _OutputRect:
    """한 모니터(dxcam output)의 데스크톱 사각형 — 가상 데스크톱 물리좌표 (반열린 구간)."""
    device_idx: int
    output_idx: int
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class CaptureTile:
    """멀티모니터 합성 캡처의 한 조각.

    한 dxcam output 에서 `region`(그 output 의 로컬 좌표) 을 잡아, 합성 버퍼의
    (dst_x, dst_y) 위치에 w×h 크기로 붙인다.
    """
    device_idx: int
    output_idx: int
    region: tuple[int, int, int, int]  # output 로컬 (left, top, right, bottom)
    dst_x: int
    dst_y: int
    w: int
    h: int


def dxcam_output_rects() -> list[_OutputRect]:
    """dxcam 이 본 모든 output 의 데스크톱 사각형 (DXGI 열거 순서, 물리좌표).

    `output.desc.DesktopCoordinates` 는 가상 데스크톱상의 실제 위치라, output_idx 를
    화면 순서로 추측하지 않고 **위치로** 매핑할 수 있다(advisor 지적: QScreen 순서 ≠
    DXGI 순서일 수 있음). dxcam 이 없거나(헤드리스/CI) 접근 실패 시 빈 리스트.
    """
    if dxcam is None:
        return []
    try:
        factory = vars(dxcam)["__factory"]
        rects: list[_OutputRect] = []
        for didx, outputs in enumerate(factory.outputs):
            for oidx, out in enumerate(outputs):
                dc = out.desc.DesktopCoordinates
                rects.append(_OutputRect(
                    didx, oidx, int(dc.left), int(dc.top), int(dc.right), int(dc.bottom)
                ))
        return rects
    except Exception:
        return []


def qscreen_output_rects() -> list[_OutputRect]:
    """QScreen geometry 기반 폴백 — dxcam output 정보를 못 얻을 때(헤드리스/테스트).

    DPR=1.0 환경에서 QScreen.geometry()(논리좌표) == dxcam DesktopCoordinates(물리좌표).
    """
    try:
        from PySide6.QtGui import QGuiApplication
        rects: list[_OutputRect] = []
        for i, s in enumerate(QGuiApplication.screens()):
            g = s.geometry()
            rects.append(_OutputRect(
                0, i, g.x(), g.y(), g.x() + g.width(), g.y() + g.height()
            ))
        return rects
    except Exception:
        return []


def resolve_output_rects() -> list[_OutputRect]:
    """캡처/가드가 함께 쓰는 단일 진실원 — dxcam 우선, 없으면 QScreen 폴백."""
    rects = dxcam_output_rects()
    if rects:
        return rects
    return qscreen_output_rects()


def plan_capture_tiles(rect: Rect, outputs: list[_OutputRect]) -> list[CaptureTile]:
    """캡처 rect 를 각 output 과 교집합내 조각(tile)으로 분해 (순수 함수, 테스트 가능).

    각 output 의 데스크톱 사각형 [left,right) × [top,bottom) 과 rect 를 교집합해,
    겹치는 부분마다 tile 하나를 만든다. output 들은 서로 겹치지 않으므로 tile 들도
    disjoint 하고, 합치면 (모든 부분이 모니터 위에 있을 때) rect 를 정확히 덮는다.
    어떤 output 과도 안 겹치면 빈 리스트(= rect 전체가 화면 밖).
    """
    rx0, ry0 = rect.x, rect.y
    rx1, ry1 = rect.x + rect.w, rect.y + rect.h
    tiles: list[CaptureTile] = []
    for o in outputs:
        ix0 = max(rx0, o.left)
        iy0 = max(ry0, o.top)
        ix1 = min(rx1, o.right)
        iy1 = min(ry1, o.bottom)
        if ix1 > ix0 and iy1 > iy0:
            tiles.append(CaptureTile(
                device_idx=o.device_idx,
                output_idx=o.output_idx,
                region=(ix0 - o.left, iy0 - o.top, ix1 - o.left, iy1 - o.top),
                dst_x=ix0 - rx0,
                dst_y=iy0 - ry0,
                w=ix1 - ix0,
                h=iy1 - iy0,
            ))
    return tiles


def tiles_cover_rect(tiles: list[CaptureTile], rect: Rect) -> bool:
    """tile 들이 rect 전체를 빈틈 없이 덮는지 (tile 들은 disjoint 이므로 면적 합으로 판정).

    빈 리스트(화면 밖)거나 일부만 덮으면(가장자리가 화면 밖) False → 가드가 거부.
    """
    if not tiles:
        return False
    covered = sum(t.w * t.h for t in tiles)
    return covered == rect.w * rect.h


def _pick_output_for_rect(rect: Rect) -> tuple[int, tuple[int, int]]:
    """가상 데스크톱 좌표의 rect 중심이 속한 dxcam output 을 찾아
    (output_idx, (offset_x, offset_y)) 를 반환.

    dxcam 은 output(모니터) 단위로 묶여 있고 region 은 그 output 의 로컬 좌표만
    받기 때문에, 주 모니터가 아닌 곳을 캡처하려면 적절한 output 선택과 오프셋
    보정이 필수다. fallback 은 주 모니터(index 0).
    """
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QPoint
    screens = QGuiApplication.screens()
    if not screens:
        return 0, (0, 0)
    cx = rect.x + rect.w // 2
    cy = rect.y + rect.h // 2
    center = QPoint(cx, cy)
    for i, s in enumerate(screens):
        if s.geometry().contains(center):
            g = s.geometry()
            return i, (g.x(), g.y())
    g = screens[0].geometry()
    return 0, (g.x(), g.y())


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

        # 영역이 두 모니터에 걸치면 output 별 카메라를 합성하는 multi 경로로.
        # 한 모니터 안(또는 output 정보를 모르는 헤드리스/테스트)이면 기존 single 경로.
        tiles = plan_capture_tiles(rect, resolve_output_rects())
        if len(tiles) >= 2:
            self._run_multi(rect, tiles, log)
        else:
            self._run_single(rect, log)

    def _open_tile_cams(self, tiles: list[CaptureTile]) -> list:
        """tile 마다 dxcam 카메라를 만든다 — one-shot 용이라 start() 하지 않는다.

        ⚠ output 마다 start()+video_mode 로 **내부 캡처 스레드를 2개** 띄우면 부하 시
        (예: libx264 인코더가 CPU 점유) 두 스레드가 공유 D3D multithread lock 에서
        deadlock → 화면이 ~수십 초 후 **영구 정지**(frame_count 는 계속 늘지만 내용 동결).
        단일 모니터는 스레드 1개라 같은 부하에도 멀쩡. 그래서 멀티는 내부 스레드 없이
        우리 루프가 output 별로 **순차 one-shot grab** → 같은 시점 DDA 접근이 하나뿐이라
        deadlock 이 구조적으로 불가능. (2026-06-10 재현·검증, Phase 79.)
        """
        cams: list = []
        try:
            for t in tiles:
                cams.append(dxcam.create(
                    device_idx=t.device_idx, output_idx=t.output_idx, output_color="BGRA"
                ))
        except Exception:
            self._close_tile_cams(cams)
            raise
        return cams

    @staticmethod
    def _close_tile_cams(cams: list) -> None:
        for cam in cams:
            try:
                cam.stop()
            except Exception:
                pass
            try:
                cam.release()
            except Exception:
                pass

    def _run_multi(self, rect: Rect, tiles: list[CaptureTile], log) -> None:
        """두 모니터에 걸친 영역을 output 별 **one-shot grab** 으로 한 프레임에 합성한다.

        각 카메라는 start() 없이(내부 캡처 스레드 없이) 우리 루프에서 순차로
        `grab(region, new_frame_only=False)` 한다 — 같은 시점에 DDA 를 건드리는 스레드가
        하나뿐이라 2-스레드 deadlock(부하 시 영구 freeze) 이 구조적으로 불가능
        (`_open_tile_cams` 주석 참고, Phase 79). 매 프레임 zero 버퍼(rect 크기, BGRA) 에
        각 tile 을 dst 위치로 붙인다. grab 이 새 프레임을 못 주면 그 tile 의 직전 프레임을
        재사용한다.

        emit 은 **벽시계 기준** 정확히 fps 만큼 — grab 이 30fps 를 못 따라가도 직전 합성을
        복제해 채운다(출력 프레임 수 = 경과×fps). 이렇게 안 하면 CFR `-r fps` 인코더에
        프레임을 덜 흘려보내 결과 영상이 빨라지고 오디오 싱크가 어긋난다.
        """
        out_w, out_h = rect.w, rect.h
        try:
            cams = self._open_tile_cams(tiles)
        except Exception as e:
            log.error(
                "multi-monitor dxcam create failed (tiles=%s): %s",
                [(t.output_idx, t.region) for t in tiles], e,
            )
            return

        period = 1.0 / max(self.fps, 1)
        next_emit = time.perf_counter()
        frames_emitted = 0
        last_good: list = [None] * len(tiles)  # tile 별 최근 성공 프레임
        try:
            while not self._stop_event.is_set():
                # 녹화 중 영역 이동 — tile 을 다시 계획하고 카메라 세트를 재구성.
                if self._pending_origin is not None:
                    nx, ny = self._pending_origin
                    self._pending_origin = None
                    fw, fh = self._fixed_size or (rect.w, rect.h)
                    new_rect = Rect(nx, ny, fw, fh)
                    new_tiles = plan_capture_tiles(new_rect, resolve_output_rects())
                    if new_tiles:
                        self._close_tile_cams(cams)
                        try:
                            cams = self._open_tile_cams(new_tiles)
                            tiles, rect = new_tiles, new_rect
                            out_w, out_h = rect.w, rect.h
                            last_good = [None] * len(tiles)
                        except Exception as e:
                            log.error("multi-monitor restart failed: %s", e)
                            break

                buf = np.zeros((out_h, out_w, 4), dtype=np.uint8)
                for i, (t, cam) in enumerate(zip(tiles, cams)):
                    # one-shot: 새 프레임 없으면 직전 캐시 반환(new_frame_only=False).
                    frame = cam.grab(region=t.region, new_frame_only=False)
                    if frame is None:
                        frame = last_good[i]
                    else:
                        last_good[i] = frame
                    if frame is None:
                        continue
                    ph = min(frame.shape[0], t.h)
                    pw = min(frame.shape[1], t.w)
                    if ph <= 0 or pw <= 0:
                        continue
                    buf[t.dst_y:t.dst_y + ph, t.dst_x:t.dst_x + pw] = frame[:ph, :pw]

                # 벽시계 기준 fps 만큼 emit(부족분은 직전 합성 복제). grab 이 빠르면 sleep.
                now = time.perf_counter()
                while next_emit <= now:
                    try:
                        self.output_queue.put_nowait(buf)
                        frames_emitted += 1
                    except queue.Full:
                        try:
                            self.output_queue.get_nowait()
                            self.output_queue.put_nowait(buf)
                            frames_emitted += 1
                            self.dropped_count += 1
                        except queue.Empty:
                            pass
                    next_emit += period
                sleep_for = next_emit - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            log.info(
                "multi-monitor capture finished (one-shot): tiles=%d frames_emitted=%d dropped=%d",
                len(tiles), frames_emitted, self.dropped_count,
            )
            self._close_tile_cams(cams)

    def _run_single(self, rect: Rect, log) -> None:
        output_idx, (ox, oy) = _pick_output_for_rect(rect)
        local_rect = Rect(rect.x - ox, rect.y - oy, rect.w, rect.h)
        try:
            self._cam = dxcam.create(output_idx=output_idx, output_color="BGRA")
            # video_mode=True: 화면 변화가 없어도 직전 프레임을 target_fps 로 복제해
            # 끊김 없는 프레임 스트림을 보장한다(정적 화면에서 0프레임 방지). 영상
            # 녹화의 표준 사용법.
            self._cam.start(
                target_fps=self.fps,
                region=local_rect.as_dxcam_region(),
                video_mode=True,
            )
        except Exception as e:
            # 영역이 모니터 경계를 넘는 등으로 dxcam 이 거부하면 여기로 온다. 상위
            # (controller.start_recording) 에서 이미 막지만, 만약을 위한 방어 — 트레이스백
            # 으로 스레드가 조용히 죽는 대신 로그를 남기고 깔끔히 종료한다(인코더는
            # 0프레임 가드로 빈 파일을 폐기한다).
            log.error(
                "dxcam start failed (output_idx=%s region=%s): %s",
                output_idx, local_rect.as_dxcam_region(), e,
            )
            return

        period = 1.0 / max(self.fps, 1)
        next_tick = time.perf_counter()
        frames_emitted = 0

        try:
            while not self._stop_event.is_set():
                # 외부에서 위치 변경 요청이 오면 dxcam 영역 재시작 (크기는 고정).
                # 새 위치가 다른 모니터로 넘어갔다면 dxcam 카메라 자체를 그 output 으로
                # 재생성해야 한다.
                if self._pending_origin is not None:
                    nx, ny = self._pending_origin
                    self._pending_origin = None
                    fw, fh = self._fixed_size or (rect.w, rect.h)
                    new_rect = Rect(nx, ny, fw, fh)
                    new_idx, (nox, noy) = _pick_output_for_rect(new_rect)
                    new_local = Rect(nx - nox, ny - noy, fw, fh)
                    try:
                        self._cam.stop()
                    except Exception as e:
                        log.warning("dxcam stop failed during region update: %s", e)
                    try:
                        if new_idx != output_idx:
                            # 모니터 변경 → 카메라 자체 재생성
                            del self._cam
                            self._cam = dxcam.create(output_idx=new_idx, output_color="BGRA")
                            output_idx, ox, oy = new_idx, nox, noy
                        self._cam.start(
                            target_fps=self.fps,
                            region=new_local.as_dxcam_region(),
                            video_mode=True,
                        )
                    except Exception as e:
                        log.error("dxcam restart failed: %s", e)
                        # 원래 영역으로 복귀
                        try:
                            self._cam.start(
                                target_fps=self.fps,
                                region=local_rect.as_dxcam_region(),
                                video_mode=True,
                            )
                        except Exception:
                            pass
                    rect = new_rect
                    local_rect = new_local

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
                    frames_emitted += 1
                except queue.Full:
                    try:
                        self.output_queue.get_nowait()
                        self.output_queue.put_nowait(frame)
                        frames_emitted += 1
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
            # 진단용: 0프레임으로 빈 mp4 가 나오는 회귀를 다음 보고에서 즉시 추적할 수
            # 있도록 캡처 결과를 남긴다.
            log.info(
                "video capture finished: output_idx=%s region=%s frames_emitted=%d dropped=%d",
                output_idx, local_rect.as_dxcam_region(), frames_emitted, self.dropped_count,
            )
            try:
                self._cam.stop()
            except Exception:
                pass
