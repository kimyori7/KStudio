"""ImageGenDialog 시그널 / UI 상태 전환 테스트.

heavy diffusers 의존성은 mock — UI 상태/시그널 흐름만 검증.

설계 (2026-05-27): 단일 `_panel` 구조 — 모드 (t2i/i2i) 라디오 + 모델 카탈로그
picker + (i2i 시) reference 이미지 슬롯 + strength 슬라이더.
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

    def set_model(self, model_id: str) -> None:
        self.calls.append(("set_model", model_id))


def _write_real_png(path) -> None:
    from PySide6.QtGui import QImage, QColor
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    assert img.save(str(path), "PNG"), f"failed to write test png to {path}"


def _all_cached(*_args, **_kw):
    return True


def _none_cached(*_args, **_kw):
    return False


def test_dialog_is_non_modal_with_window_flag(qtbot, monkeypatch):
    """비모달 별창 — 떠있어도 메인 도구 자유 사용 가능."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtCore import Qt

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg.isModal() is False
    assert bool(dlg.windowFlags() & Qt.Window)


def test_dialog_populates_catalog_in_quality_order(qtbot, monkeypatch):
    """모델 dropdown 은 카탈로그를 quality_rank 순으로 채움."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from screen_recorder.image_gen.model_catalog import t2i_models

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    expected_order = [e.id for e in t2i_models()]
    actual_order = [
        dlg._panel.model_combo.itemData(i)
        for i in range(dlg._panel.model_combo.count())
    ]
    assert actual_order == expected_order


def test_mode_toggle_shows_i2i_group(qtbot, monkeypatch):
    """i2i 라디오 선택 시 원본 이미지 그룹 표시 + dropdown 도 i2i 모델만."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from screen_recorder.image_gen.model_catalog import i2i_models

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    # qtbot.addWidget 만으로는 show() 안 함 → isVisible 대신 hidden flag 검사.
    assert dlg._panel.i2i_group.isHidden() is True
    dlg._panel.i2i_radio.setChecked(True)
    assert dlg._panel.i2i_group.isHidden() is False

    expected_i2i = [e.id for e in i2i_models()]
    actual = [
        dlg._panel.model_combo.itemData(i)
        for i in range(dlg._panel.model_combo.count())
    ]
    assert actual == expected_i2i
    # PixArt 는 i2i 미지원 → dropdown 에 없어야 함.
    assert "pixart-sigma-1024ms" not in actual


def test_uncached_model_shows_download_button(qtbot, monkeypatch):
    """모델 미설치 → 다운로드 버튼 visible + 생성 버튼 비활성."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _none_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg._panel.download_btn.isHidden() is False
    assert not dlg._panel.generate_btn.isEnabled()


def test_cached_model_enables_generate(qtbot, monkeypatch):
    """모델 캐시 됨 → 다운로드 버튼 숨김 + 생성 버튼 활성."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    assert dlg._panel.download_btn.isHidden() is True
    assert dlg._panel.generate_btn.isEnabled()


def test_model_changed_calls_runtime_set_model(qtbot, monkeypatch):
    """dropdown 변경 시 runtime.set_model 호출."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    # populate 시점에 첫 set_model 도 호출됐을 수 있음 — 이후 dropdown 변경.
    rt.calls.clear()
    if dlg._panel.model_combo.count() >= 2:
        dlg._panel.model_combo.setCurrentIndex(1)
        assert any(c[0] == "set_model" for c in rt.calls)


def test_download_button_emits_download_requested(qtbot, monkeypatch):
    """다운로드 버튼 클릭 → download_requested 시그널 + ModelDownloadJob start."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _none_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    captured: list[str] = []
    monkeypatch.setattr(dlg, "_on_download_requested", lambda mid: captured.append(mid))
    # 시그널 재배선 — _on_download_requested 가 이미 connect 돼 있어 가짜로 갈음.
    try:
        dlg._panel.download_requested.disconnect()
    except RuntimeError:
        pass
    dlg._panel.download_requested.connect(dlg._on_download_requested)

    dlg._panel.download_btn.click()
    assert captured  # 한 개 이상 emit


def test_generate_button_calls_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._panel.prompt_edit.setPlainText("a cat")
    dlg._panel._on_generate_clicked()

    assert any(c[0] == "generate" and c[1] == "a cat" for c in rt.calls)


def test_empty_prompt_does_not_call_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._panel.prompt_edit.setPlainText("   ")
    dlg._panel._on_generate_clicked()
    assert not any(c[0] == "generate" for c in rt.calls)


def test_i2i_without_reference_image_blocks_generate(qtbot, monkeypatch):
    """i2i 모드 + 원본 이미지 미선택 → generate 차단."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._panel.i2i_radio.setChecked(True)
    dlg._panel.prompt_edit.setPlainText("turn it into watercolor")
    dlg._panel._on_generate_clicked()
    assert not any(c[0] == "generate" for c in rt.calls)


def test_i2i_with_reference_passes_params(qtbot, tmp_path, monkeypatch):
    """i2i + reference 선택됨 → runtime.generate 에 reference_image + strength 전달."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from pathlib import Path

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    fake_png = tmp_path / "ref.png"
    _write_real_png(fake_png)
    dlg._panel.i2i_radio.setChecked(True)
    dlg._panel._reference_path = Path(fake_png)
    dlg._panel.strength_slider.setValue(45)   # 0.45
    dlg._panel.prompt_edit.setPlainText("turn it into watercolor")
    dlg._panel._on_generate_clicked()

    gen_calls = [c for c in rt.calls if c[0] == "generate"]
    assert gen_calls
    _, prompt, kw = gen_calls[-1]
    assert prompt == "turn it into watercolor"
    assert kw["reference_image"] == Path(fake_png)
    assert abs(kw["strength"] - 0.45) < 1e-6


def test_image_ready_enables_editor_button_and_emits_signal(qtbot, tmp_path, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    fake_png = tmp_path / "out.png"
    _write_real_png(fake_png)

    received: list[str] = []
    dlg.image_for_editor.connect(lambda p: received.append(p))

    dlg._panel.show_result(str(fake_png))
    assert dlg._panel.editor_btn.isEnabled()
    assert dlg._panel.save_btn.isEnabled()

    dlg._panel.editor_btn.click()
    assert received == [str(fake_png)]


def test_video_button_stays_disabled_after_result(qtbot, tmp_path, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    fake_png = tmp_path / "x.png"
    _write_real_png(fake_png)
    dlg._panel.show_result(str(fake_png))

    assert dlg._panel.editor_btn.isEnabled()
    assert dlg._panel.save_btn.isEnabled()
    assert not dlg._panel.video_btn.isEnabled()


def test_auto_translate_checkbox_default_on_and_toggles_runtime(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    rt.translate_calls = []
    rt.set_auto_translate = lambda on: rt.translate_calls.append(on)
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    assert dlg._panel.auto_translate_check.isChecked()
    dlg._panel.auto_translate_check.setChecked(False)
    assert rt.translate_calls == [False]
    dlg._panel.auto_translate_check.setChecked(True)
    assert rt.translate_calls == [False, True]


def test_translated_label_shows_after_translation(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    rt.set_auto_translate = lambda on: None
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)
    dlg._ensure_runtime()

    rt._bus.translated.emit("고양이", "a calico cat")
    assert "a calico cat" in dlg._panel.translated_label.text()


def test_generate_button_disables_immediately_on_click(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    rt = _FakeRuntime()
    dlg = mod.ImageGenDialog(runtime=rt)
    qtbot.addWidget(dlg)

    dlg._panel.prompt_edit.setPlainText("test")
    assert dlg._panel.generate_btn.isEnabled()
    dlg._panel._on_generate_clicked()
    assert not dlg._panel.generate_btn.isEnabled()
    assert dlg._panel.cancel_btn.isEnabled()


def test_progress_bar_indeterminate_during_load(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    dlg._panel.set_load_state(True)
    assert dlg._panel.progress_bar.maximum() == 0
    assert not dlg._panel.generate_btn.isEnabled()
    assert "10~60초" in dlg._panel.status_label.text()


def test_progress_bar_becomes_determinate_on_first_step(qtbot, monkeypatch):
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    dlg._panel.set_generating(True)
    assert dlg._panel.progress_bar.maximum() == 0

    dlg._panel.set_step(1, 20)
    assert dlg._panel.progress_bar.maximum() == 100
    assert dlg._panel.progress_bar.value() == 5
    assert "Step 1/20" in dlg._panel.status_label.text()


def test_recommended_resolution_marked_in_dropdown(qtbot, monkeypatch):
    """해상도 dropdown 에서 모델의 default_resolution 항목에 '(추천)' 라벨."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from screen_recorder.image_gen.model_catalog import by_id

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    entry = by_id(dlg._panel.model_combo.currentData())
    assert entry is not None
    default_res = entry.default_resolution

    # default_resolution 항목 라벨에 "(추천)" 포함, 나머지엔 없음.
    found_rec = False
    for i in range(dlg._panel.res_combo.count()):
        value = dlg._panel.res_combo.itemData(i)
        text = dlg._panel.res_combo.itemText(i)
        if value == default_res:
            assert "(추천)" in text
            found_rec = True
        else:
            assert "(추천)" not in text
    assert found_rec


def test_clipboard_paste_sets_reference_and_switches_to_i2i(qtbot, monkeypatch):
    """Ctrl+V → 클립보드 이미지 → reference path 세팅 + i2i 모드 자동 전환."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtGui import QGuiApplication, QImage, QColor

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    # 초기: t2i 모드, reference 없음.
    assert dlg._panel.t2i_radio.isChecked()
    assert dlg._panel._reference_path is None

    # 클립보드에 빨간색 32×32 이미지 set.
    test_img = QImage(32, 32, QImage.Format_ARGB32)
    test_img.fill(QColor(255, 0, 0))
    QGuiApplication.clipboard().setImage(test_img)

    # paste handler 직접 호출 (shortcut.activated 와 동등).
    ok = dlg._panel.paste_reference_from_clipboard()
    assert ok is True
    assert dlg._panel._reference_path is not None
    assert dlg._panel._reference_path.exists()
    assert dlg._panel.i2i_radio.isChecked()   # i2i 모드 자동 전환
    assert "클립보드" in dlg._panel.status_label.text()


def test_clipboard_paste_returns_false_when_no_image(qtbot, monkeypatch):
    """클립보드에 이미지 없으면 False — 호출자가 fallback 가능."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtGui import QGuiApplication

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    QGuiApplication.clipboard().clear()
    QGuiApplication.clipboard().setText("just text, no image")

    ok = dlg._panel.paste_reference_from_clipboard()
    assert ok is False
    assert dlg._panel._reference_path is None


def test_paste_shortcut_routes_to_prompt_when_prompt_focused(qtbot, monkeypatch):
    """prompt_edit 에 focus 있으면 텍스트 paste 가 우선 — 이미지 paste 안 함."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod
    from PySide6.QtGui import QGuiApplication, QImage, QColor

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)
    dlg.show()   # focus 동작에 widget visible 필요.

    # 클립보드에 이미지 + 텍스트 둘다 (PySide 가 image 우선이지만 prompt focus 면 텍스트 paste).
    img = QImage(8, 8, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 255))
    QGuiApplication.clipboard().clear()
    QGuiApplication.clipboard().setImage(img)
    QGuiApplication.clipboard().setText("hello prompt")  # setText 가 image 덮을 수 있음

    # prompt_edit 에 focus 설정.
    dlg._panel.prompt_edit.setFocus()
    dlg._handle_paste_shortcut()

    # reference 는 안 들어감 (텍스트 paste 경로).
    assert dlg._panel._reference_path is None
    dlg.hide()


def test_close_emits_closed_signal(qtbot, monkeypatch):
    """X 닫기 → closed 시그널 발화 (main_window 가 메뉴 체크 해제)."""
    from screen_recorder.ui.image_gen import image_gen_dialog as mod

    monkeypatch.setattr(mod, "_is_model_cached", _all_cached)
    dlg = mod.ImageGenDialog(runtime=_FakeRuntime())
    qtbot.addWidget(dlg)

    fired = []
    dlg.closed.connect(lambda: fired.append(True))
    dlg.close()
    assert fired == [True]
