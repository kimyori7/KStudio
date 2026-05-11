"""BrollPipPlayer 단위 + 통합 테스트.

BrollPipPlayer 는 QObject (QWidget 아님) — qtbot.addWidget 불가.
qapp fixture 로 QApplication 만 보장하고 인스턴스는 로컬 scope 로 cleanup.
"""
from __future__ import annotations

import pytest

from screen_recorder.ui.video.broll_pip_player import BrollPipPlayer


def test_pip_player_starts_idle(qapp):
    p = BrollPipPlayer()
    assert p.active_effect_id() is None
    assert p.loaded_src() is None
    p.deleteLater()
