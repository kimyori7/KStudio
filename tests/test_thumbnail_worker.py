"""ThumbnailService — QRunnable 디스패치 + 캐시 hit 즉시 시그널."""
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage

from screen_recorder.services.thumbnail_extractor import ThumbnailExtractor
from screen_recorder.services.thumbnail_worker import ThumbnailRequest, ThumbnailService


def test_service_returns_cached_immediately(qtbot):
    extractor = ThumbnailExtractor()
    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    extractor._cache[("a.mp4", 1000)] = img

    svc = ThumbnailService(extractor)
    received = []
    svc.thumbnail_ready.connect(lambda sid, im: received.append((sid, im)))
    svc.request(ThumbnailRequest(segment_id="seg1", src="a.mp4", ms=1000))
    assert len(received) == 1
    assert received[0][0] == "seg1"


def test_service_dispatches_to_threadpool_on_miss(qtbot, monkeypatch):
    extractor = ThumbnailExtractor()
    svc = ThumbnailService(extractor)

    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF334455)
    monkeypatch.setattr(extractor, "extract_sync", lambda src, ms: img)

    received = []
    svc.thumbnail_ready.connect(lambda sid, im: received.append((sid, im)))
    svc.request(ThumbnailRequest(segment_id="seg2", src="b.mp4", ms=0))

    QThreadPool.globalInstance().waitForDone(2000)
    qtbot.wait(50)
    assert len(received) == 1
    assert received[0][0] == "seg2"


def test_service_dedupes_pending_requests(qtbot, monkeypatch):
    """같은 segment_id 가 pending 일 동안 추가 요청은 무시 (worker 1회만 실행)."""
    extractor = ThumbnailExtractor()
    svc = ThumbnailService(extractor)

    call_count = [0]

    def fake_extract(src, ms):
        call_count[0] += 1
        img = QImage(96, 54, QImage.Format_ARGB32)
        img.fill(0xFF000000)
        return img

    monkeypatch.setattr(extractor, "extract_sync", fake_extract)

    svc.request(ThumbnailRequest(segment_id="seg3", src="c.mp4", ms=0))
    svc.request(ThumbnailRequest(segment_id="seg3", src="c.mp4", ms=0))
    svc.request(ThumbnailRequest(segment_id="seg3", src="c.mp4", ms=0))

    QThreadPool.globalInstance().waitForDone(2000)
    qtbot.wait(50)
    assert call_count[0] == 1


def test_service_handles_extraction_failure_silently(qtbot, monkeypatch):
    """extract_sync 가 None 을 반환하면 시그널 발화 안 함, pending 도 클리어."""
    extractor = ThumbnailExtractor()
    svc = ThumbnailService(extractor)
    monkeypatch.setattr(extractor, "extract_sync", lambda src, ms: None)

    received = []
    svc.thumbnail_ready.connect(lambda sid, im: received.append((sid, im)))
    svc.request(ThumbnailRequest(segment_id="seg4", src="bad.mp4", ms=0))
    QThreadPool.globalInstance().waitForDone(2000)
    qtbot.wait(50)
    assert received == []
    # 다음 요청 디스패치 가능 (pending 정리됐는지 확인)
    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF223344)
    monkeypatch.setattr(extractor, "extract_sync", lambda src, ms: img)
    svc.request(ThumbnailRequest(segment_id="seg4", src="bad.mp4", ms=0))
    QThreadPool.globalInstance().waitForDone(2000)
    qtbot.wait(50)
    assert len(received) == 1
