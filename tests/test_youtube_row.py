from screen_recorder.ui.youtube.download_row import DownloadRow


def test_row_progress_updates_bar(qtbot):
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_progress(50, 100)
    assert row.progress_bar.value() == 50


def test_row_progressbar_text_hidden_no_double_percent(qtbot):
    # 회귀: 막대 내장 % 텍스트를 끄지 않으면 "23% 23%" 처럼 두 번 보임(라벨 + 막대).
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    assert row.progress_bar.isTextVisible() is False


def test_row_progress_unknown_total_busy(qtbot):
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_progress(123, 0)   # total 미정 → busy(0,0)
    assert row.progress_bar.maximum() == 0


def test_row_shows_received_total_and_speed(qtbot):
    # % 대신 받은량/총량 + 속도 표시.
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_progress(3 * 1024 * 1024, 12 * 1024 * 1024)
    row.on_speed(2.3 * 1024 * 1024)
    s = row.status_label.text()
    assert "3.0MB" in s
    assert "12.0MB" in s
    assert "MB/s" in s
    assert "%" not in s


def test_row_speed_ignored_after_finished(qtbot):
    # 완료 후 늦게 온 speed 가 '완료' 텍스트를 덮어쓰지 않아야.
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_finished("C:/out/f.mp4")
    row.on_speed(999)
    assert row.status_label.text() == "완료"


def test_row_finished_shows_open(qtbot):
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_finished("C:/out/f.mp4")
    assert not row.open_btn.isHidden()
    assert not row.folder_btn.isHidden()
    assert row.progress_bar.value() == row.progress_bar.maximum()


def test_row_error_shows_message(qtbot):
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_error("boom")
    assert "실패" in row.status_label.text()
    assert not row.retry_btn.isHidden()


def test_row_cancelled_state(qtbot):
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    row.on_cancelled()
    assert "취소" in row.status_label.text()
    assert not row.close_btn.isHidden()


def test_row_set_title(qtbot):
    row = DownloadRow(title="준비")
    qtbot.addWidget(row)
    row.set_title("실제 제목")
    assert row.title_label.text() == "실제 제목"


def test_row_close_button_has_icon_not_text(qtbot):
    # 회귀: '✕' 텍스트 글리프가 안 보여 빈 버튼처럼 보이던 문제 → SVG 'x' 아이콘 사용.
    row = DownloadRow(title="t")
    qtbot.addWidget(row)
    assert row.close_btn.text() == ""
    assert not row.close_btn.icon().isNull()
