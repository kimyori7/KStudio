"""다운로드 버튼: 펄스(반짝) 글로우 + (완료/전체) 카운터 + 줄의 X(지우기) 아이콘 PNG 진단."""
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

btn = tb.downloads_button
j1, j2 = FakeJob(), FakeJob()
r1 = btn.add_job(j1, "Me at the zoo")
r2 = btn.add_job(j2, "두 번째 영상")
j1.finished.emit("C:/out/a.mp4")   # 1개 완료 → 줄에 열기/폴더/X 버튼 노출
j2.progress.emit(30, 100)           # 1개 진행 중 → 버튼 "30% (1/2)"

out = Path("logs"); out.mkdir(exist_ok=True)

# 1) 펄스 글로우 최대치 상태로 버튼 영역 grab
btn._apply_glow(1.0)
tb.grab().save(str(out / "_yt_btn_glow.png"))
btn._apply_glow(0.0)

# 2) 카운터 텍스트 확인 + 일반 상태 toolbar
tb.grab().save(str(out / "_yt_btn_counter.png"))

# 3) 팝업 패널(줄 목록) — 완료 줄의 X 아이콘 보이게
panel = btn.panel()
panel.resize(560, 100)
panel.grab().save(str(out / "_yt_btn_popup.png"))

print("button text:", repr(btn.text()))
print("header:", repr(panel._header.text()))
print("saved logs/_yt_btn_glow.png, _yt_btn_counter.png, _yt_btn_popup.png")
