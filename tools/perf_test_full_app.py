"""실제 앱 (MainWindow) 전체를 띄워 사용자 시나리오 자동 재현 + 메인 스레드 응답성 측정.

이전 perf 테스트들은 _VideoSurface + QMediaPlayer 만 분리해 측정 → 격리된 환경이라
실제 앱 부하를 반영 못함. 본 테스트는 진짜 MainWindow 를 띄우고:
  1. 시작 시 라이브러리 인덱싱 (실제 14 영상)
  2. 영상 모드 전환 + 첫 영상 탭 오픈 (실제 VideoTab 생성)
  3. 5배속 재생 30초
  4. 100Hz stutter detector 가 메인 스레드 중단 50ms 초과 시 기록

진짜 코드 경로로 실행하므로 사용자가 실제 보는 stutter 를 잡을 수 있음.
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("KSTUDIO_PERF_DIAG", "0")   # 기본 OFF (set env=1 to enable)
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtCore import QTimer, QDateTime
from PySide6.QtWidgets import QApplication

from screen_recorder.app.main import build_main_window
from screen_recorder.ui.library_model import EntryKind
from screen_recorder.ui.mode_controller import AppMode


def main():
    app = QApplication(sys.argv)
    win = build_main_window()
    win.show()

    target_dir = Path(r"C:\Users\me\KStudio\Video\발표용")
    mp4s = sorted([p for p in target_dir.iterdir() if p.suffix.lower() == ".mp4"],
                  key=lambda p: -p.stat().st_size)
    target = mp4s[0]
    target_size_mb = target.stat().st_size / 1024 / 1024
    print(f"\n=== FULL APP TEST ===")
    print(f"target = {target.name} ({target_size_mb:.0f}MB)")

    # 100Hz 외부 stutter 측정 (MainWindow 내부 측정과 별개로 — 진단 차원).
    stutters_log: list[tuple[float, int]] = []
    state = {"last_ms": QDateTime.currentMSecsSinceEpoch(),
             "play_started": False, "stage": "start"}

    def _stutter_check():
        now = QDateTime.currentMSecsSinceEpoch()
        skew = (now - state["last_ms"]) - 100
        if skew > 50:
            elapsed = (now - state["t0"]) / 1000.0
            stutters_log.append((elapsed, skew))
            stage = state["stage"]
            print(f"  [t={elapsed:5.1f}s/{stage:10s}] STUTTER +{skew}ms")
        state["last_ms"] = now

    state["t0"] = QDateTime.currentMSecsSinceEpoch()
    stutter_timer = QTimer()
    stutter_timer.setInterval(100)
    stutter_timer.timeout.connect(_stutter_check)
    stutter_timer.start()

    # 시나리오 단계.
    def _step_switch_to_video():
        state["stage"] = "modeswitch"
        print("  >> step 1: switch to VIDEO mode + open target via button click flow")
        # 실제 영상 모드 버튼 클릭 흐름 그대로 시뮬레이션.
        win._on_mode_button_clicked(AppMode.VIDEO)
        QTimer.singleShot(2_000, _step_open_target)

    def _step_open_target():
        state["stage"] = "tab_open"
        print(f"  >> step 2: open {target.name} via library click")
        # 라이브러리에서 target 영상 entry 찾아 open.
        for e in win.library_model.entries():
            if e.path and Path(e.path).resolve() == target.resolve():
                win._open_entry(e.id)
                break
        QTimer.singleShot(3_000, _step_play_5x)   # 탭 로드 시간 좀 줌

    def _step_play_5x():
        state["stage"] = "play5x"
        cur = win.tab_area.current_video_tab()
        if cur is None:
            print("  !! no video tab — abort")
            app.quit()
            return
        print("  >> step 3: 5x playback for 30s")
        cur.controls.set_speed(5.0)
        cur.controls.speed_changed.emit(5.0)
        cur.player.play()
        QTimer.singleShot(30_000, _summary)

    def _summary():
        elapsed_total = (QDateTime.currentMSecsSinceEpoch() - state["t0"]) / 1000.0
        print(f"\n=== SUMMARY (total {elapsed_total:.1f}s) ===")
        by_stage: dict[str, list[int]] = {}
        for t, skew in stutters_log:
            stage = state["stage"]  # 마지막 stage 만 잡힘 — 정확하려면 per-tick 기록 필요
            by_stage.setdefault(stage, []).append(skew)
        print(f"  total stutters (>50ms): {len(stutters_log)}")
        if stutters_log:
            top = sorted(stutters_log, key=lambda x: -x[1])[:5]
            print(f"  worst 5: {[(round(t,1), s) for t,s in top]}")
        print(f"  see app.log for PERF_DIAG 5s dumps")
        app.quit()

    QTimer.singleShot(5_000, _step_switch_to_video)
    QTimer.singleShot(50_000, app.quit)  # safety
    print("\n  >> phase: app launch + library indexing")
    print("  (waiting 5s for indexing to settle, then mode switch)\n")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
