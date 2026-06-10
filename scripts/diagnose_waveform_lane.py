"""AudioTrackLane 정렬 진단 — 파형 envelope 경계가 segment 경계와 맞는지.

실행: python scripts/diagnose_waveform_lane.py  (PNG 세 장 저장)
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from screen_recorder.ui.video.audio_track_lane import AudioTrackLane  # noqa: E402
from screen_recorder.effects.segment import VideoSegment  # noqa: E402


def _seg(src, dur, start, src_in=0, src_out=0):
    return VideoSegment(src=src, src_in_ms=src_in, src_out_ms=src_out,
                        src_duration_ms=dur, start_ms=start)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    lane = AudioTrackLane()
    lane.resize(800, 44)
    lane.set_duration_ms(3000)
    # seg0: 0~1000 (소리 큼), seg1: 1500~2500 자른 클립 (앞부분만, 소리 작음)
    lane.set_segments([_seg("a.mp4", 1000, 0),
                       _seg("a.mp4", 3000, 1500, src_in=0, src_out=1000)])
    # a.mp4 전체 peaks: 앞 절반 큼, 뒤 절반 작음.
    peaks = [0.9] * 500 + [0.2] * 500
    lane.set_peaks("a.mp4", peaks)
    pm = QPixmap(800, 44)
    lane.render(pm)
    pm.save("diag_waveform_normal.png")

    lane.set_muted(True)
    pm2 = QPixmap(800, 44)
    lane.render(pm2)
    pm2.save("diag_waveform_muted.png")

    # 퇴화 케이스 (#1 가드): 30분 원본을 5초로 자른 슬라이스. 시간 비례 bucket
    # (buckets_for: 90000) 이면 5초 슬라이스 ≈250 bucket → 파형이 보여야 한다.
    # (고정 총 bucket=2000 이었다면 5/1800*2000≈5 bucket 으로 평평한 블록.)
    lane2 = AudioTrackLane()
    lane2.resize(800, 44)
    lane2.set_duration_ms(5000)
    lane2.set_segments([_seg("long.mp4", 1_800_000, 0, src_in=0, src_out=5000)])
    import math
    long_peaks = [0.2 + 0.7 * abs(math.sin(i / 300.0)) for i in range(90000)]
    lane2.set_peaks("long.mp4", long_peaks)
    pm3 = QPixmap(800, 44)
    lane2.render(pm3)
    pm3.save("diag_waveform_long_source_short_slice.png")
    print("saved diag_waveform_normal.png / _muted.png / _long_source_short_slice.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
