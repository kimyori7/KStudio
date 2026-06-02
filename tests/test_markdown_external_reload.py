"""외부에서 .md 파일이 수정되면 확인 팝업 후 열린 문서 탭에 반영 (QFileSystemWatcher).

정책(2026-06-01 사용자 요청): 조용히 덮어쓰지 않는다. 외부 변경이 감지되면 "최신 내용으로
불러올까요?" 확인 팝업을 띄우고, [예] 일 때만 반영한다.
- [예]: 디스크 최신본으로 reload (커서/스크롤 보존)
- [아니오]: 현재 내용 유지 + 거절한 버전을 기억(같은 내용으로 다시 묻지 않음)
- 미저장 편집이 있으면 팝업에 '편집 내용이 사라집니다' 경고(dirty 플래그로 전달)
- 우리 앱 자신의 저장: 디스크 == 마지막 동기화 내용 → 팝업 안 뜸(오탐 없음)

모달 QMessageBox 는 헤드리스에서 블록되므로 _confirm_external_reload 를 monkeypatch 해
(예/아니오) 답을 주입하고 호출 여부/인자를 기록한다. 실제 fileChanged 시그널은 느리고
불안정하므로 reload 로직(_reload_check)을 직접 호출 — 시그널 배선만 별도 1건 검증.
"""
from pathlib import Path

import pytest


def _make_tab(tmp_path: Path, text: str = "v1"):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return MarkdownTab.from_file(p), p


def _stub_confirm(tab, answer: bool):
    """_confirm_external_reload 를 대체 — (dirty 인자들 기록, 미리 정한 답 반환)."""
    calls = []

    def fake(dirty):
        calls.append(dirty)
        return answer

    tab._confirm_external_reload = fake   # bound 메서드 자리 인스턴스 속성으로 덮어씀
    return calls


def test_open_starts_watching_file(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    assert str(p) in tab._fs_watcher.files()
    assert tab.editor.toPlainText() == "v1"
    assert not tab.needs_save()


def test_clean_change_prompts_then_reloads_on_yes(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.write_text("changed externally", encoding="utf-8")
    tab._reload_check()
    assert calls == [False]                       # 팝업이 떴고(깨끗 → dirty=False)
    assert tab.editor.toPlainText() == "changed externally"
    assert not tab.needs_save()


def test_no_silent_reload_without_confirmation(qtbot, tmp_path):
    """확인 없이는 절대 바뀌지 않는다 — [아니오] 면 현재 내용 유지."""
    tab, p = _make_tab(tmp_path, "original")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=False)
    p.write_text("changed externally", encoding="utf-8")
    tab._reload_check()
    assert calls == [False]                       # 물어보긴 함
    assert tab.editor.toPlainText() == "original"  # 거절 → 그대로


def test_decline_does_not_reprompt_same_content(qtbot, tmp_path):
    """거절한 버전은 기억 — 같은 내용으로 fileChanged 가 또 와도 다시 안 묻는다."""
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=False)
    p.write_text("v2", encoding="utf-8")
    tab._reload_check()
    tab._reload_check()                            # 동일 내용 두 번째 검사
    assert calls == [False]                        # 단 한 번만 물어봄


def test_yes_preserves_cursor_and_clears_dirty(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "line0\nline1\nline2\n")
    qtbot.addWidget(tab)
    _stub_confirm(tab, answer=True)
    cur = tab.editor.textCursor()
    cur.setPosition(3)
    tab.editor.setTextCursor(cur)
    p.write_text("LINE0\nline1\nline2\nline3\n", encoding="utf-8")
    tab._reload_check()
    assert tab.editor.toPlainText() == "LINE0\nline1\nline2\nline3\n"
    assert tab.editor.textCursor().position() == 3
    assert not tab.needs_save()


def test_dirty_change_passes_warning_flag(qtbot, tmp_path):
    """미저장 편집이 있으면 팝업에 dirty=True 로 경고를 전달한다."""
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    tab.editor.setPlainText("MY UNSAVED EDIT")
    assert tab.needs_save()
    calls = _stub_confirm(tab, answer=False)       # 일단 거절
    p.write_text("v2 from outside", encoding="utf-8")
    tab._reload_check()
    assert calls == [True]                         # dirty=True 로 물어봄(경고 문구)
    assert tab.editor.toPlainText() == "MY UNSAVED EDIT"   # 거절 → 편집 보존


def test_dirty_yes_discards_local_and_loads_disk(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    tab.editor.setPlainText("MY UNSAVED EDIT")
    _stub_confirm(tab, answer=True)
    p.write_text("v2 from outside", encoding="utf-8")
    tab._reload_check()
    assert tab.editor.toPlainText() == "v2 from outside"
    assert not tab.needs_save()


def test_own_save_then_type_does_not_prompt(qtbot, tmp_path):
    """advisor 지적: 저장 직후 타이핑 → 디스크(V1) ≠ 편집기(V2) 라도 오탐 금지.

    비교 기준은 '마지막으로 디스크와 동기화한 내용'(_disk_text) — 자기 저장은 안 묻는다.
    """
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    tab.editor.setPlainText("v2")
    tab.save_as(p)                                 # 우리 앱이 디스크에 v2 기록
    assert not tab.needs_save()
    tab.editor.setPlainText("v2 typing more")      # 저장 직후 타이핑(더티)
    tab._reload_check()                            # 저장으로 인한 fileChanged 처리
    assert calls == []                             # 자기 저장 → 팝업 없음
    assert tab.editor.toPlainText() == "v2 typing more"


def test_external_delete_is_ignored(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=True)
    p.unlink()
    tab._reload_check()                            # 크래시 없이 무시
    assert calls == []
    assert tab.editor.toPlainText() == "v1"


def test_save_updates_watch_path(qtbot, tmp_path):
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("new doc")
    target = tmp_path / "saved.md"
    tab.save_as(target)
    assert str(target) in tab._fs_watcher.files()


def test_filechanged_signal_triggers_debounced_prompt(qtbot, tmp_path):
    """배선 확인: fileChanged → 디바운스 타이머 → _reload_check(팝업) 발화.

    OS 파일 이벤트 감지 의존은 헤드리스에서 불안정 → 시그널을 직접 emit 해
    (시그널→타이머→핸들러) 경로만 결정론적으로 검증한다. 답은 [예] 주입.
    """
    tab, p = _make_tab(tmp_path, "before")
    qtbot.addWidget(tab)
    _stub_confirm(tab, answer=True)
    p.write_text("after via watcher", encoding="utf-8")
    tab._fs_watcher.fileChanged.emit(str(p))       # OS 이벤트 모사
    qtbot.waitUntil(lambda: tab.editor.toPlainText() == "after via watcher", timeout=1000)
    assert not tab.needs_save()
