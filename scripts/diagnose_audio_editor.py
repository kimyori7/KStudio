"""AudioWaveformEditor 진단 — 위젯을 820x140 으로 구성해 PNG 로 grab.

트림(1000,9000) / 컷(3000,4000) / 재생위치 5000 / 변화하는 peaks 를 세팅하고
logs/audio_editor_diag.png 로 저장한다. (헤드리스에서 시각 확인용 — PNG 는 직접 못 보지만
저장 성공 여부와 경로를 출력한다.)
"""
from __future__ import annotations

import math
import os
import sys

# offscreen 강제 — CI/헤드리스 안전.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from PySide6.QtWidgets import QApplication  # noqa: E402

from screen_recorder.ui.audio.audio_waveform_editor import AudioWaveformEditor  # noqa: E402


def _peaks(n=400):
    return [abs(math.sin(i / 13.0)) * (0.3 + 0.7 * (i / n)) for i in range(n)]


def _grab(app, w, out_path):
    w.show()
    app.processEvents()
    pix = w.grab()
    ok = pix.save(out_path, "PNG")
    print(f"saved={ok} path={out_path} size={pix.width()}x{pix.height()}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    out_dir = os.path.join(_ROOT, "logs")
    os.makedirs(out_dir, exist_ok=True)

    # (1) 미편집 상태 — 가운데 안내 힌트 + 양끝 그립(손잡이)이 보여야 한다.
    w1 = AudioWaveformEditor()
    w1.resize(820, 140)
    w1.set_total_ms(10000)
    w1.set_peaks(_peaks())
    w1.set_position_ms(5000)
    w1.set_filename("sample_audio.wav")
    _grab(app, w1, os.path.join(out_dir, "audio_editor_unedited.png"))

    # (2) 편집 상태 — 트림(1000,9000)+컷(3000,4000). 힌트 없음, 그립은 안쪽으로.
    w2 = AudioWaveformEditor()
    w2.resize(820, 140)
    w2.set_total_ms(10000)
    w2.set_peaks(_peaks())
    w2.set_trim(1000, 9000)
    w2.set_cuts([(3000, 4000)])
    w2.set_position_ms(5000)
    w2.set_filename("sample_audio.wav")
    _grab(app, w2, os.path.join(out_dir, "audio_editor_edited.png"))

    # (3) 선택 상태 — 파랑 선택(6000~7000, 아직 안 자름) vs 빨강 컷(3000~4000).
    #     우클릭 → '자르기' 로 선택을 컷으로 확정. 선택/컷 색 구분 확인.
    w3 = AudioWaveformEditor()
    w3.resize(820, 140)
    w3.set_total_ms(10000)
    w3.set_peaks(_peaks())
    w3.set_cuts([(3000, 4000)])
    w3.set_selection((6000, 7000))
    w3.set_position_ms(5000)
    w3.set_filename("sample_audio.wav")
    _grab(app, w3, os.path.join(out_dir, "audio_editor_selection.png"))


if __name__ == "__main__":
    main()
