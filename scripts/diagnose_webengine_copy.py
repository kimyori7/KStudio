"""WebEngine 미리보기가 Ctrl+C(=Copy WebAction)로 선택 텍스트를 복사하는지 검증.

라우팅(disabled QShortcut → 키가 위젯으로)은 Qt 계약상 보장 → 여기선 'WebEngine 자체가
선택을 클립보드로 복사하는가' 만 확인. 키 라우팅 대신 triggerAction(Copy) 직접 호출
(헤드리스 포커스 불안정 회피). 메모리: singleShot + exec, 동기 대기 금지.
"""
import os
os.environ.setdefault("KSTUDIO_SETTINGS_DIR", os.path.join(os.environ["TEMP"], "kstudio_dev"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

app = QApplication([])
view = QWebEngineView()
result = {}


def on_load(ok):
    if not ok:
        result["err"] = "loadFinished(False)"
        app.quit()
        return
    # 본문 전체 선택 → Copy 액션 → 약간의 지연 후 클립보드 확인.
    view.page().runJavaScript(
        "getSelection().selectAllChildren(document.body); getSelection().toString();",
        lambda sel: _after_select(sel),
    )


def _after_select(sel):
    result["selected"] = sel
    view.page().triggerAction(QWebEnginePage.WebAction.Copy)
    result["tries"] = 0
    _poll()


def _poll():
    txt = QApplication.clipboard().text()
    result["tries"] += 1
    if txt.strip() or result["tries"] > 20:   # 최대 ~2초 폴링
        result["clipboard"] = txt
        app.quit()
        return
    QTimer.singleShot(100, _poll)


view.resize(400, 200)
view.show()
view.raise_()
view.activateWindow()
view.loadFinished.connect(on_load)
view.setHtml("<p>hello world from preview</p>")
QApplication.clipboard().clear()
QTimer.singleShot(10000, app.quit)  # 안전 타임아웃
app.exec()

print("selected  :", repr(result.get("selected")))
print("clipboard :", repr(result.get("clipboard")))
print("err       :", result.get("err"))
ok = (result.get("clipboard") or "").strip() == "hello world from preview"
print("WEBENGINE_COPY_OK:", ok)
