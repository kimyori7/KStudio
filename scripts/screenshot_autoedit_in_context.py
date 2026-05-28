"""실제 VideoTab 헤더 (자동 편집 버튼 포함) 를 PNG 로 캡처 — 컨텍스트 검증."""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from screen_recorder.ui.theme import apply_theme   # noqa: E402
from screen_recorder.core.settings import PlayerHotkeys, PlayerSettings  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app, "video")

    # 작은 테스트 영상 — 라이브러리에 있는 첫 파일 찾기. 없으면 dummy path 로 시도.
    candidates = [
        Path("E:/KStudio_Image/Video"),
        Path.home() / "Videos",
    ]
    test_video: Path | None = None
    for d in candidates:
        if d.exists():
            for f in d.glob("*.mp4"):
                test_video = f
                break
            if test_video is not None:
                break

    if test_video is None:
        # VideoTab 이 실제 영상을 요구하지 않을 수도 있으니 fake path 로도 시도.
        test_video = Path("nonexistent.mp4")

    from screen_recorder.ui.video_tab import VideoTab
    tab = VideoTab(
        path=test_video,
        source_label=test_video.name,
        duration_ms=120000,
        player_settings=PlayerSettings(),
        player_hotkeys=PlayerHotkeys(),
        thumbnail=None,
    )
    tab.setFixedSize(800, 400)
    tab.show()
    app.processEvents()
    app.processEvents()  # layout 안정용 2회.

    # 헤더만 잘라서 저장.
    header = tab._tab_header
    print(f"header size: {header.size().width()}x{header.size().height()}")
    print(f"autoedit btn size: {tab._autoedit_button.size().width()}x{tab._autoedit_button.size().height()}")
    print(f"autoedit btn sizeHint: {tab._autoedit_button.sizeHint().width()}x{tab._autoedit_button.sizeHint().height()}")

    header_png = ROOT / "test_header.png"
    full_png = ROOT / "test_full_tab.png"
    header.grab().save(str(header_png))
    tab.grab().save(str(full_png))
    print(f"\n→ 헤더 캡처: {header_png}")
    print(f"→ 탭 전체 캡처: {full_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
