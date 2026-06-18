from PySide6.QtCore import QObject, Signal

from screen_recorder.ui.youtube.downloads_button import DownloadsButton


class FakeJob(QObject):
    progress = Signal(object, object)
    title_resolved = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()

    def cancel(self):
        pass


def test_button_hidden_until_job_added(qtbot):
    btn = DownloadsButton()
    qtbot.addWidget(btn)
    assert btn.isHidden()
    btn.add_job(FakeJob(), "t")
    assert not btn.isHidden()


def test_button_shows_aggregate_percent(qtbot):
    btn = DownloadsButton()
    qtbot.addWidget(btn)
    job = FakeJob()
    btn.add_job(job, "t")
    job.progress.emit(25, 100)
    assert "25%" in btn.text()


def test_button_clears_percent_when_done(qtbot):
    btn = DownloadsButton()
    qtbot.addWidget(btn)
    job = FakeJob()
    btn.add_job(job, "t")
    job.progress.emit(50, 100)
    assert "50%" in btn.text()
    job.finished.emit("C:/out/f.mp4")
    # 완료되면 진행 중이 없으니 % 텍스트가 사라짐(아이콘만), 줄은 남아 버튼은 보임.
    assert "%" not in btn.text()
    assert not btn.isHidden()


def test_button_hides_when_all_rows_closed(qtbot):
    btn = DownloadsButton()
    qtbot.addWidget(btn)
    job = FakeJob()
    row = btn.add_job(job, "t")
    assert not btn.isHidden()
    row.close_requested.emit()   # 사용자가 줄 닫음 → rows_changed(0) → 버튼 숨김
    assert btn.isHidden()


def test_button_toggle_popup(qtbot):
    btn = DownloadsButton()
    qtbot.addWidget(btn)
    btn.show()
    btn.add_job(FakeJob(), "t")
    btn._toggle_popup()
    assert btn._popup.isVisible()
    btn._toggle_popup()
    assert not btn._popup.isVisible()
