"""검색 바 시각 확인 — 찾기/바꾸기 바가 안 깨지고 매치 하이라이트가 보이는지 PNG 캡처."""
import os
os.environ["KSTUDIO_SETTINGS_DIR"] = os.path.join(os.environ["TEMP"], "kstudio_dev")
os.environ["KSTUDIO_DISABLE_WEBENGINE"] = "1"   # fallback 미리보기(Chromium 불필요)

from PySide6.QtWidgets import QApplication
from screen_recorder.ui.theme import apply_theme
from screen_recorder.ui.markdown_tab import MarkdownTab

app = QApplication([])
apply_theme(app, "document")
tab = MarkdownTab.from_blank()
tab.editor.setPlainText(
    "# 제목\n\nalpha 베타 alpha 감마 alpha\n다른 줄에도 alpha 가 있고 ALPHA 도 있다.\n"
    "리스트:\n- 첫째 alpha\n- 둘째\n- 셋째 alpha\n"
)
tab.resize(900, 360)
tab.show()

# 찾기+바꾸기 열고 alpha 검색.
tab._search_bar.open_replace()
tab._search_bar.set_query("alpha")
tab._search_bar.set_replacement("ALPHA")

print("match_count :", tab._search_bar.match_count())
print("current     :", tab._search_bar.current_index())
print("extra_sels  :", len(tab.editor.extraSelections()))
tab.grab().save(os.path.join(os.environ["TEMP"], "kstudio_dev", "search_bar.png"))
print("SAVED:", os.path.join(os.environ["TEMP"], "kstudio_dev", "search_bar.png"))
