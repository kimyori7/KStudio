"""ImageGenDock 가벼운 시그널 / 상태 전환 테스트.

heavy diffusers 의존성은 mock — UI 상태/시그널 흐름만 검증. qtbot fixture 로
QApplication 관리 (pytest-qt).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal


class _FakeSigBus(QObject):
    """ImageGenRuntime 의 Signal 들을 보유."""
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
    """ImageGenRuntime 의 API 만 모방한 더미 — ImageGenDock 인스턴스화용."""

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
    """Qt 의 QImage.save 로 진짜 PNG 작성 — 인라인 bytes 의 CRC 오류 회피."""
    from PySide6.QtGui import QImage, QColor
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    assert img.save(str(path), "PNG"), f"failed to write test png to {path}"


def test_dock_starts_uninstalled_when_no_cache(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: False)
    dock = mod.ImageGenDock(runtime=_FakeRuntime())
    qtbot.addWidget(dock)

    assert dock._stack.currentWidget() is dock._uninstalled_panel


def test_dock_starts_ready_when_cached(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dock = mod.ImageGenDock(runtime=_FakeRuntime())
    qtbot.addWidget(dock)

    assert dock._stack.currentWidget() is dock._ready_panel


def test_generate_button_calls_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    dock._ready_panel.prompt_edit.setPlainText("a cat")
    dock._ready_panel._on_generate_clicked()

    assert any(c[0] == "generate" and c[1] == "a cat" for c in rt.calls)


def test_empty_prompt_does_not_call_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dock as mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    dock._ready_panel.prompt_edit.setPlainText("   ")
    dock._ready_panel._on_generate_clicked()

    assert not any(c[0] == "generate" for c in rt.calls)


def test_image_ready_enables_editor_button_and_emits_signal(qtbot, tmp_path, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    fake_png = tmp_path / "out.png"
    _write_real_png(fake_png)

    received: list[str] = []
    dock.image_for_editor.connect(lambda p: received.append(p))

    dock._ready_panel.show_result(str(fake_png))
    assert dock._ready_panel.editor_btn.isEnabled()
    assert dock._ready_panel.save_btn.isEnabled()

    dock._ready_panel.editor_btn.click()
    assert received == [str(fake_png)]


def test_video_button_stays_disabled_after_result(qtbot, tmp_path, monkeypatch):
    """video_btn 은 Phase 6+ 까지 항상 비활성."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    fake_png = tmp_path / "x.png"
    _write_real_png(fake_png)
    dock._ready_panel.show_result(str(fake_png))

    assert dock._ready_panel.editor_btn.isEnabled()
    assert dock._ready_panel.save_btn.isEnabled()
    assert not dock._ready_panel.video_btn.isEnabled()


def test_auto_translate_checkbox_default_on_and_toggles_runtime(qtbot, monkeypatch):
    """체크박스 기본 ON + 토글 시 runtime.set_auto_translate 호출."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    # FakeRuntime 에 set_auto_translate 추가.
    rt.translate_calls = []
    rt.set_auto_translate = lambda on: rt.translate_calls.append(on)
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    assert dock._ready_panel.auto_translate_check.isChecked()
    dock._ready_panel.auto_translate_check.setChecked(False)
    assert rt.translate_calls == [False]
    dock._ready_panel.auto_translate_check.setChecked(True)
    assert rt.translate_calls == [False, True]


def test_translated_label_shows_after_translation(qtbot, monkeypatch):
    """runtime 이 translated 시그널 emit → 패널이 영어 결과 표시."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    rt.set_auto_translate = lambda on: None
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)
    # _ensure_runtime 강제 (와이어링).
    dock._ensure_runtime()

    assert not dock._ready_panel.translated_label.isVisible() or \
           dock._ready_panel.translated_label.text() == ""

    rt._bus.translated.emit("고양이", "a calico cat")
    assert "a calico cat" in dock._ready_panel.translated_label.text()


def test_generate_button_disables_immediately_on_click(qtbot, monkeypatch):
    """클릭 즉시 비활성 — runtime 시그널 도착 전 race 회피 (2026-05-27)."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    dock._ready_panel.prompt_edit.setPlainText("test")
    assert dock._ready_panel.generate_btn.isEnabled()
    dock._ready_panel._on_generate_clicked()
    assert not dock._ready_panel.generate_btn.isEnabled()
    assert dock._ready_panel.cancel_btn.isEnabled()


def test_progress_bar_indeterminate_during_load(qtbot, monkeypatch):
    """load 중엔 progress_bar 가 indeterminate (range 0~0) — '멈춤' 오해 방지."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dock = mod.ImageGenDock(runtime=_FakeRuntime())
    qtbot.addWidget(dock)

    dock._ready_panel.set_load_state(True)
    # offscreen 플랫폼에선 isVisible() 이 parent 의 hide 상태로 False 일 수 있어 maximum 만 검증.
    assert dock._ready_panel.progress_bar.maximum() == 0   # indeterminate
    assert not dock._ready_panel.generate_btn.isEnabled()
    assert "10~60초" in dock._ready_panel.status_label.text()


def test_progress_bar_becomes_determinate_on_first_step(qtbot, monkeypatch):
    """첫 step 도달 시 indeterminate → 0~100 determinate 전환."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: True)
    dock = mod.ImageGenDock(runtime=_FakeRuntime())
    qtbot.addWidget(dock)

    dock._ready_panel.set_generating(True)
    assert dock._ready_panel.progress_bar.maximum() == 0

    dock._ready_panel.set_step(1, 20)
    assert dock._ready_panel.progress_bar.maximum() == 100
    assert dock._ready_panel.progress_bar.value() == 5
    assert "Step 1/20" in dock._ready_panel.status_label.text()


def test_uninstalled_download_button_signals_dock(qtbot, monkeypatch):
    """미설치 패널의 다운로드 버튼이 _start_download 호출."""
    from screen_recorder.ui.image_gen import image_gen_dock as mod

    monkeypatch.setattr(mod, "_is_model_cached", lambda repo: False)
    rt = _FakeRuntime()
    dock = mod.ImageGenDock(runtime=rt)
    qtbot.addWidget(dock)

    calls: list[str] = []
    monkeypatch.setattr(dock, "_start_download", lambda: calls.append("start"))

    # 미설치 패널의 다운로드 버튼을 찾아 클릭.
    panel = dock._uninstalled_panel
    panel.download_clicked.emit()
    assert calls == ["start"]
