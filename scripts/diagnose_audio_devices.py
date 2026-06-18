"""오디오 출력 장치 진단 — Qt(QtMultimedia) 가 보는 재생 장치/기본 장치 확인.

KStudio 미리보기는 player_widget 에서 `QAudioOutput()` 을 장치 지정 없이 만들어
**시스템 기본 재생 장치**에 의존한다. 기본 장치를 Qt 가 못 잡으면 음소거가 아니어도
소리가 안 난다. 이 스크립트로 그 상태를 직접 확인.

실행:  .venv\\Scripts\\python.exe scripts\\diagnose_audio_devices.py
"""
from __future__ import annotations
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaDevices, QAudioOutput


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    outs = QMediaDevices.audioOutputs()
    print(f"[출력 장치 개수] {len(outs)}")
    for i, d in enumerate(outs):
        print(f"  {i}: {d.description()!r}  (null={d.isNull()})")

    default = QMediaDevices.defaultAudioOutput()
    print(f"[기본 출력 장치] {default.description()!r}  (null={default.isNull()})")
    if default.isNull():
        print("  ⚠ 기본 출력 장치가 NULL — Qt 가 재생 장치를 못 잡았다. 이게 무음 원인.")

    # KStudio 와 동일하게 장치 지정 없이 QAudioOutput 생성 → 기본값 확인.
    ao = QAudioOutput()
    print(f"[QAudioOutput 기본] volume={ao.volume():.3f}  muted={ao.isMuted()}  "
          f"device={ao.device().description()!r} (null={ao.device().isNull()})")
    if ao.volume() <= 0.0:
        print("  ⚠ 기본 볼륨이 0 — 소리가 안 난다.")
    if ao.isMuted():
        print("  ⚠ 기본이 음소거 상태.")

    # 멀티미디어 백엔드 확인 (환경변수로 강제됐는지).
    import os
    print(f"[QT_MEDIA_BACKEND] {os.environ.get('QT_MEDIA_BACKEND', '(미설정=기본)')}")


if __name__ == "__main__":
    main()
