"""ChatPanel 모델 설치/다운로드 flow 분리 — Task 6 1단계 (controller 골격 + signal).

배경 (ChatPanel 1924줄 분해):
  ChatPanel 이 모델 콤보 선택 시 의존성 확인 → GpuInstallDialog → HF 다운로드 →
  fallback 복구까지 직접 담당(~235줄). 이 파일은 그 흐름의 신호 인터페이스를 정의하고
  순수 런타임 체크 로직만 먼저 추출한다.

1단계 범위:
  - ModelInstallController 클래스 + signal 선언
  - handle_runtime_check: 런타임 가용성 확인 → 불가 시 fallback_requested emit
  - GpuInstallDialog / ModelDownloadWindow / _pending_* 참조가 포함된 메서드는
    QObject lifetime·GC 이슈가 있어 Task 7 에서 이동. 현재는 ChatPanel 에 위치.

signal:
  fallback_requested(str)  — 의존성 부족 또는 런타임 실패 → 이전 모델 ID 로 복귀.
  install_started(str)     — 패키지 설치 다이얼로그 열림 (runtime 이름).
  install_finished(bool, str) — 설치 완료/실패 (success, runtime).
  download_started(str)    — 모델 다운로드 시작 (repo_id).
  download_finished(bool, str) — 다운로드 완료/실패 (success, repo_id).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ...agent.models.registry import ModelRegistry, check_runtime_available


class ModelInstallController(QObject):
    """모델 설치/다운로드 흐름 조율자.

    ChatPanel 에서 install/download 관련 signal 을 담당하고,
    ChatPanel 은 signal wiring 만 유지한다 (1단계).
    """

    # 의존성 미설치 / 런타임 실패 → ChatPanel._fallback_combo_to 로 연결.
    fallback_requested = Signal(str)

    # 향후 메서드 이동 시 사용 — 현재는 ChatPanel 내 dialog 메서드가 직접 emit 예정.
    install_started = Signal(str)        # runtime 이름
    install_finished = Signal(bool, str) # (success, runtime)
    download_started = Signal(str)       # repo_id
    download_finished = Signal(bool, str) # (success, repo_id)

    def __init__(self, parent_widget: Optional[QWidget] = None) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._registry = ModelRegistry()

    def handle_runtime_check(
        self,
        *,
        target_model_id: str,
        previous_model_id: str,
    ) -> bool:
        """선택 모델의 런타임 의존성이 충족되는지 확인.

        Args:
            target_model_id:   사용자가 선택한 모델 ID.
            previous_model_id: 실패 시 복귀할 이전 모델 ID.

        Returns:
            True  — 런타임 가용. 호출자는 다음 단계(다운로드·set_model) 로 진행 가능.
            False — 런타임 불가. fallback_requested(previous_model_id) emit 완료.
        """
        meta = self._registry.get(target_model_id)
        if meta is None:
            # 알 수 없는 모델 ID → 안전하게 fallback.
            self.fallback_requested.emit(previous_model_id)
            return False

        if check_runtime_available(meta.runtime):
            return True

        self.fallback_requested.emit(previous_model_id)
        return False
