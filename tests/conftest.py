import os

# pytest 실행 시 Qt 창을 실제로 띄우지 않도록 offscreen 플랫폼 강제.
# 안 그러면 ScreenshotViewer.add_tab 안의 self.show() 때문에 창이 뜨고,
# 테스트 종료 시 cleanup 으로 close 가 불리면서 모달 다이얼로그가 뜸.
# 반드시 Qt import 전에 환경변수가 설정되어야 하므로 최상단에 둔다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# MainWindow 의 첫 실행 단축키 프리셋 다이얼로그가 테스트를 블로킹하지 않게 차단.
os.environ.setdefault("KSTUDIO_NO_FIRST_RUN_DIALOG", "1")

import pytest
from screen_recorder.core import ffmpeg_check


@pytest.fixture(autouse=True)
def reset_ffmpeg_cache():
    ffmpeg_check.reset_cache()
    yield
    ffmpeg_check.reset_cache()


@pytest.fixture(autouse=True)
def isolate_user_settings(monkeypatch, tmp_path):
    """테스트가 사용자 실제 settings.json (~/AppData/Local/KStudio/settings.json) 을
    덮어쓰는 것을 차단.

    회귀 (2026-05-12): 어떤 통합 테스트가 save() 흐름을 타면서 실제 settings 파일을
    pytest 임시 경로로 채워 사용자의 라이브러리/단축키/dock 상태가 모두 날아갔다.
    settings_path() 를 tmp_path 안의 가짜 파일로 monkeypatch — 테스트가 어떤
    경로로 save() 를 호출해도 사용자 데이터에 영향을 주지 않게 격리.
    """
    from screen_recorder.core import settings as _settings_mod
    fake_path = tmp_path / "kstudio_test_settings.json"
    monkeypatch.setattr(_settings_mod, "settings_path", lambda: fake_path)


@pytest.fixture(autouse=True)
def stub_close_dialog_exec(monkeypatch):
    """테스트 종료 시 '저장 안 된 탭' 모달 다이얼로그가 블로킹하는 것 방지.

    offscreen 플랫폼에서도 QDialog.exec() 는 이벤트 루프에 진입하면 사람
    입력을 기다리며 멈춘다. 테스트에서는 CloseDialog 가 떴다는 건 '닫기
    취소' 와 동치로 처리해 그냥 빠져나오게 한다. 실제 다이얼로그의 버튼
    클릭/결과 동작은 _choose() 를 직접 호출하는 unit 테스트로 검증됨
    (test_screenshot_close_dialog.py).
    """
    from screen_recorder.ui.screenshot_close_dialog import CloseDialog, CloseAction

    def stub_exec(self):
        self._action = CloseAction.CANCEL
        return 0

    monkeypatch.setattr(CloseDialog, "exec", stub_exec)
