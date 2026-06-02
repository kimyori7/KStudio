"""삭제 표시 시각 확인 — 라이브러리 행(취소선+✕)과 탭(취소선)을 PNG 로 grab."""
import sys
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from screen_recorder.ui.library_model import LibraryModel, EntryKind
from screen_recorder.ui.docks.library_panel import LibraryPanel
from screen_recorder.ui.tab_area import TabArea
from screen_recorder.ui.mode_controller import ModeController
from screen_recorder.core.settings import PlayerSettings, PlayerHotkeys


def _img(c=0xFF334455):
    im = QImage(48, 32, QImage.Format_ARGB32); im.fill(c); return im


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    # 라이브러리: 정상 1 + 삭제 1
    m = LibraryModel()
    a = m.add(EntryKind.IMAGE, thumbnail=_img(), source_label="region",
              display_name="alive_screenshot.png")
    b = m.add(EntryKind.IMAGE, thumbnail=_img(0xFF553333), source_label="region",
              display_name="deleted_screenshot.png")
    panel = LibraryPanel(m)
    panel.resize(300, 130)
    panel.show()
    app.processEvents()
    m.set_missing(b.id, True)
    app.processEvents()
    panel.grab().save("diag_missing_library.png", "PNG")

    # 탭: 정상 1 + 삭제 1
    ta = TabArea(ModeController(), player_settings=PlayerSettings(),
                 player_hotkeys=PlayerHotkeys())
    ta.add_screenshot(image=_img(), source_label="region", entry_id=1)
    ta.add_screenshot(image=_img(), source_label="region", entry_id=2)
    ta._tab_base_labels  # noop
    ta.resize(420, 60)
    ta.show()
    app.processEvents()
    ta.set_entry_deleted(2, True)
    app.processEvents()
    ta.tabBar().grab().save("diag_missing_tabbar.png", "PNG")

    print("saved diag_missing_library.png, diag_missing_tabbar.png")


if __name__ == "__main__":
    main()
