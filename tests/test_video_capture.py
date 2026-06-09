import queue
import time
from unittest.mock import MagicMock, patch

import numpy as np

from screen_recorder.capture.video import (
    VideoCaptureThread,
    _OutputRect,
    plan_capture_tiles,
    tiles_cover_rect,
)
from screen_recorder.capture.targets import RegionTarget, Rect


# 사용자 환경: 2560x1440 모니터 2개 좌우 배치.
_MON_A = _OutputRect(0, 0, 0, 0, 2560, 1440)
_MON_B = _OutputRect(0, 1, 2560, 0, 5120, 1440)
_TWO = [_MON_A, _MON_B]


# ----- plan_capture_tiles (순수 함수) -----

def test_plan_single_monitor_one_tile_full_coverage():
    rect = Rect(100, 100, 1200, 800)  # 모니터 A 안
    tiles = plan_capture_tiles(rect, _TWO)
    assert len(tiles) == 1
    t = tiles[0]
    assert t.output_idx == 0
    assert t.region == (100, 100, 1300, 900)  # output 로컬 == 데스크톱 (A 는 origin 0)
    assert (t.dst_x, t.dst_y, t.w, t.h) == (0, 0, 1200, 800)
    assert tiles_cover_rect(tiles, rect)


def test_plan_second_monitor_local_region_offset():
    rect = Rect(2700, 100, 1200, 800)  # 모니터 B 안
    tiles = plan_capture_tiles(rect, _TWO)
    assert len(tiles) == 1
    t = tiles[0]
    assert t.output_idx == 1
    assert t.region == (140, 100, 1340, 900)  # B origin(2560) 만큼 빠짐
    assert (t.dst_x, t.dst_y, t.w, t.h) == (0, 0, 1200, 800)
    assert tiles_cover_rect(tiles, rect)


def test_plan_spanning_two_monitors_tiles_and_seam():
    rect = Rect(1481, 200, 3638, 400)  # 경계(2560) 를 넘김
    tiles = plan_capture_tiles(rect, _TWO)
    assert len(tiles) == 2
    a, b = sorted(tiles, key=lambda t: t.dst_x)
    # 왼쪽 조각: 모니터 A 의 1481~2560
    assert a.output_idx == 0
    assert a.region == (1481, 200, 2560, 600)
    assert (a.dst_x, a.dst_y, a.w, a.h) == (0, 0, 1079, 400)
    # 오른쪽 조각: 모니터 B 의 0~2559 → 합성 버퍼 1079 부터
    assert b.output_idx == 1
    assert b.region == (0, 200, 2559, 600)
    assert (b.dst_x, b.dst_y, b.w, b.h) == (1079, 0, 2559, 400)
    # 이음매: 왼쪽 끝(dst 1079) == 오른쪽 시작 → 빈틈/겹침 없음
    assert a.dst_x + a.w == b.dst_x
    assert tiles_cover_rect(tiles, rect)


def test_plan_offscreen_returns_empty():
    rect = Rect(6000, 100, 200, 200)  # 어떤 모니터와도 안 겹침
    tiles = plan_capture_tiles(rect, _TWO)
    assert tiles == []
    assert not tiles_cover_rect(tiles, rect)


def test_plan_partly_offscreen_not_fully_covered():
    rect = Rect(4800, 100, 800, 800)  # 오른쪽이 5120 너머로 나감
    tiles = plan_capture_tiles(rect, _TWO)
    assert len(tiles) == 1  # B 와만 부분 교집합
    assert not tiles_cover_rect(tiles, rect)  # 가드가 거부해야 함


def test_plan_no_outputs_returns_empty():
    assert plan_capture_tiles(Rect(0, 0, 100, 100), []) == []


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


def test_capture_uses_video_mode_for_constant_fps():
    """dxcam 은 video_mode=True 로 시작해야 한다 — 화면 변화가 없어도 직전 프레임을
    target_fps 로 복제해 끊김 없는 프레임 스트림을 보장한다. (기본 video_mode=False
    면 정적 화면에서 get_latest_frame 이 블록 → 0프레임.) 영역 갱신 재시작 포함 모든
    start 호출에 적용돼야 한다."""
    fake_frame = np.zeros((10, 10, 4), dtype=np.uint8)
    fake_cam = MagicMock()
    fake_cam.get_latest_frame.return_value = fake_frame

    q = queue.Queue(maxsize=10)
    target = RegionTarget(Rect(0, 0, 10, 10))

    with patch("screen_recorder.capture.video.dxcam") as dx_mod:
        dx_mod.create.return_value = fake_cam
        t = VideoCaptureThread(target=target, fps=30, output_queue=q)
        t.start()
        time.sleep(0.1)
        t.stop()
        t.join(timeout=1.0)

    assert fake_cam.start.called
    for call in fake_cam.start.call_args_list:
        assert call.kwargs.get("video_mode") is True


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
