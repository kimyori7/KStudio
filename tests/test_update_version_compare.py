import pytest
from screen_recorder.app.updater.version_compare import parse_semver, is_newer


def test_parse_semver():
    assert parse_semver("1.2.3") == (1, 2, 3)


def test_parse_semver_rejects_bad():
    for bad in ["1.2", "v1.2.3", "a.b.c", ""]:
        with pytest.raises(ValueError):
            parse_semver(bad)


def test_is_newer_true():
    assert is_newer("0.1.5", "0.1.4") is True
    assert is_newer("0.2.0", "0.1.9") is True
    assert is_newer("1.0.0", "0.9.9") is True


def test_is_newer_false_when_same_or_older():
    assert is_newer("0.1.4", "0.1.4") is False
    assert is_newer("0.1.3", "0.1.4") is False


def test_is_newer_false_on_garbage_remote():
    # 깨진 remote 버전은 절대 "새 버전"으로 보지 않음(안전).
    assert is_newer("garbage", "0.1.4") is False
    assert is_newer("", "0.1.4") is False
