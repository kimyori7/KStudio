"""오디오 출력 장치 열거·매칭 (QMediaDevices 래퍼).

QAudioDevice.id() 는 QByteArray(엔드포인트 고유 id) — JSON·콤보 userData 에 쓰려고
hex 문자열로 변환해 저장/비교한다. 순수 계산은 audio_device_list.py 참고.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtMultimedia import QMediaDevices, QAudioDevice


def device_id_str(dev: Optional[QAudioDevice]) -> str:
    """QAudioDevice → 안정적 문자열 id(hex). null/None 이면 빈 문자열."""
    if dev is None or dev.isNull():
        return ""
    return bytes(dev.id()).hex()


def list_outputs() -> list[tuple[str, str]]:
    """(id_str, description) 목록 — 시스템 출력 장치 순서 그대로."""
    return [(device_id_str(d), d.description()) for d in QMediaDevices.audioOutputs()]


def default_output_id() -> str:
    """현재 시스템 기본 출력 장치의 id_str. 없으면 빈 문자열."""
    return device_id_str(QMediaDevices.defaultAudioOutput())


def find_output(id_str: str) -> Optional[QAudioDevice]:
    """id_str 과 일치하는 QAudioDevice. 없으면 None(빈 id_str 도 None)."""
    if not id_str:
        return None
    for d in QMediaDevices.audioOutputs():
        if device_id_str(d) == id_str:
            return d
    return None
