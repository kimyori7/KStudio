import os

# pytest 실행 시 Qt 창을 실제로 띄우지 않도록 offscreen 플랫폼 강제.
# 안 그러면 ScreenshotViewer.add_tab 안의 self.show() 때문에 창이 뜨고,
# 테스트 종료 시 cleanup 으로 close 가 불리면서 모달 다이얼로그가 뜸.
# 반드시 Qt import 전에 환경변수가 설정되어야 하므로 최상단에 둔다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# MainWindow 의 첫 실행 단축키 프리셋 다이얼로그가 테스트를 블로킹하지 않게 차단.
os.environ.setdefault("KSTUDIO_NO_FIRST_RUN_DIALOG", "1")
# Markdown 미리보기는 테스트에서 QtWebEngine(Chromium) 대신 경량 Fallback 렌더러 사용.
# 한 프로세스에서 여러 QWebEngineView 를 만들고 해제하면 Qt WebEngine teardown 이
# 불안정해 세그폴트가 나므로(offscreen 환경에서 특히), 단위 테스트는 Chromium 을 띄우지
# 않는다. 실제 WebEngine 렌더는 빌드된 .exe 수동 검증(진단 스크립트)으로 확인.
os.environ.setdefault("KSTUDIO_DISABLE_WEBENGINE", "1")

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

    회귀 (2026-05-12, 2026-05-13): 통합 테스트의 save() 가 실제 settings 파일을
    덮어써 라이브러리/단축키/dock 상태가 날아갔다.

    2026-05-13 추가 회귀: `settings_path` 를 *이름으로* import 한 모듈 (예:
    `from .settings import settings_path`) 은 모듈-attribute monkeypatch 우회 가능.
    main_window.py 와 app/main.py 가 그런 import 를 했었음. 이중 차단:
    1) `core.settings.settings_path` 자체 patch — 함수 호출 시점 lookup 하는 경로.
    2) 직접 path-방어: `core.settings.save` 도 패치해 tmp_path 외부 쓰기 거부 +
       즉시 fail. 호출자가 이름-bound `settings_path` 를 끼고 들어와도 save 가
       경로를 검사해서 막음.
    """
    from screen_recorder.core import settings as _settings_mod
    fake_path = tmp_path / "kstudio_test_settings.json"
    monkeypatch.setattr(_settings_mod, "settings_path", lambda: fake_path)

    # belt-and-suspenders: save() 도 wrap — 호출 경로가 tmp_path 가 아니면
    # 강제로 fake_path 로 리다이렉트 + AssertionError 로 즉시 실패. 테스트가
    # 우회 경로로 사용자 데이터에 쓰는 사고를 발견 즉시 잡음.
    _real_save = _settings_mod.save

    def _guarded_save(settings, path):
        from pathlib import Path
        p = Path(path).resolve()
        tmp_root = Path(tmp_path).resolve()
        try:
            p.relative_to(tmp_root)
        except ValueError:
            raise AssertionError(
                f"테스트가 tmp_path 외부 경로에 settings save 시도! path={p}\n"
                f"원인: settings_path 를 import-by-name 으로 가져온 모듈이 monkeypatch "
                f"우회. core.settings 의 `from screen_recorder.core import settings as _m` "
                f"패턴으로 변경하세요."
            )
        return _real_save(settings, path)

    monkeypatch.setattr(_settings_mod, "save", _guarded_save)


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
