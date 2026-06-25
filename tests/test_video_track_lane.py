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


def test_lane_has_thumbnail_reports_presence(qtbot):
    """has_thumbnail — 슬롯 (segment_id, ms) 이 이미 캐시에 있으면 True.

    편집마다 _request_all_thumbnails 가 전체 슬롯을 재요청해 ffmpeg 폭풍을 내던
    회귀(클립 많을수록 CPU/메모리 폭증)를 막기 위해, 이미 가진 슬롯은 skip 하는 데 쓴다.
    """
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    assert lane.has_thumbnail("a", 0) is False
    img = QImage(96, 54, QImage.Format_RGB888)
    img.fill(0)
    lane.set_thumbnail("a", 0, img)
    assert lane.has_thumbnail("a", 0) is True
    # 다른 ms / 다른 segment 는 여전히 없음.
    assert lane.has_thumbnail("a", 999) is False
    assert lane.has_thumbnail("b", 0) is False


def test_lane_missing_thumbnail_slots_excludes_cached(qtbot):
    """missing_thumbnail_slots — 아직 없는 슬롯만 반환. 편집마다 전체 재요청 대신
    빠진 것만 추출하게 해 ffmpeg 폭풍(클립 많을수록 CPU/메모리 폭증)을 막는다."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    seg = _seg("a.mp4", 4000, "a", start_ms=0)
    all_slots = lane.thumbnail_slots_for(seg)
    assert all_slots, "사전조건: 슬롯이 하나 이상"
    # 캐시 비었을 때 — 전부 missing.
    assert lane.missing_thumbnail_slots(seg) == all_slots
    # 한 슬롯을 채우면 그것만 빠진다.
    img = QImage(96, 54, QImage.Format_RGB888)
    img.fill(0)
    lane.set_thumbnail("a", all_slots[0], img)
    remaining = lane.missing_thumbnail_slots(seg)
    assert all_slots[0] not in remaining
    assert remaining == all_slots[1:]
    # 전부 채우면 빈 리스트 — 재요청 0건.
    for ms in all_slots:
        lane.set_thumbnail("a", ms, img)
    assert lane.missing_thumbnail_slots(seg) == []


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
