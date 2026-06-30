from screen_recorder.app.changelog import (
    notes_since, all_notes, decide_startup_changelog, CHANGELOG, PATCH_BASELINE,
)


def _vers(entries):
    return [v for v, _ in entries]


def test_notes_since_range_excludes_prev_includes_current():
    assert _vers(notes_since("0.1.4", "1.0.0")) == ["1.0.0", "0.1.5"]


def test_notes_since_single():
    assert _vers(notes_since("0.1.5", "1.0.0")) == ["1.0.0"]


def test_notes_since_equal_is_empty():
    assert notes_since("1.0.0", "1.0.0") == []


def test_notes_since_downgrade_is_empty():
    assert notes_since("1.0.0", "0.1.5") == []


def test_notes_since_unparseable_is_empty():
    assert notes_since("garbage", "1.0.0") == []
    assert notes_since("0.1.4", "nope") == []


def test_all_notes_is_full_newest_first_with_baseline_last():
    versions = _vers(all_notes())
    assert versions[0] == "1.0.0"
    assert versions[-1] == PATCH_BASELINE == "0.1.4"
    # 모든 항목이 노트를 갖는다(빈 릴리스 금지).
    assert all(notes for _, notes in all_notes())


def test_decide_existing_user_first_adopt_shows_all():
    r = decide_startup_changelog("", "1.0.0", settings_existed=True)
    assert _vers(r) == _vers(all_notes())


def test_decide_fresh_install_is_empty():
    assert decide_startup_changelog("", "1.0.0", settings_existed=False) == []


def test_decide_normal_update():
    assert _vers(decide_startup_changelog("0.1.5", "1.0.0", True)) == ["1.0.0"]


def test_decide_no_change_is_empty():
    assert decide_startup_changelog("1.0.0", "1.0.0", True) == []


def test_changelog_versions_all_parse():
    # 데이터 무결성: 모든 버전이 semver 로 파싱돼야(notes_since 가 안 깨지도록).
    from screen_recorder.app.updater.version_compare import parse_semver
    for v, _ in CHANGELOG:
        parse_semver(v)
