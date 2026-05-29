"""WebEngine pre-warm 생성 경로 스모크 — last_mode=document + WebEngine 켠 상태에서
MainWindow 구성 시 1×1 QWebEngineView 가 예외 없이 만들어지는지(테스트는 conftest 가
WebEngine 을 꺼서 못 타는 경로). 실제 settings 오염 방지로 KSTUDIO_SETTINGS_DIR 격리.
"""
import os
os.environ["KSTUDIO_SETTINGS_DIR"] = os.path.join(os.environ["TEMP"], "kstudio_dev")
os.environ.pop("KSTUDIO_DISABLE_WEBENGINE", None)  # WebEngine 켜기

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from screen_recorder.core.settings import AppSettings
from screen_recorder.app.main import build_main_window

app = QApplication([])
s = AppSettings()
s.preferences.last_mode = "document"
win = build_main_window(settings=s)
pw = win._webengine_prewarm
print("prewarm type :", type(pw).__name__ if pw is not None else None)
print("prewarm size :", (pw.width(), pw.height()) if pw is not None else None)
print("PREWARM_CREATED:", pw is not None)

# 실사용 경로: show() + 첫 show 의 지연 dock 복원 + pre-warm 자식이 동시에 materialize.
# 이 세션에 문서 모드 첫 show 세그폴트 전력이 있어 크래시 안 나는지 실제로 확인.
win.show()
QTimer.singleShot(1500, app.quit)
app.exec()
print("SHOWN_OK")   # 여기 도달 = 실 경로 첫 show 크래시 없음
win.close()
