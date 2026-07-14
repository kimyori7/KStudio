"""문서 새로고침 버튼 (⟳) — 비교 버튼 옆, 수동 새로고침 + 감시 재장전.

동작 (2026-07-14 사용자 요청 — 외부 변경 팝업이 실사용에서 안 뜬 사건의 안전망):
- 외부 변경 있음 + 깨끗: 즉시 반영 (버튼 클릭 = 명시적 동의라 팝업 없음)
- 외부 변경 있음 + 미저장 편집: 잃음 경고 확인 팝업, [예] 만 반영
- 외부 변경 없음: 미리보기만 재렌더 (죽은 미리보기 수동 복구 수단)
- 어떤 경우든 파일 감시(QFileSystemWatcher)를 재장전 — 죽은 watch 자가 복구
"""
from pathlib import Path


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


def test_refresh_button_exists_next_to_diff(qtbot, tmp_path):
    """새로고침 버튼은 모드 버튼(비교) 바로 옆의 액션 버튼 — 체크 불가(모드 아님)."""
    tab, _ = _make_tab(tmp_path)
    qtbot.addWidget(tab)
    btn = tab.refresh_btn
    assert "새로고침" in btn.text()
    assert not btn.isCheckable()


def test_refresh_clean_applies_disk_without_prompt(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    calls = _stub_confirm(tab, answer=False)   # 팝업이 뜨면 False 로 막힘 → 뜨면 안 됨
    p.write_text("v2 external", encoding="utf-8")
    tab.refresh_btn.click()
    assert calls == []                          # 묻지 않고
    assert tab.editor.toPlainText() == "v2 external"   # 즉시 반영
    assert not tab.needs_save()


def test_refresh_dirty_asks_before_discarding_edits(qtbot, tmp_path):
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    tab.editor.setPlainText("MY EDIT")
    calls = _stub_confirm(tab, answer=False)
    p.write_text("v2 external", encoding="utf-8")
    tab.refresh_btn.click()
    assert calls == [True]                      # 잃음 경고로 물어봄
    assert tab.editor.toPlainText() == "MY EDIT"  # 거절 → 편집 보존

    _stub_confirm(tab, answer=True)
    tab.refresh_btn.click()
    assert tab.editor.toPlainText() == "v2 external"


def test_refresh_no_external_change_rerenders_preview_only(qtbot, tmp_path):
    """디스크가 그대로면 편집 내용을 건드리지 않고 미리보기만 다시 렌더한다
    (미저장 편집이 있어도 잃지 않음 — 죽은 미리보기 복구 용도)."""
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    tab.editor.setPlainText("MY EDIT")          # dirty, 디스크는 v1 그대로
    calls = _stub_confirm(tab, answer=False)
    rendered = []
    tab.preview.set_content = lambda text, doc_dir=None: rendered.append(text)
    tab.refresh_btn.click()
    assert calls == []                          # 팝업 없음
    assert tab.editor.toPlainText() == "MY EDIT"  # 편집 보존
    assert rendered and rendered[-1] == "MY EDIT"  # 미리보기 재렌더


def test_refresh_rearms_dead_watcher(qtbot, tmp_path):
    """watch 가 어떤 이유로든 죽어 있어도(디렉터리 목록 비음) 새로고침이 되살린다."""
    tab, p = _make_tab(tmp_path, "v1")
    qtbot.addWidget(tab)
    tab._fs_watcher.removePaths(tab._fs_watcher.directories())
    assert tab._fs_watcher.directories() == []
    tab.refresh_btn.click()
    assert str(p.parent) in tab._fs_watcher.directories()


def test_refresh_blank_tab_is_safe(qtbot):
    """저장 경로 없는 새 문서에서 눌러도 크래시 없이 미리보기 재렌더만 한다."""
    from screen_recorder.ui.markdown_tab import MarkdownTab
    tab = MarkdownTab.from_blank()
    qtbot.addWidget(tab)
    tab.editor.setPlainText("draft")
    rendered = []
    tab.preview.set_content = lambda text, doc_dir=None: rendered.append(text)
    tab.refresh_btn.click()
    assert rendered and rendered[-1] == "draft"
