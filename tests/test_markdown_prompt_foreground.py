"""외부 변경 팝업을 띄우기 직전에 앱 창을 앞으로 끌어올린다.

왜 (2026-07-21 실사용 로그): 팝업은 제때 떴는데 사용자가 편집기에서 작업 중이라
편집기 뒤에 깔려 한참 못 봤다 — 감지→답변 간격이 7/15 41분, 7/20 1시간 39분,
7/21 8분. 앱 전체를 막는 모달이라 KStudio 를 쓰려 하면 반드시 알게 되지만,
그때까지는 문서가 안 갱신된 채로 남는다(사용자 체감: "팝업이 안 뜬다").

여기서 검증하는 것은 *배선*뿐이다. 실제로 창이 올라오는지는 Windows 포그라운드
정책이 결정하므로 헤드리스 테스트로 재현할 수 없다(windows-foreground-window 스킬:
"user manual verification on real Windows as ground truth"). 그래서 테스트는
"팝업 직전에 창 올리기를 호출한다 / 그게 없거나 실패해도 팝업은 뜬다"만 못박는다.
"""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget


def _make_tab(tmp_path: Path, text: str = "v1"):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return MarkdownTab.from_file(p), p


def _host_window(tab, hook=None):
    """탭을 최상위 창에 넣는다 — window() 가 그 창을 돌려주게. hook 은 bring_to_front."""
    win = QWidget()
    if hook is not None:
        win.bring_to_front = hook          # 인스턴스 속성으로 주입(덕 타이핑 배선)
    tab.setParent(win)
    return win


def _stub_question(monkeypatch, order, answer=QMessageBox.StandardButton.Yes):
    import screen_recorder.ui.markdown_tab as mt

    def fake_question(*a, **kw):
        order.append("popup")
        return answer

    monkeypatch.setattr(mt.QMessageBox, "question", staticmethod(fake_question))


def test_prompt_brings_window_to_front_first(qtbot, tmp_path, monkeypatch):
    tab, _ = _make_tab(tmp_path)
    order = []
    win = _host_window(tab, hook=lambda: order.append("front"))
    qtbot.addWidget(win)
    _stub_question(monkeypatch, order)

    assert tab._confirm_external_reload(False) is True
    # 팝업보다 *먼저* 창을 올려야 한다 — 순서가 뒤집히면 뜬 뒤에 올라와 의미가 준다.
    assert order == ["front", "popup"]


def test_prompt_works_when_host_has_no_hook(qtbot, tmp_path, monkeypatch):
    """평범한 부모(테스트/다른 컨테이너) — 창 올리기가 없어도 팝업은 떠야 한다."""
    tab, _ = _make_tab(tmp_path)
    order = []
    win = _host_window(tab, hook=None)
    qtbot.addWidget(win)
    _stub_question(monkeypatch, order)

    assert tab._confirm_external_reload(False) is True
    assert order == ["popup"]


def test_prompt_survives_bring_to_front_failure(qtbot, tmp_path, monkeypatch):
    """포커스 실패가 팝업을 막으면 안 된다 — 그게 본 기능이다."""
    tab, _ = _make_tab(tmp_path)
    order = []

    def boom():
        order.append("front")
        raise RuntimeError("foreground denied")

    win = _host_window(tab, hook=boom)
    qtbot.addWidget(win)
    _stub_question(monkeypatch, order, answer=QMessageBox.StandardButton.No)

    assert tab._confirm_external_reload(True) is False
    assert order == ["front", "popup"]
