"""VideoTrackLane — 필름스트립 + 좌클릭 선택. Stage A 기본 표시."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QMouseEvent

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.video_track_lane import VideoTrackLane


def _seg(src: str, dur_ms: int, sid: str = "", start_ms: int = 0) -> VideoSegment:
    kw = {"src": src, "src_in_ms": 0, "src_out_ms": dur_ms,
          "src_duration_ms": dur_ms, "start_ms": start_ms}
    if sid:
        kw["id"] = sid
    return VideoSegment(**kw)


def test_lane_renders_one_box_per_segment(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_duration_ms(10_000)
    lane.set_segments([
        _seg("a.mp4", 4000, "a", start_ms=0),
        _seg("b.mp4", 6000, "b", start_ms=4000),
    ])
    lane.show()
    qtbot.waitExposed(lane)
    boxes = lane._segment_rects()
    assert len(boxes) == 2
    assert boxes[0]["id"] == "a"
    assert boxes[1]["id"] == "b"
    # b 가 더 길어 더 넓어야 함.
    assert boxes[0]["rect"].width() < boxes[1]["rect"].width()


def test_lane_click_emits_segment_selected(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_duration_ms(10_000)
    lane.set_segments([
        _seg("a.mp4", 4000, "a", start_ms=0),
        _seg("b.mp4", 6000, "b", start_ms=4000),
    ])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    target = boxes[0]["rect"].center()

    with qtbot.waitSignal(lane.segment_selected, timeout=500) as blocker:
        press = QMouseEvent(QMouseEvent.MouseButtonPress, target,
                             lane.mapToGlobal(target),
                             Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        release = QMouseEvent(QMouseEvent.MouseButtonRelease, target,
                               lane.mapToGlobal(target),
                               Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        lane.mousePressEvent(press)
        lane.mouseReleaseEvent(release)
    assert blocker.args == ["a"]


def test_lane_set_selected_id(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([_seg("a.mp4", 4000, "a"), _seg("b.mp4", 6000, "b")])
    lane.set_selected_id("a")
    assert lane._selected_id == "a"
    lane.set_selected_id(None)
    assert lane._selected_id is None


def test_lane_empty_segments_no_crash(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([])
    lane.show()
    qtbot.waitExposed(lane)
    assert lane._segment_rects() == []


def test_lane_thumbnail_set_does_not_crash(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    img = QImage(96, 54, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    lane.set_thumbnail("a", 0, img)
    assert ("a", 0) in lane._thumbnails


def test_lane_total_duration_uses_segments_when_unset(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([
        _seg("a.mp4", 3000, "a", start_ms=0),
        _seg("b.mp4", 7000, "b", start_ms=3000),
    ])
    # set_duration_ms 안 부른 경우 max end_ms = 10000.
    assert lane._total_duration_ms() == 10_000


def test_lane_total_duration_with_gap(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.set_segments([
        _seg("a.mp4", 3000, "a", start_ms=0),
        _seg("b.mp4", 2000, "b", start_ms=5000),
    ])
    # 갭 (3000~5000) 포함 → max end_ms = 7000.
    assert lane._total_duration_ms() == 7000


def test_lane_drag_emits_segment_position_changed(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_duration_ms(10_000)
    lane.set_segments([_seg("a.mp4", 4000, "a", start_ms=0)])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    start = boxes[0]["rect"].center()
    moved = start + type(start)(80, 0)   # 오른쪽으로 80px (= 약 2300 ms in 10s/body).

    with qtbot.waitSignal(lane.segment_position_changed, timeout=500) as blocker:
        press = QMouseEvent(QMouseEvent.MouseButtonPress, start,
                             lane.mapToGlobal(start),
                             Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        move = QMouseEvent(QMouseEvent.MouseMove, moved,
                           lane.mapToGlobal(moved),
                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        release = QMouseEvent(QMouseEvent.MouseButtonRelease, moved,
                               lane.mapToGlobal(moved),
                               Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        lane.mousePressEvent(press)
        lane.mouseMoveEvent(move)
        lane.mouseReleaseEvent(release)
    assert blocker.args[0] == "a"
    assert blocker.args[1] > 0   # 오른쪽으로 갔으니 양수 start_ms.


# ---------- segment_h_rects 순수 함수 ----------

def test_segment_h_rects_positions():
    from screen_recorder.ui.video.video_track_lane import segment_h_rects
    from screen_recorder.effects.segment import VideoSegment

    s0 = VideoSegment(src="a", src_in_ms=0, src_out_ms=0,
                      src_duration_ms=1000, start_ms=0)
    s1 = VideoSegment(src="a", src_in_ms=0, src_out_ms=0,
                      src_duration_ms=1000, start_ms=1000)
    rects = segment_h_rects([s0, s1], total_ms=2000, body_width=200, header_width=56)
    assert rects[0]["x"] == 56 and rects[1]["x"] == 56 + 100
    assert all(r["w"] >= 1 for r in rects)


def test_segment_h_rects_empty():
    from screen_recorder.ui.video.video_track_lane import segment_h_rects
    assert segment_h_rects([], total_ms=0, body_width=200) == []
