"""VideoTrackLane 외부 드래그-드롭 — request_insert_files 시그널 emit.

QDropEvent 생성이 까다로워 unittest.mock 으로 이벤트를 만들어 검증.
"""
from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, QPointF, QMimeData, QUrl, Qt

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.video_track_lane import VideoTrackLane


def _seg(src: str, dur: int, sid: str, start: int = 0) -> VideoSegment:
    return VideoSegment(
        id=sid, src=src, src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
        start_ms=start,
    )


def _drop_event(x: int, y: int, urls: list[QUrl]) -> MagicMock:
    """dropEvent 가 사용하는 메서드만 가진 mock."""
    mime = QMimeData()
    mime.setUrls(urls)
    ev = MagicMock()
    ev.mimeData.return_value = mime
    ev.position.return_value = QPointF(x, y)
    ev.acceptProposedAction = MagicMock()
    ev.ignore = MagicMock()
    return ev


def test_drop_event_emits_request_insert_files_at_end(qtbot, tmp_path):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    end_x = boxes[0]["rect"].right() + 50
    cy = boxes[0]["rect"].center().y()

    f = tmp_path / "drop.mp4"
    f.write_bytes(b"fake")
    urls = [QUrl.fromLocalFile(str(f))]

    with qtbot.waitSignal(lane.request_insert_files, timeout=500) as blocker:
        lane.dropEvent(_drop_event(end_x, cy, urls))
    paths, at_ms = blocker.args
    import os
    assert [os.path.normpath(p) for p in paths] == [os.path.normpath(str(f))]
    # 끝(end_x = box.right + 50) 위치는 segment 끝(4000ms) 보다 큼.
    assert at_ms > 4000


def test_drop_event_emits_between_segments_with_gap(qtbot, tmp_path):
    """두 segment 사이 갭에 drop → 결합 ms 가 갭 안 위치로 emit."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    # 4000~5000 갭 만들기.
    lane.set_segments([
        _seg("a.mp4", 4000, "a", start=0),
        _seg("b.mp4", 4000, "b", start=5000),
    ])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    # 갭 가운데로 drop.
    pt_x = (boxes[0]["rect"].right() + boxes[1]["rect"].left()) // 2
    pt_y = boxes[0]["rect"].center().y()

    f = tmp_path / "x.mp4"
    f.write_bytes(b"fake")
    urls = [QUrl.fromLocalFile(str(f))]

    with qtbot.waitSignal(lane.request_insert_files, timeout=500) as blocker:
        lane.dropEvent(_drop_event(pt_x, pt_y, urls))
    paths, at_ms = blocker.args
    # 갭 안 (4000~5000) 어딘가.
    assert 3500 < at_ms < 5500


def test_drop_event_with_multiple_urls(qtbot, tmp_path):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    f1 = tmp_path / "1.mp4"; f1.write_bytes(b"a")
    f2 = tmp_path / "2.png"; f2.write_bytes(b"b")
    urls = [QUrl.fromLocalFile(str(f1)), QUrl.fromLocalFile(str(f2))]
    with qtbot.waitSignal(lane.request_insert_files, timeout=500) as blocker:
        lane.dropEvent(_drop_event(70, 30, urls))
    paths, _idx = blocker.args
    import os
    assert [os.path.normpath(p) for p in paths] == [
        os.path.normpath(str(f1)), os.path.normpath(str(f2)),
    ]


def test_drag_enter_accepts_urls_only(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    # URL 없는 mime → ignore.
    ev = MagicMock()
    mime = QMimeData()
    mime.setText("plain text")
    ev.mimeData.return_value = mime
    ev.acceptProposedAction = MagicMock()
    ev.ignore = MagicMock()
    lane.dragEnterEvent(ev)
    ev.acceptProposedAction.assert_not_called()
    ev.ignore.assert_called_once()

    # URL 있으면 accept.
    ev2 = MagicMock()
    mime2 = QMimeData()
    mime2.setUrls([QUrl.fromLocalFile("/tmp/x.mp4")])
    ev2.mimeData.return_value = mime2
    ev2.acceptProposedAction = MagicMock()
    ev2.ignore = MagicMock()
    lane.dragEnterEvent(ev2)
    ev2.acceptProposedAction.assert_called_once()
