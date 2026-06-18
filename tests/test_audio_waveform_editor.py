"""AudioWaveformEditor — 트림/컷/seek 편집 표면 단위 테스트."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent


def _press(w, x, y=60):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(ev)


def _move(w, x, y=60):
    ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(x, y),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(ev)


def _release(w, x, y=60):
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseReleaseEvent(ev)


def test_set_peaks_and_total(qtbot):
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.set_total_ms(10000); w.set_peaks([0.5] * 200)
    assert w._total_ms == 10000 and len(w._peaks) == 200


def test_add_cut_ms_emits(qtbot):
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(820, 120); w.set_total_ms(10000); w.set_peaks([0.3] * 100)
    got = []; w.cuts_changed.connect(got.append)
    w.add_cut_ms(3000, 4000)
    assert got and got[-1] == [(3000, 4000)]
    assert w.cuts() == [(3000, 4000)]


def test_set_trim_keeps_order(qtbot):
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.set_total_ms(10000); w.set_trim(2000, 8000)
    assert w.trim() == (2000, 8000)


def test_click_in_body_emits_seek(qtbot):
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    got = []; w.seek_request.connect(got.append)
    # a plain click (press+release at same point) in the middle should seek
    pos = QPointF(400, 60)
    for et in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        ev = QMouseEvent(et, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        w.mousePressEvent(ev) if et == QMouseEvent.Type.MouseButtonPress else w.mouseReleaseEvent(ev)
    assert got  # some ms emitted


# ---------- extra sensible tests ----------
def test_seek_maps_x_to_ms(qtbot):
    """800px / 10000ms 에서 x=400 클릭은 ~5000ms 로 매핑된다."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    got = []; w.seek_request.connect(got.append)
    _press(w, 400); _release(w, 400)
    assert got and abs(got[-1] - 5000) <= 50


def test_drag_selects_then_right_click_cuts(qtbot):
    """빈 영역 드래그 = '선택'(아직 안 자름). 우클릭 메뉴의 자르기(cut_selection)로 확정."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    cuts = []; seeks = []
    w.cuts_changed.connect(cuts.append); w.seek_request.connect(seeks.append)
    _press(w, 200); _move(w, 360); _release(w, 360)
    # 드래그는 선택만 — 아직 컷 아님(cuts_changed 안 옴).
    assert not cuts and not seeks
    sel = w.selection()
    assert sel is not None and abs(sel[0] - 2500) <= 60 and abs(sel[1] - 4500) <= 60
    assert w.cuts() == []
    # 우클릭 '자르기' = cut_selection → 이제 컷 확정 + 선택 해제.
    assert w.cut_selection() is True
    assert cuts and abs(w.cuts()[-1][0] - 2500) <= 60
    assert w.selection() is None


def test_trim_grab_only_near_grip_band(qtbot):
    """트림 핸들은 그립 세로 밴드 근처에서만 잡힌다 — 라인 위/아래 끝(밴드 밖)은 트림 아님."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.set_trim(0, 10000)
    # 그립 밴드 안(가운데 y=60)에서는 잡힘.
    assert w._trim_hit(0, 60) == "trim_in"
    assert w._trim_hit(800, 60) == "trim_out"
    # 밴드 밖(맨 위 y=4, 맨 아래 y=116)에서는 같은 x 라도 안 잡힘.
    assert w._trim_hit(0, 4) is None
    assert w._trim_hit(800, 116) is None
    # 밴드 밖에서 드래그하면 트림이 아니라 '선택'이 된다.
    trims = []; w.trim_changed.connect(lambda a, b: trims.append((a, b)))
    _press(w, 0, y=4); _move(w, 200, y=4); _release(w, 200, y=4)
    assert not trims                    # 트림 변경 없음
    assert w.selection() is not None    # 대신 선택


def test_hover_cursor_feedback(qtbot):
    """마우스 오버 — 트림 그립=손(OpenHand), 컷=손가락(PointingHand), 빈 영역=기본(Arrow)."""
    from PySide6.QtCore import Qt
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.set_trim(0, 10000)
    w._update_hover_cursor(0, 60)           # 트림 그립(가운데 밴드) → 손
    assert w.cursor().shape() == Qt.OpenHandCursor
    w._update_hover_cursor(0, 4)            # 같은 x 라도 그립 밴드 밖 → 손 아님
    assert w.cursor().shape() != Qt.OpenHandCursor
    w.add_cut_ms(3000, 4000)
    w._update_hover_cursor(280, 60)         # 컷(3500ms) 위 → 손가락
    assert w.cursor().shape() == Qt.PointingHandCursor
    w._update_hover_cursor(600, 60)         # 빈 영역 → 기본
    assert w.cursor().shape() == Qt.ArrowCursor


def test_context_menu_offers_cut_and_uncut(qtbot):
    """선택 위 우클릭 → '자르기', 컷 위 우클릭 → '자르기 취소'."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.set_selection((3000, 4000))
    texts = [a.text() for a in w._context_menu_for(3500).actions()]
    assert any("자르기" in t and "취소" not in t for t in texts)
    # 컷 위에서는 '자르기 취소' 제공 + 제거 동작.
    w.set_selection(None); w.add_cut_ms(5000, 6000)
    texts2 = [a.text() for a in w._context_menu_for(5500).actions()]
    assert any("취소" in t for t in texts2)
    assert w.remove_cut_at_ms(5500) is True
    assert w.cuts() == []


def test_click_on_cut_removes_it(qtbot):
    """기존 컷 위 클릭 → 그 컷 제거 + cuts_changed."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.add_cut_ms(3000, 4000)
    assert w.cuts() == [(3000, 4000)]
    got = []; w.cuts_changed.connect(got.append)
    # x for 3500ms = 800 * 3500 / 10000 = 280
    _press(w, 280); _release(w, 280)
    assert got and got[-1] == []
    assert w.cuts() == []


def test_drag_trim_in_emits_trim_changed(qtbot):
    """트림 in 핸들(x≈0) 근처를 잡고 드래그 → trim_changed."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.set_trim(0, 10000)
    got = []; w.trim_changed.connect(lambda a, b: got.append((a, b)))
    _press(w, 0); _move(w, 160); _release(w, 160)   # 160px ≈ 2000ms
    assert got
    new_in, _ = w.trim()
    assert abs(new_in - 2000) <= 60


def test_set_cuts_normalizes(qtbot):
    """set_cuts 는 정렬·병합(_normalize 경유)된 컷을 저장한다."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.set_total_ms(10000)
    w.set_cuts([(4000, 5000), (1000, 2000), (1500, 1800)])
    assert w.cuts() == [(1000, 2000), (4000, 5000)]


# ---------- 발견된 사용성 이슈 fix ----------
def test_hint_shown_only_when_ready_and_unedited(qtbot):
    """편집 안내 힌트: 파형+길이 준비됨 & 미편집일 때만. 길이 0/편집 후엔 숨김."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    assert not w._should_show_hint()                 # 아무것도 없음
    w.set_total_ms(10000)
    assert not w._should_show_hint()                 # 파형(peaks) 아직 없음
    w.set_peaks([0.2] * 50)
    assert w._should_show_hint()                     # 준비됨 + 미편집 → 보임
    w.add_cut_ms(3000, 4000)
    assert not w._should_show_hint()                 # 컷 생기면 숨김
    w.set_cuts([]); w.set_trim(1000, 0)
    assert not w._should_show_hint()                 # 트림하면 숨김


def test_edge_trim_handles_are_grabbable(qtbot):
    """가장자리(x=0, x=width) 트림 핸들이 집힌다 — 그립 폭만큼 안쪽까지 히트."""
    from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor
    w = AudioWaveformEditor(); qtbot.addWidget(w)
    w.resize(800, 120); w.set_total_ms(10000); w.set_peaks([0.2] * 50)
    w.set_trim(0, 10000)
    # 왼쪽 끝(x=0) press → in 핸들 드래그로 인식 → 드래그 시 trim_in 변경.
    got = []; w.trim_changed.connect(lambda a, b: got.append((a, b)))
    _press(w, 0); _move(w, 120); _release(w, 120)
    assert got and abs(w.trim()[0] - 1500) <= 80
    # 회귀: 왼쪽 핸들 release 가 trim_out 을 붕괴(trim_in+1)시키면 안 된다.
    assert w.trim()[1] >= 9000
    # 오른쪽 끝(x=width) press → out 핸들 드래그.
    got.clear()
    _press(w, 800); _move(w, 680); _release(w, 680)
    assert got
    assert 8000 <= w.trim()[1] < 10000   # out 이 안쪽으로 당겨짐
    assert abs(w.trim()[0] - 1500) <= 80  # in 은 그대로
