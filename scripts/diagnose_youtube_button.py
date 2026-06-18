"""다운로드 트레이 버튼이 설정 버튼 왼쪽에 뜨는지 + 드롭다운 모양 PNG 진단."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from screen_recorder.ui.theme import apply_theme
from screen_recorder.ui.global_toolbar import GlobalToolbar
from screen_recorder.ui.mode_controller import AppMode


class FakeJob(QObject):
    progress = Signal(object, object)
    title_resolved = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()
    def cancel(self): pass


app = QApplication.instance() or QApplication([])
apply_theme(app, "image")

tb = GlobalToolbar()
tb.set_mode(AppMode.IMAGE)
tb.resize(1400, 48)

job = FakeJob()
row = tb.downloads_button.add_job(job, "Me at the zoo")
job.title_resolved.emit("Me at the zoo")
job.progress.emit(42, 100)

out = Path("logs"); out.mkdir(exist_ok=True)
tb.grab().save(str(out / "_yt_button_toolbar.png"))

# 팝업 내용(패널) 단독 grab — 줄 모양 확인.
panel = tb.downloads_button.panel()
panel.resize(540, 60)
panel.grab().save(str(out / "_yt_button_popup.png"))

print("button visible:", tb.downloads_button.isVisible() or not tb.downloads_button.isHidden())
print("button text:", repr(tb.downloads_button.text()))
print("saved logs/_yt_button_toolbar.png, logs/_yt_button_popup.png")
