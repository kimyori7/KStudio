"""통지가 유실돼도 외부 변경을 놓치지 않는다 — 주기적 디스크 확인(polling) 안전망.

왜 필요한가 (2026-07-21, "갱신 팝업이 안 뜬다" 3회차 재발의 실측 결론):
  실제 앱에서 감시는 살아 있는데(3분 뒤 같은 폴더의 파일 생성엔 즉시 신호가 왔다)
  에이전트의 제자리 수정 1건에 대해 directoryChanged 가 오지 않았다. 단독 재현
  실험에서는 쓰기 방식 3종(제자리/생성/atomic) × 볼륨 2종(C:/D:) 전부 수신했고,
  앱과 같은 부하(라이브러리 60 폴더 + 탭 12 watcher)에서도 10/10 수신했다.
  → 우리 쪽 사용법 문제가 아니라 통지 스트림 자체가 이따금 유실된다.

Phase 108·110 은 통지가 도착한 *뒤*의 로직만 두껍게 해서 이 실패를 못 막았다.
그래서 통지에만 의존하지 않는다: 열린 문서 파일의 (mtime, size) 를 주기적으로 보고
달라졌으면 기존 검사 경로(_reload_check)를 태운다. 사용자가 하루 종일 손으로 누르던
⟳ 새로고침이 100% 동작했다는 사실이, 폴링이 맞는 답이라는 증거다.
"""
from pathlib import Path

import pytest


def _make_tab(tmp_path: Path, text: str = "v1"):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return MarkdownTab.from_file(p), p


def _stub_confirm(tab, answer: bool):
    calls = []

    def fake(dirty):
        calls.append(dirty)
        return answer

    tab._confirm_external_reload = fake
    return calls


def _sever_watcher(tab):
    """QFileSystemWatcher 통지 경로를 끊는다 — 실측된 '통지 유실'을 재현한다."""
    watched = tab._fs_watcher.files() + tab._fs_watcher.directories()
    if watched:
        tab._fs_watcher.removePaths(watched)
    assert not tab._fs_watcher.directories()


# --- DiskPoller 단위 ---

def test_poller_reports_change_after_write(tmp_path):
    from screen_recorder.ui.markdown.disk_poll import DiskPoller
    p = tmp_path / "doc.md"
    p.write_text("before", encoding="utf-8")
    poller = DiskPoller()
    poller.watch(p)
    assert poller.check() is False          # 쓴 적 없으면 조용
    p.write_text("after changed", encoding="utf-8")
    assert poller.check() is True           # 크기/시각이 달라졌다


def test_poller_is_quiet_when_untouched(tmp_path):
    from screen_recorder.ui.markdown.disk_poll import DiskPoller
    p = tmp_path / "doc.md"
    p.write_text("same", encoding="utf-8")
    poller = DiskPoller()
    poller.watch(p)
    assert poller.check() is False
    assert poller.check() is False          # 반복 호출해도 조용 (팝업 오탐 방지)


def test_poller_reports_change_when_size_same(tmp_path):
    """같은 길이로 바뀌어도 놓치지 않는다 — mtime 도 함께 본다."""
    from screen_recorder.ui.markdown.disk_poll import DiskPoller
    import os
    p = tmp_path / "doc.md"
    p.write_text("AAAA", encoding="utf-8")
    poller = DiskPoller()
    poller.watch(p)
    p.write_text("BBBB", encoding="utf-8")
    os.utime(p, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    assert poller.check() is True


def test_poller_without_path_is_quiet(tmp_path):
    """미저장 문서(경로 없음) — 폴링이 돌아도 아무 일 없어야 한다."""
    from screen_recorder.ui.markdown.disk_poll import DiskPoller
    poller = DiskPoller()
    poller.watch(None)
    assert poller.check() is False


# --- 탭 통합: 통지가 죽어도 탐지된다 (이 버그의 회귀 테스트) ---

def test_tab_detects_change_even_when_watcher_never_signals(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    _sever_watcher(tab)                     # 통지 유실 상황
    calls = _stub_confirm(tab, answer=True)

    p.write_text("changed externally", encoding="utf-8")
    tab._poll_disk()                        # 실제로는 QTimer 가 주기 호출

    assert calls == [False]                 # 통지 없이도 팝업이 떴다
    assert tab.editor.toPlainText() == "changed externally"
    assert not tab.needs_save()


def test_tab_poll_does_not_prompt_without_change(qtbot, tmp_path):
    """오탐 금지 — 아무도 안 건드렸으면 폴링이 돌아도 조용."""
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    for _ in range(3):
        tab._poll_disk()
    assert calls == []
    assert tab.editor.toPlainText() == "original"


def test_tab_poll_ignores_our_own_save(qtbot, tmp_path):
    """우리 앱이 저장한 것에는 팝업이 뜨면 안 된다(자기 저장 오탐)."""
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    tab.editor.setPlainText("edited in app")
    tab.save()
    for _ in range(3):
        tab._poll_disk()
    assert calls == []


def test_tab_poll_survives_missing_file(qtbot, tmp_path):
    """파일이 지워져도 폴링이 예외로 죽지 않는다(타이머는 계속 돌아야 한다)."""
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    _stub_confirm(tab, answer=True)
    p.unlink()
    tab._poll_disk()                        # 예외 없이 통과해야 함
