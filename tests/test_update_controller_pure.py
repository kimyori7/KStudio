"""순수 함수 should_prompt 단위 테스트.

스레드/네트워크/다운로드/적용 전체 흐름은 실 Windows 수동 검증(Task 13).
"""
from screen_recorder.app.updater.controller import should_prompt
from screen_recorder.app.updater.manifest import Manifest

_M = Manifest(version="0.1.5", notes="", full_url="https://x/S.exe",
              full_sha256="a" * 64)


def test_prompt_when_newer():
    assert should_prompt(_M, current_version="0.1.4", skip_version="") is True


def test_no_prompt_when_same():
    assert should_prompt(_M, current_version="0.1.5", skip_version="") is False


def test_no_prompt_when_skipped():
    # "이 버전 건너뛰기" 한 버전이면 안 띄움.
    assert should_prompt(_M, current_version="0.1.4", skip_version="0.1.5") is False
