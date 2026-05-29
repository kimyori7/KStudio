"""문서/미리보기 Ctrl+C 회귀 — 이미지 편집용 Ctrl+C/X/A/D 단축키(WindowShortcut)는
EditTab 활성 시에만 켜져야 텍스트 위젯(마크다운 에디터·미리보기)·영상 타임라인이 키를 받는다.

판별 근거(scripts/diagnose_copy_shortcut.py): 편집 가능한 에디터는 ShortcutOverride 를
스스로 accept 해 원래도 Ctrl+C 가 동작하지만, 읽기 전용 미리보기(QTextBrowser/WebEngine)는
accept 안 해 WindowShortcut 에 키를 빼앗긴다 → 비-EditTab 일 때 비활성화로 해결.
disabled QShortcut 은 shortcut 매칭에 참여하지 않으므로 키가 포커스 위젯으로 정상 전달된다.
"""
from PySide6.QtGui import QImage


def _img() -> QImage:
    img = QImage(20, 20, QImage.Format_ARGB32)
    img.fill(0xFF112233)
    return img


def _win(qtbot, tmp_path):
    from screen_recorder.ui.main_window import MainWindow
    from screen_recorder.core.settings import AppSettings
    s = AppSettings()
    s.screenshot.save_dir = str(tmp_path)
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    win = MainWindow(s, f)
    qtbot.addWidget(win)
    return win


def test_image_clipboard_shortcuts_enabled_on_edittab(qtbot, tmp_path):
    # 이미지 EditTab 활성 → Ctrl+C/X/A/D 켜짐 (이미지 복사/잘라내기/선택 유지).
    win = _win(qtbot, tmp_path)
    win._on_screenshot_captured(_img(), "region")
    assert win._image_clipboard_shortcuts
    assert all(sc.isEnabled() for sc in win._image_clipboard_shortcuts)
    win.close()


def test_image_clipboard_shortcuts_disabled_in_document_mode(qtbot, tmp_path):
    # 문서(md) 탭 활성 → 단축키 꺼짐 → 에디터/미리보기가 네이티브 Ctrl+C 를 받음.
    win = _win(qtbot, tmp_path)
    p = tmp_path / "d.md"
    p.write_text("# hi\n\nsome **text** here", encoding="utf-8")
    win._open_path(p)
    assert all(not sc.isEnabled() for sc in win._image_clipboard_shortcuts)
    win.close()
