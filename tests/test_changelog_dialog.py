from screen_recorder.ui.changelog_dialog import changelog_html, ChangelogDialog


def test_html_contains_versions_and_notes():
    html = changelog_html([("1.0.0", ["용량 감소", "알림 제거"]), ("0.1.4", ["자동 업데이트"])])
    assert "1.0.0" in html and "0.1.4" in html
    assert "용량 감소" in html and "알림 제거" in html and "자동 업데이트" in html
    # 버전당 <li> 가 노트 수만큼.
    assert html.count("<li>") == 3


def test_html_empty_has_placeholder():
    html = changelog_html([])
    assert html.strip()  # 빈 목록도 안내 문구로 비어있지 않게.


def test_dialog_constructs_and_shows(qtbot):
    dlg = ChangelogDialog([("1.0.0", ["용량 감소"])], "패치 내역")
    qtbot.addWidget(dlg)
    dlg.show()
    assert not dlg.isHidden()
    assert dlg.windowTitle() == "패치 내역"
