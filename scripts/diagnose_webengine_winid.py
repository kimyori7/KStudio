"""WebEngine 첫 진입 깜빡임 오라클 — 최상위 창의 네이티브 핸들(winId/HWND)이
첫 문서(WebEngine) 열 때 재생성되는지 측정한다.

가설(확정): "창이 닫혔다 열림" = 첫 QWebEngineView 실현 시 최상위 창의 HWND 재생성.
→ winId 변화로 헤드리스 검출 가능 (시각 grab 불요).

**중첩 이벤트 루프 금지**: 보이는 창에서 WebEngine 을 만든 직후 nested QEventLoop 로
블록하면 GPU 프로세스 핸드셰이크와 데드락(행)이 관측됨 — 실제 앱(메인 app.exec())엔
없는 아티팩트. 그래서 모든 단계를 단일 app.exec() 위에서 QTimer.singleShot 체인으로
돌린다(실제 사용자 동작이 이벤트 루프 턴마다 분리되는 것과 동일).

시나리오 (각각 별 프로세스로 — WebEngine 글로벌 init 은 프로세스당 1회):
  current  : last_mode=document → startup pre-warm 실행 (show 이전 생성)
  nopre    : last_mode=image    → pre-warm 스킵 (baseline: 문서 열기가 winId 바꾸나?)
  switch   : last_mode=image 로 켜서 startup 스킵 → 문서 모드 전환(_on_mode_changed 의
             force warm, 실제 fix 경로) → 그 다음 문서 열기. winId 안정성 검증.

사용:  python scripts/diagnose_webengine_winid.py <scenario>
"""
import os
import sys
import threading

# 실제 settings 오염 방지 (메모리: dev 앱 실행이 사용자 settings 덮어씀).
os.environ["KSTUDIO_SETTINGS_DIR"] = os.path.join(os.environ["TEMP"], "kstudio_winid_probe")
os.environ.pop("KSTUDIO_DISABLE_WEBENGINE", None)  # WebEngine 켜기

# 하드 워치독 — 별도 OS 스레드라 Qt 이벤트 루프가 블록(행)돼도 작동한다. 어떤 경우에도
# 창이 화면에 남지 않도록 강제 종료. 정상 경로는 그 전에 os._exit(0).
threading.Timer(15.0, lambda: (sys.stderr.write("WATCHDOG FIRED\n"), os._exit(3))).start()

from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QApplication

scenario = sys.argv[1] if len(sys.argv) > 1 else "current"

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
app = QApplication([])

from screen_recorder.core.settings import AppSettings
from screen_recorder.app.main import build_main_window
from screen_recorder.ui.mode_controller import AppMode


def log(msg: str) -> None:
    print(f"[{scenario}] {msg}")
    sys.stdout.flush()


s = AppSettings()
s.preferences.last_mode = "document" if scenario == "current" else "image"
win = build_main_window(settings=s)
win.show()

_state = {"before": None}


def step_switch():
    if scenario == "switch":
        log("-> set_mode(DOCUMENT)")
        win.mode_controller.set_mode(AppMode.DOCUMENT)
        log("<- set_mode returned (no block = 실제 앱 freeze 없음)")
    QTimer.singleShot(1200, step_capture_before)


def step_capture_before():
    _state["before"] = int(win.winId())
    pw = getattr(win, "_webengine_prewarm", None)
    log(f"prewarm      = {type(pw).__name__ if pw else None}")
    log(f"winId_before = {_state['before']}")
    tmp = Path(os.environ["TEMP"]) / "kstudio_winid_probe_doc.md"
    tmp.write_text("# probe\n\n본문 텍스트 한 줄.\n", encoding="utf-8")
    log("-> open_markdown_path")
    win._open_markdown_path(tmp)
    log("<- open returned")
    QTimer.singleShot(2000, step_capture_after)


def step_capture_after():
    after = int(win.winId())
    log(f"winId_after  = {after}")
    log(f"WINID_CHANGED = {_state['before'] != after}")
    os._exit(0)   # teardown segfault/hang 우회 — 측정값 출력 후 즉시 종료


QTimer.singleShot(1200, step_switch)
app.exec()
