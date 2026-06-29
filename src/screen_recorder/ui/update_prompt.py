"""업데이트 안내 프롬프트 + 다운로드 진행 다이얼로그."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from screen_recorder.app.updater.manifest import Manifest


def prompt_update(parent, manifest: Manifest) -> str:
    """새 버전 안내. 반환: 'now'(지금) | 'later'(나중에)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("KStudio 업데이트")
    notes = (manifest.notes or "").strip()
    text = f"새 버전 {manifest.version} 이(가) 있습니다."
    if notes:
        text += f"\n\n{notes}"
    text += "\n\n지금 업데이트할까요?"
    box.setText(text)
    now_btn = box.addButton("지금", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return "now" if box.clickedButton() is now_btn else "later"


class DownloadProgressDialog(QProgressDialog):
    """다운로드 진행 표시. total=0(길이 모름)이면 busy 인디케이터."""

    def __init__(self, version: str, parent=None):
        super().__init__(f"버전 {version} 다운로드 중…", "취소", 0, 100, parent)
        self.setWindowTitle("KStudio 업데이트")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumDuration(0)
        self.setAutoClose(False)
        self.setAutoReset(False)

    def set_progress(self, downloaded: int, total: int) -> None:
        if total <= 0:
            self.setRange(0, 0)            # busy
            return
        self.setRange(0, 100)
        self.setValue(int(downloaded * 100 / total))
