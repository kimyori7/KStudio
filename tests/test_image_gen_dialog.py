"""ImageGenDialog 가벼운 시그널 / 상태 전환 테스트.

heavy diffusers 의존성은 mock — UI 상태/시그널 흐름만 검증. qtbot fixture 로
QApplication 관리 (pytest-qt).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal


class _FakeSigBus(QObject):
    load_started = Signal()
    load_finished = Signal()
    generation_started = Signal()
    step_progress = Signal(int, int)
    image_ready = Signal(str)
    generation_failed = Signal(str)
    generation_cancelled = Signal()
    translate_started = Signal()
    translated = Signal(str, str)


class _FakeRuntime:
    def __init__(self) -> None:
        self._bus = _FakeSigBus()
        self.load_started = self._bus.load_started
        self.load_finished = self._bus.load_finished
        self.generation_started = self._bus.generation_started
        self.step_progress = self._bus.step_progress
        self.image_ready = self._bus.image_ready
        self.generation_failed = self._bus.generation_failed
        self.generation_cancelled = self._bus.generation_cancelled
        self.translate_started = self._bus.translate_started
        self.translated = self._bus.translated
        self.calls: list[tuple] = []

    def generate(self, prompt: str, **kw) -> bool:
        self.calls.append(("generate", prompt, kw))
        return True

    def cancel(self) -> None:
        self.calls.append(("cancel",))

    def close(self) -> None:
        self.calls.append(("close",))

    def is_busy(self) -> bool:
        return False

    def set_auto_translate(self, on: bool) -> None:
        self.calls.append(("set_auto_translate", on))


def _write_real_png(path) -> None:
    from PySide6.QtGui import QImage, QColor
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    assert img.save(str(path), "PNG"), f"failed to write test png to {path}"


def test_dialog_starts_uninstalled_when_no_cache(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: False)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg._stack.currentWidget() is dlg._uninstalled_panel


def test_dialog_starts_ready_when_cached(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg._stack.currentWidget() is dlg._ready_panel


def test_dialog_is_non_modal_with_window_flag(qtbot, monkeypatch):
    """비모달 별창 — 떠있어도 메인 도구 자유 사용 가능 (사용자 요구 2026-05-27)."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtCore import Qt

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg.isModal() is False
    # Qt.Window 플래그 — 메인 윈도우와 독립된 별창.
    assert bool(dlg.windowFlags() & Qt.Window)


def test_generate_button_calls_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._ready_panel.prompt_edit.setPlainText("a cat")
    dlg._ready_panel._on_generate_clicked()

    assert any(c[0] == "generate" and c[1] == "a cat" for c in rt.calls)


def test_empty_prompt_does_not_call_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._ready_panel.prompt_edit.setPlainText("   ")
    dlg._ready_panel._on_generate_clicked()

    assert not any(c[0] == "generate" for c in rt.calls)


def test_image_ready_enables_editor_button_and_emits_signal(qtbot, tmp_path, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    fake_png = tmp_path / "out.png"
    _write_real_png(fake_png)

    received: list[str] = []
    dlg.image_for_editor.connect(lambda p: received.append(p))

    dlg._ready_panel.show_result(str(fake_png))
    assert dlg._ready_panel.editor_btn.isEnabled()
    assert dlg._ready_panel.save_btn.isEnabled()

    dlg._ready_panel.editor_btn.click()
    assert received == [str(fake_png)]


def test_video_button_stays_disabled_after_result(qtbot, tmp_path, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    fake_png = tmp_path / "x.png"
    _write_real_png(fake_png)
    dlg._ready_panel.show_result(str(fake_png))

    assert dlg._ready_panel.editor_btn.isEnabled()
    assert dlg._ready_panel.save_btn.isEnabled()
    assert not dlg._ready_panel.video_btn.isEnabled()


def test_auto_translate_checkbox_default_on_and_toggles_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    rt.translate_calls = []
    rt.set_auto_translate = lambda on: rt.translate_calls.append(on)
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    assert dlg._ready_panel.auto_translate_check.isChecked()
    dlg._ready_panel.auto_translate_check.setChecked(False)
    assert rt.translate_calls == [False]
    dlg._ready_panel.auto_translate_check.setChecked(True)
    assert rt.translate_calls == [False, True]


def test_translated_label_shows_after_translation(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    rt.set_auto_translate = lambda on: None
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)
    dlg._ensure_runtime()

    assert not dlg._ready_panel.translated_label.isVisible() or \
           dlg._ready_panel.translated_label.text() == ""

    rt._bus.translated.emit("고양이", "a calico cat")
    assert "a calico cat" in dlg._ready_panel.translated_label.text()


def test_generate_button_disables_immediately_on_click(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._ready_panel.prompt_edit.setPlainText("test")
    assert dlg._ready_panel.generate_btn.isEnabled()
    dlg._ready_panel._on_generate_clicked()
    assert not dlg._ready_panel.generate_btn.isEnabled()
    assert dlg._ready_panel.cancel_btn.isEnabled()


def test_progress_bar_indeterminate_during_load(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    dlg._ready_panel.set_load_state(True)
    assert dlg._ready_panel.progress_bar.maximum() == 0
    assert not dlg._ready_panel.generate_btn.isEnabled()
    assert "10~60초" in dlg._ready_panel.status_label.text()


def test_progress_bar_becomes_determinate_on_first_step(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    dlg._ready_panel.set_generating(True)
    assert dlg._ready_panel.progress_bar.maximum() == 0

    dlg._ready_panel.set_step(1, 20)
    assert dlg._ready_panel.progress_bar.maximum() == 100
    assert dlg._ready_panel.progress_bar.value() == 5
    assert "Step 1/20" in dlg._ready_panel.status_label.text()


def test_uninstalled_download_button_signals_dialog(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: False)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    calls: list[str] = []
    monkeypatch.setattr(dlg, "_start_download", lambda: calls.append("start"))

    panel = dlg._uninstalled_panel
    panel.download_clicked.emit()
    assert calls == ["start"]


def test_close_emits_closed_signal(qtbot, monkeypatch):
    """X 닫기 → closed 시그널 발화 (main_window 가 메뉴 체크 해제)."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    fired = []
    dlg.closed.connect(lambda: fired.append(True))
    dlg.close()
    assert fired == [True]
