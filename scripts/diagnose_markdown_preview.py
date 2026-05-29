"""Markdown 미리보기 실제 WebEngine 렌더 검증 (소스 모드).

QtWebEngine(Chromium)으로 template 로드 → JS 주입 → DOM 읽기로 렌더 결과를 확인한다.
QWebEngineView 픽셀 grab 은 GPU 합성이라 blank 가 잦으므로, 실제 검증은 페이지의
#content innerHTML 을 runJavaScript 로 되읽어 핵심 요소(h1/table/code/체크박스)가
들어갔는지 확인하는 방식으로 한다.

사용:  .venv\\Scripts\\python.exe scripts\\diagnose_markdown_preview.py
주의:  KSTUDIO_DISABLE_WEBENGINE 환경변수가 설정돼 있으면 안 됨 (실제 WebEngine 사용).
"""
import os
import sys
from pathlib import Path

# 실제 WebEngine 사용 — fallback 강제 플래그 해제.
os.environ.pop("KSTUDIO_DISABLE_WEBENGINE", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui.markdown.preview import MarkdownPreview  # noqa: E402

SAMPLE = """# 설치 가이드

**굵게** 와 *기울임*, `inline code`, [링크](https://example.com).

- [x] 완료한 항목
- [ ] 남은 항목

| OS | 명령 |
|----|------|
| Win | pip install |

```python
def run():
    return 1
```

> 인용문 블록
"""

EXPECT = ["<h1", "설치 가이드", "<table", "<strong>", "checkbox", "highlight"]


def main() -> int:
    app = QApplication(sys.argv)
    pv = MarkdownPreview()
    pv.resize(900, 700)
    pv.show()
    pv.set_content(SAMPLE, None)

    result = {"ok": False, "html": ""}

    def check():
        renderer = pv._renderer
        view = renderer.widget()
        page = getattr(view, "page", lambda: None)()
        if page is None:
            print("FALLBACK 렌더러 사용 중 (WebEngine 불가) — 이 검증은 무의미.")
            app.quit()
            return

        def got(html):
            result["html"] = html or ""
            missing = [e for e in EXPECT if e not in result["html"]]
            result["ok"] = not missing
            print("=== #content innerHTML (앞 600자) ===")
            print(result["html"][:600])
            print("=== 검증 ===")
            if missing:
                print("FAIL — 누락:", missing)
            else:
                print("PASS — h1/table/strong/checkbox/highlight 모두 렌더됨")
            # 픽셀 grab 도 시도 (참고용 — blank 일 수 있음).
            try:
                view.grab().save("test_markdown_preview.png")
                print("(참고) test_markdown_preview.png 저장 시도")
            except Exception as e:
                print("grab 실패(무시):", e)
            app.quit()

        page.runJavaScript("document.getElementById('content').innerHTML", got)

    # 로드 + 디바운스(300ms) + 렌더 여유.
    QTimer.singleShot(2500, check)
    # 안전장치 — 콜백이 안 와도(헤드리스 등) 7초 후 강제 종료해 행 방지.
    def _timeout_quit():
        if not result["html"]:
            print("TIMEOUT — WebEngine 렌더 콜백이 오지 않음 (실제 디스플레이 필요)."
                  " 이 환경에선 시각 검증 불가 — 빌드된 .exe 에서 수동 확인 요망.")
        app.quit()
    QTimer.singleShot(7000, _timeout_quit)
    app.exec()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
