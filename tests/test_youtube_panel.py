from PySide6.QtCore import QObject, Signal

from screen_recorder.ui.youtube.downloads_panel import DownloadsPanel


class FakeJob(QObject):
    progress = Signal(object, object)
    title_resolved = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.cancelled_called = False

    def cancel(self):
        self.cancelled_called = True


def test_panel_hidden_when_empty(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    assert panel.isHidden()


def test_panel_shows_on_add(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.add_job(FakeJob(), title_hint="t")
    assert not panel.isHidden()
    assert panel.row_count() == 1


def test_panel_finished_keeps_row(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    panel.show()
    job = FakeJob()
    panel.add_job(job, title_hint="t")
    job.finished.emit("C:/out/f.mp4")
    assert panel.row_count() == 1   # 완료돼도 사용자가 닫기 전까지 유지


def test_panel_title_resolved_updates_row(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    panel.show()
    job = FakeJob()
    row = panel.add_job(job, title_hint="준비")
    job.title_resolved.emit("실제 제목")
    assert row.title_label.text() == "실제 제목"


def test_panel_cancel_button_calls_job_cancel(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    panel.show()
    job = FakeJob()
    row = panel.add_job(job, title_hint="t")
    row.cancel_btn.click()
    assert job.cancelled_called


def test_panel_close_removes_row_and_hides(qtbot):
    panel = DownloadsPanel()
    qtbot.addWidget(panel)
    panel.show()
    job = FakeJob()
    row = panel.add_job(job, title_hint="t")
    row.close_requested.emit()
    assert panel.row_count() == 0
    assert panel.isHidden()
