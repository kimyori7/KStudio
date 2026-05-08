"""VideoTrackLane 외부 드래그-드롭 — request_insert_files 시그널 emit.

QDropEvent 생성이 까다로워 unittest.mock 으로 이벤트를 만들어 검증.
"""
from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, QPointF, QMimeData, QUrl, Qt

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.video_track_lane import VideoTrackLane


def _seg(src: str, dur: int, sid: str) -> VideoSegment:
    return VideoSegment(
        id=sid, src=src, src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
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
    paths, idx = blocker.args
    import os
    assert [os.path.normpath(p) for p in paths] == [os.path.normpath(str(f))]
    assert idx == 1   # 끝에


def test_drop_event_emits_between_segments(qtbot, tmp_path):
    """두 segment 사이에 drop → 가운데 idx (=1) 로 emit."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a"), _seg("b.mp4", 4000, "b")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    # box[0] 의 right + 1 ~ box[1].left 사이의 점은 보통 _BOX_GAP=2 짧지만
    # _x_to_insert_index 가 box[1].left 직전이면 1 반환.
    pt_x = boxes[1]["rect"].left() - 1   # box[1] 직전.
    pt_y = boxes[0]["rect"].center().y()

    f = tmp_path / "x.mp4"
    f.write_bytes(b"fake")
    urls = [QUrl.fromLocalFile(str(f))]

    with qtbot.waitSignal(lane.request_insert_files, timeout=500) as blocker:
        lane.dropEvent(_drop_event(pt_x, pt_y, urls))
    paths, idx = blocker.args
    assert idx == 1


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
