"""영역 녹화 테두리의 위치/크기는 옮길 때마다 즉시 디스크에 저장돼야 한다.

회귀(사용자 보고 2026-06-10 "껏다 켜도 영역 지정 영상 캡쳐 범위/위치가 저장 안 됨"):
target(region/fullscreen)은 _on_target_changed 가 즉시 _persist_settings() 로 저장하는데,
region_x/y/w/h 는 _on_region_moved 가 in-memory 객체만 갱신하고 디스크 저장은 종료 시
aboutToQuit 훅에만 의존했다. 그래서 터미널 kill·강제 종료·크래시 시 위치가 손실되고,
target 만 살아남아 재시작 후 테두리가 *기본 위치*로 돌아왔다.

이 테스트는 aboutToQuit 를 거치지 않고 디스크에서 다시 읽어 검증한다 (in-memory
객체를 보면 fix 전후 모두 통과해 버그를 못 잡으므로 반드시 파일에서 읽는다).
"""
from screen_recorder.core.settings import AppSettings
from screen_recorder.core import settings as settings_module
from screen_recorder.ui.main_window import MainWindow


def test_region_move_persists_to_disk_immediately(qtbot, tmp_path):
    f = tmp_path / "ffmpeg.exe"
    f.write_bytes(b"")
    win = MainWindow(AppSettings(), f)
    qtbot.addWidget(win)

    # 사용자가 테두리를 드래그/리사이즈 → rect_changed → _on_region_moved.
    win._on_region_moved(111, 222, 640, 480)

    # aboutToQuit 없이 *디스크에서* 다시 읽었을 때 값이 남아 있어야 한다.
    loaded = settings_module.load(settings_module.settings_path())
    assert (
        loaded.general.region_x,
        loaded.general.region_y,
        loaded.general.region_w,
        loaded.general.region_h,
    ) == (111, 222, 640, 480)
