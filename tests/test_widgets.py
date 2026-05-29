"""OneShotKeySequenceEdit — 인라인 단축키 편집기의 pause/resume 신호 균형 회귀 테스트.

배경 (2026-05-29 사용자 보고 "갑자기 Ctrl+Shift+R 안 먹힘"):
편집기 focusIn → editing_started → main_window 가 전역 핫키 unregister(일시정지).
focusOut → editing_finished_signal → 재등록(재개). 그런데 편집기가 포커스를 가진 채
*숨겨지면*(모드 전환 등) focusOutEvent 가 안 와서 finished 가 누락 → 전역 핫키가
영구 해제 상태로 남았음. OS 프로브로 Ctrl+Shift+R/T 가 FREE(미등록) 확인됨.

fix: _capturing 상태 플래그 + hideEvent 에서도 capture 종료 보장(idempotent).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFocusEvent, QHideEvent


def _make(qapp):
    from screen_recorder.ui.widgets import OneShotKeySequenceEdit
    ed = OneShotKeySequenceEdit()
    started: list[int] = []
    finished: list[int] = []
    ed.editing_started.connect(lambda: started.append(1))
    ed.editing_finished_signal.connect(lambda: finished.append(1))
    return ed, started, finished


def test_focus_in_emits_started(qapp):
    ed, started, finished = _make(qapp)
    ed.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
    assert started == [1]
    assert finished == []


def test_focus_out_emits_finished(qapp):
    ed, started, finished = _make(qapp)
    ed.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
    ed.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert started == [1]
    assert finished == [1]


def test_hide_while_capturing_still_emits_finished(qapp):
    """회귀: focusIn 후 focusOut 없이 숨겨져도 finished(=resume) 가 떠야 함.

    안 그러면 전역 핫키가 영구 해제 상태로 남음 (사용자 보고 2026-05-29).
    """
    ed, started, finished = _make(qapp)
    ed.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
    ed.hideEvent(QHideEvent())
    assert started == [1]
    assert finished == [1], "숨김 시 editing_finished_signal 누락 — 핫키 영구 해제 회귀"


def test_finished_not_double_emitted_on_hide_then_focus_out(qapp):
    """idempotent — 숨김으로 한 번 종료된 뒤 focusOut 이 또 와도 finished 는 1회만."""
    ed, started, finished = _make(qapp)
    ed.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
    ed.hideEvent(QHideEvent())
    ed.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert finished == [1], "finished 가 중복 발화되면 안 됨"


def test_no_finished_without_started(qapp):
    """focusIn 없이 숨김/focusOut 만 오면 finished 안 뜸 (started 없는데 resume 금지)."""
    ed, started, finished = _make(qapp)
    ed.hideEvent(QHideEvent())
    ed.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert started == []
    assert finished == []
