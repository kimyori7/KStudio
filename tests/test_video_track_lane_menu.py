"""VideoTrackLane 우클릭 메뉴 — 자르기 / 삭제 / 삽입."""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QContextMenuEvent

from screen_recorder.effects.segment import VideoSegment
from screen_recorder.ui.video.video_track_lane import VideoTrackLane


def _seg(src: str, dur: int, sid: str, start: int = 0) -> VideoSegment:
    return VideoSegment(
        id=sid, src=src, src_in_ms=0, src_out_ms=dur, src_duration_ms=dur,
        start_ms=start,
    )


def test_context_menu_on_segment_emits_split_or_delete(qtbot):
    """segment 위 우클릭 → 메뉴가 popup. 액션 trigger 시 시그널 emit."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([
        _seg("a.mp4", 4000, "a", start=0),
        _seg("b.mp4", 6000, "b", start=4000),
    ])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    target = boxes[0]["rect"].center()

    # popup() 으로 띄움 (non-blocking) — _last_menu 보관.
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, target,
                            lane.mapToGlobal(target))
    lane.contextMenuEvent(ev)
    menu = lane._last_menu
    assert menu is not None
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("자르기" in l for l in labels)
    assert any("삭제" in l for l in labels)


def test_context_menu_on_empty_area_emits_insert(qtbot):
    """segment 영역 밖 우클릭 → '영상 파일 삽입…' 메뉴."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    # x=10 (HEADER_WIDTH=56 안) 은 본체가 아니지만 일단 무시. 본체 빈 영역에 접근하려면
    # 트랙의 끝 너머가 필요 — 작은 segment 라 box 끝 + 30px 가 빈 영역.
    boxes = lane._segment_rects()
    end_x = boxes[0]["rect"].right() + 50
    end_y = boxes[0]["rect"].center().y()
    pt = QPoint(end_x, end_y)
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pt, lane.mapToGlobal(pt))
    lane.contextMenuEvent(ev)
    menu = lane._last_menu
    assert menu is not None
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("삽입" in l for l in labels)


def test_split_action_emits_request_split_with_local_ms(qtbot):
    """segment 위 좌측 1/4 지점에서 우클릭 → 자르기 → request_split(id, dur*0.25)."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    rect = boxes[0]["rect"]
    # segment 좌측에서 1/4 지점.
    pt = QPoint(rect.left() + rect.width() // 4, rect.center().y())

    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pt, lane.mapToGlobal(pt))
    lane.contextMenuEvent(ev)
    menu = lane._last_menu
    split = next(a for a in menu.actions() if "자르기" in a.text())

    with qtbot.waitSignal(lane.request_split, timeout=500) as blocker:
        split.trigger()
    sid, local_ms = blocker.args
    assert sid == "a"
    # ~25% of 4000ms ≈ 1000ms (±100ms 톨러런스).
    assert 800 <= local_ms <= 1200


def test_delete_action_emits_request_delete(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    pt = boxes[0]["rect"].center()
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pt, lane.mapToGlobal(pt))
    lane.contextMenuEvent(ev)
    menu = lane._last_menu
    delete = next(a for a in menu.actions() if "삭제" in a.text())

    with qtbot.waitSignal(lane.request_delete, timeout=500) as blocker:
        delete.trigger()
    assert blocker.args == ["a"]


def test_insert_action_emits_request_insert_at_end(qtbot):
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    pt = QPoint(boxes[0]["rect"].right() + 50, boxes[0]["rect"].center().y())
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pt, lane.mapToGlobal(pt))
    lane.contextMenuEvent(ev)
    menu = lane._last_menu
    insert = next(a for a in menu.actions() if "삽입" in a.text())

    with qtbot.waitSignal(lane.request_insert_at, timeout=500) as blocker:
        insert.trigger()
    # 새 contract: at_combined_ms (트랙상 시작 위치) — segment 끝(4000ms) 보다 큼.
    assert blocker.args[0] > 4000


def test_context_menu_on_segment_offers_copy(qtbot):
    """Phase 116 — 클립 위 우클릭에 '클립 복사'. 마우스로도 닿는 경로."""
    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    target = lane._segment_rects()[0]["rect"].center()
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, target, lane.mapToGlobal(target))
    lane.contextMenuEvent(ev)
    copy_action = next(a for a in lane._last_menu.actions() if "복사" in a.text())
    with qtbot.waitSignal(lane.request_copy, timeout=500) as sig:
        copy_action.trigger()
    assert sig.args == ["a"]


def test_paste_menu_item_only_when_clipboard_has_clip(qtbot):
    """빈 자리 우클릭의 '붙여넣기' 는 클립보드에 클립이 있을 때만 — 죽은 항목 금지."""
    from screen_recorder.ui.video.clip_clipboard import clipboard

    lane = VideoTrackLane()
    qtbot.addWidget(lane)
    lane.resize(400, 60)
    lane.set_segments([_seg("a.mp4", 4000, "a")])
    lane.show()
    qtbot.waitExposed(lane)

    boxes = lane._segment_rects()
    pt = QPoint(boxes[0]["rect"].right() + 50, boxes[0]["rect"].center().y())
    ev = QContextMenuEvent(QContextMenuEvent.Mouse, pt, lane.mapToGlobal(pt))

    clipboard().clear()
    lane.contextMenuEvent(ev)
    assert not any("붙여넣기" in a.text() for a in lane._last_menu.actions())

    try:
        clipboard().copy_segment(_seg("b.mp4", 3000, "b"))
        lane.contextMenuEvent(ev)
        paste_action = next(a for a in lane._last_menu.actions() if "붙여넣기" in a.text())
        with qtbot.waitSignal(lane.request_paste_at, timeout=500):
            paste_action.trigger()
    finally:
        clipboard().clear()
