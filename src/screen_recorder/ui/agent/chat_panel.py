"""Claude 와 대화하는 채팅 패널 (QDockWidget).

레이아웃:
- 상단: 메시지 리스트 (스크롤 영역, 각 메시지 = QFrame).
- 하단: 멀티라인 입력창(_ChatInputEdit, QPlainTextEdit 기반) + 보내기 버튼.
  Enter=보내기, Shift+Enter=줄바꿈. 입력이 길어지면 최대 5줄까지 자동 확장.
- 진행 상태: 입력창 위에 작은 상태 라벨 ("도구 사용: get_video_state...").

신호 흐름:
- 사용자 입력 → user_submitted(str) → MainWindow 가 AgentRuntime.send() 호출.
- AgentRuntime.message_received(AgentMessage) → ChatPanel.append_message().
- AgentRuntime.event_received(AgentEvent) → ChatPanel.update_status().

직접 AgentRuntime 을 들고 있지 않음 — 의존성 역전. 테스트에서 시그널만 emit 해도
UI 갱신 검증 가능.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QBuffer, QEvent, QIODevice, Signal, Slot
from PySide6.QtGui import QKeySequence, QKeyEvent, QPixmap, QImage
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFrame, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ...agent.chat_history import (
    MAX_MESSAGES, PERSISTABLE_ROLES, load_history, save_history,
)
from ...agent import models as _models   # is_model_cached / ModelDownloadJob alias 용 (monkeypatch 친화).
from ...agent.models import ModelRegistry, check_runtime_available
from ...agent.plan_gate import PlanGate
from ...agent.runtime import AgentMessage, AgentEvent
from ..gpu_install_dialog import GpuInstallDialog
from ..model_download_window import ModelDownloadWindow
from .model_install_flow import ModelInstallController
from .bubbles import (
    MessageBubble as _MessageBubble,
    PlanCard as _PlanCard,
    ProposalsPreviewCard as _ProposalsPreviewCard,
    WhisperDownloadCard as _WhisperDownloadCard,
)
from .chat_input_edit import ChatInputEdit as _ChatInputEdit


# Qwen2.5-Omni 7B 실행에 필요한 PyTorch + 의존성 패키지.
# GpuInstallDialog(packages=...) 로 전달해 동일 UI 로 설치.
# - torchvision: qwen_omni_utils.v2_5.vision_process 가 module-level import
#   (이게 빠지면 시작 시 _check_runtime_available("transformers") 영원히 False).
# - bitsandbytes: INT8 양자화, qwen-omni-utils[decord]: 영상 디코더, soundfile: 오디오 I/O.
PYTORCH_PACKAGES: tuple[str, ...] = (
    "torch",
    "torchvision",
    "transformers",
    "accelerate",
    "bitsandbytes",
    "qwen-omni-utils[decord]",
    "soundfile",
)


# PyTorch CUDA wheel 인덱스. CUDA 13.0 은 sm_75 (Turing) ~ sm_120 (Blackwell, RTX 50xx)
# 모두 지원하므로 NVIDIA GPU 가 감지되면 무조건 이 인덱스 사용 — 사용자별 GPU 세대 분기
# 없음. (사용자 RTX 5060 Ti = sm_120, cu126 에는 해당 binary 없음.)
_PYTORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu130"


def _detect_nvidia_gpu() -> bool:
    """nvidia-smi 호출로 NVIDIA GPU 존재 여부 판정.

    True = GPU 있음 (CUDA wheel 설치 권장). False = GPU 없음 / 드라이버 문제 /
    nvidia-smi 미설치. 어떤 예외도 False 로 처리해 GPU 미지원 환경에서 깨지지 않음.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _is_torch_cuda_available() -> bool:
    """이미 CUDA torch 가 설치되어 동작 가능한지 — installer skip 판정.

    torch import 실패 / CUDA 미빌드 / 드라이버 mismatch → False (재설치 후보).
    """
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _pytorch_index_url_for_install() -> Optional[str]:
    """PyTorch 설치에 사용할 pip --index-url. None 이면 default (CPU wheel).

    - GPU 없음 → None (CPU 로 진행, 사용자에게 후술 시스템 메시지로 한계 안내).
    - GPU 있음 + 이미 CUDA torch OK → None (재설치 불필요, 호출자가 installer skip).
    - GPU 있음 + torch 없음 / CPU torch → cu130 wheel URL.
    """
    if not _detect_nvidia_gpu():
        return None
    if _is_torch_cuda_available():
        return None
    return _PYTORCH_CUDA_INDEX


# 채팅 디버그 로그 — 사용자가 보고할 때 ~/AppData/Local/KStudio/logs/chat_debug.log 를
# 첨부하면 정확한 이벤트 흐름 파악 가능. Ctrl+C 같은 UI 회귀 디버깅이 핵심 용도.
# setup_logging() 의 root 로거에 합치면 app.log 안에 묻혀버려 분리.
_chat_log = logging.getLogger("kstudio.chat")


def _ensure_chat_log_handler() -> None:
    """첫 호출 시 chat_debug.log 파일 핸들러 부착. 한 번만 실행."""
    if getattr(_chat_log, "_kstudio_handler_added", False):
        return
    try:
        log_dir = Path.home() / "AppData" / "Local" / "KStudio" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(log_dir / "chat_debug.log", encoding="utf-8")
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        _chat_log.addHandler(h)
        _chat_log.setLevel(logging.DEBUG)
        # root 로 전파 막음 — app.log 오염 방지.
        _chat_log.propagate = False
        _chat_log._kstudio_handler_added = True  # type: ignore[attr-defined]
        _chat_log.info("==== chat_debug.log started ====")
    except OSError:
        pass


# 모델 옵션 — (display, model_id). 정액제 사용자도 모델 선택 자유롭게.
# Opus 가 가장 똑똑하지만 토큰 비싸고 Pro 플랜 quota 낮음. Sonnet 이 기본 추천.
# 짧은 라벨 — 입력 바 위 좁은 공간에 깔끔히 들어가도록.
MODEL_OPTIONS: list[tuple[str, str]] = [
    ("Sonnet 4.6", "claude-sonnet-4-6"),
    ("Opus 4.7", "claude-opus-4-7"),
    ("Haiku 4.5", "claude-haiku-4-5-20251001"),
]
DEFAULT_MODEL_ID = MODEL_OPTIONS[0][1]


# 미등록 모델을 위한 보수적 default — 200k 면 대부분 안전.
_DEFAULT_CONTEXT_LIMIT = 200_000

# ModelRegistry 는 무상태 + builtin list 가 모듈 레벨 전역이라 인스턴스 1회면 충분.
# 매 호출마다 new 할 이유 없음 (UI 응답 직후 호출되어 hot path 아니지만 관용 패턴).
_CONTEXT_REGISTRY = ModelRegistry()


def _context_limit_for(model_id: str) -> int:
    """모델별 context window — ModelRegistry 가 single source of truth.

    metadata.context_window 가 0 (또는 falsy) 이거나 모델 자체 미등록이면 default.
    UI 의 컨텍스트 dot/% 계산에 사용.
    새 모델을 추가할 때 이 함수는 건드릴 필요 없음 — registry.py 만 수정하면 됨.
    """
    meta = _CONTEXT_REGISTRY.get(model_id)
    if meta is None or not meta.context_window:
        return _DEFAULT_CONTEXT_LIMIT
    return meta.context_window


def _ctx_color_for(pct: float) -> str:
    """컨텍스트 사용률 % 별 동그라미 색 — Discord 상태 아이콘 톤.

    낮음(녹) → 중간(노랑) → 높음(빨강) 점진. 70% 이상이면 사용자에게 /compact 또는 /clear 신호.
    """
    if pct < 40.0:
        return "#22c55e"   # green
    if pct < 70.0:
        return "#eab308"   # yellow
    return "#ef4444"       # red


# 슬래시 명령 — 채팅창 입력 시작에 '/' 면 명령으로 라우팅.
# (값은 시그널/내부 핸들러 둘 다에서 식별용 키)
SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/clear",   "대화 + 누적 토큰 카운터 초기화 (영상/제안 큐는 그대로)"),
    ("/compact", "지금까지 대화를 Claude 가 요약해서 컨텍스트 줄임"),
    ("/help",    "사용 가능한 명령 목록"),
]

class ChatPanel(QDockWidget):
    """Claude 와의 대화 패널. MainWindow 에 right-dock 으로 부착."""

    user_submitted = Signal(str, list)         # (prompt, pasted_image_bytes_list)
    model_changed = Signal(str)                # 사용자가 모델 변경 (model_id)
    cancel_requested = Signal()                # 사용자가 진행 중 응답 취소
    proposals_apply_confirmed = Signal()       # 미리보기 카드의 적용 클릭
    proposals_apply_canceled = Signal()        # 미리보기 카드의 취소 클릭
    show_thinking_changed = Signal(bool)       # 추론 보기 토글
    whisper_download_confirmed = Signal(str)   # Whisper 다운로드 카드 [다운로드] 클릭 (chosen model_size)
    whisper_download_canceled = Signal()       # Whisper 다운로드 카드 [취소] 클릭
    # 슬래시 명령 — runtime 측에 알려야 client 재연결/요약 트리거 가능.
    clear_requested = Signal()                 # /clear — 새 세션 시작 (client disconnect)
    compact_requested = Signal()               # /compact — Claude 에게 요약 부탁
    # 모델 다운로드 진행률 — MainWindow 가 받아 GlobalToolbar 라벨 갱신.
    # 사용자가 ModelDownloadWindow 를 닫아도 진행률 잃지 않게 (영구 인디케이터).
    download_progress_changed = Signal(int, int, str)   # (received_bytes, total_bytes, display_name)
    download_finished = Signal()                        # 다운로드 완료 또는 에러 — 라벨 숨김 신호

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_model_id: Optional[str] = None,
        initial_show_thinking: bool = True,
        plan_gate: Optional[PlanGate] = None,
        agent: Optional["object"] = None,
    ) -> None:
        # NOTE: agent 파라미터는 의존성 역전 원칙 (docstring 참조) 의 의도적 예외.
        # set_model 가드가 model 변경을 차단했는지 ChatPanel 이 직접 알아야 콤보 fallback
        # 가능 → AgentRuntime 의 _model 상태를 즉시 비교해야 함. signal/slot 만으로는
        # synchronous 결과 회신이 어려움. MainWindow 가 agent=runtime 으로 주입.
        super().__init__("Claude 에이전트", parent)
        self.setObjectName("AgentChatPanel")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        # AgentRuntime 참조 — 콤보 fallback 시 set_model 직접 호출 + _model 비교 용.
        self._agent = agent
        # 채팅 디버그 로그 활성화 — 첫 ChatPanel 생성 시 한 번만 파일 핸들러 부착.
        _ensure_chat_log_handler()
        _chat_log.info("ChatPanel constructed model=%s show_thinking=%s",
                       initial_model_id, initial_show_thinking)

        # 모델 설치/다운로드 흐름 controller — Task 6. 현재는 handle_runtime_check +
        # signal 인터페이스만. _open_installer_for / _open_downloader_for 메서드
        # 이동은 Task 7 (GC lifetime 정리 후).
        self._install_controller = ModelInstallController(parent_widget=self)
        self._install_controller.fallback_requested.connect(self._fallback_combo_to)

        body = QWidget(self)
        body.setMinimumWidth(320)
        v = QVBoxLayout(body)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # ---- 메시지 리스트 ----
        # 채팅 표준: stretch 를 *맨 위*에 둬서 메시지가 아래쪽 정렬 (WhatsApp / Slack 스타일).
        # 콘텐츠가 viewport 보다 짧을 때 빈 공간이 *위*에 생기고, 콘텐츠가 늘어나면 아래에서
        # 차오르는 자연스러운 흐름. 이전 (stretch 아래) 은 콘텐츠 위 정렬이라 viewport 아래에
        # 빈 공간이 쌓여 보이는 문제 — 사용자가 "빈곳 늘어남" 으로 인지.
        self._messages_host = QWidget()
        self._messages_lay = QVBoxLayout(self._messages_host)
        # 오른쪽 8px 마진 — scrollbar 가 등장해도 콘텐츠가 scrollbar 와 겹치지 않게.
        # 사용자 보고 (2026-05-13): "스크롤바가 채팅 일부 가린다".
        self._messages_lay.setContentsMargins(0, 0, 8, 0)
        self._messages_lay.setSpacing(4)  # 기본 spacing 더 좁게 (log-line 들 많음).
        self._messages_lay.addStretch(1)
        # stretch index = 0 (맨 위). _insert_bubble 은 stretch *뒤에* 삽입.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # 가로 스크롤 절대 금지 — markdown 긴 줄이 wrap 되지 않고 viewport 넘어가던 사용자 보고
        # (2026-05-13: "채팅창 줄바꿈이 안되"). horizontal AsNeeded 가 켜져 있으면 QLabel
        # wordWrap 이 scrollbar 가 처리할 거라 생각해서 wrap 안 함. AlwaysOff 로 강제하면
        # widgetResizable=True 와 결합해 inner widget 폭 = viewport 폭 → wrap 작동.
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._messages_host)
        self._scroll.setStyleSheet("QScrollArea{background:#0a0f1e;border:none;}")
        # viewport resize 가 일어날 때 inner widget 의 maxWidth 를 viewport 폭으로 명시 강제.
        # widgetResizable=True 만으로는 안전하지 않음 — tool_result 같이 wordWrap 무시하는
        # 단일라인 sizeHint 가 wide 일 때 inner widget 이 sizeHint 따라 wide 해질 수 있음.
        # 명시 maxWidth = 모든 자식 bubble 의 강제 wrap 보장.
        self._scroll.viewport().installEventFilter(self)
        v.addWidget(self._scroll, 1)
        # 자동 스크롤: 사용자가 맨 아래 있을 때만 새 메시지에 자동 따라감.
        # 위로 스크롤해 과거 메시지 읽는 중이면 streaming 으로 강제 점프 안 함.
        # rangeChanged 가 layout 완료 후 발화 — _scroll_to_bottom 보다 정확.
        self._auto_scroll = True
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        # ---- 상태 라벨 (진행 중 / 완료 단발 메시지) ----
        self._status = QLabel("")
        self._status.setStyleSheet("color:#94a3b8;font-size:11px;padding:2px 4px;")
        self._status.setWordWrap(True)   # dock 좁아도 잘리지 않음.
        self._status.setVisible(False)
        v.addWidget(self._status)

        # 컨텍스트 바 → 모델 row 의 동그라미 아이콘으로 이동 (아래 model_row 참조).

        # ---- 모델 선택 + ctx 동그라미 + 추론 보기 (한 줄, compact) ----
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.setContentsMargins(0, 0, 0, 0)
        self._model_combo = QComboBox()
        # ModelRegistry 기반 — built-in 4개 (Sonnet/Opus/Haiku/Qwen) 자동 표시.
        # MODEL_OPTIONS 하드코딩 fallback 은 더 이상 사용 안 함 (backward-compat 으로 상수만 유지).
        self._model_registry = ModelRegistry()
        for meta in self._model_registry.all_models():
            display = meta.display_name
            # claude 외 runtime — 의존성 미설치면 "(설치 필요)" 라벨 + 사용자가 클릭하면
            # set_model 가드가 차단 → 콤보 fallback. 의존성 표시는 정보용일 뿐 disable 안 함.
            if meta.runtime != "claude" and not check_runtime_available(meta.runtime):
                display = f"{display} (설치 필요)"
            self._model_combo.addItem(display, userData=meta.id)
        # 초기 인덱스 — initial_model_id (저장된 ID) 매칭, 없으면 agent 의 현재 model,
        # 그것도 없으면 DEFAULT_MODEL_ID (Sonnet).
        desired_id = initial_model_id
        if not desired_id and self._agent is not None:
            desired_id = getattr(self._agent, "_model", None)
        if not desired_id:
            desired_id = DEFAULT_MODEL_ID

        # 시작 시 의존성 가드 — settings 가 의존성 없는 모델 (예: Qwen + PyTorch 미설치)
        # 을 가리키면 자동으로 DEFAULT_MODEL_ID 로 강등. 안 그러면 main_window 의
        # `agent.set_model(current_model_id())` 동기화나 어떤 자동 트리거가 installer
        # dialog 를 시작 시점에 띄울 위험 — 사용자가 KStudio 켤 때마다 PyTorch 설치
        # 다이얼로그 보이는 회귀 (2026-05-21 사용자 보고).
        self._startup_demoted_from: Optional[str] = None
        desired_meta = self._model_registry.get(str(desired_id)) if desired_id else None
        if desired_meta is not None and desired_meta.runtime != "claude":
            if not check_runtime_available(desired_meta.runtime):
                self._startup_demoted_from = desired_meta.display_name
                desired_id = DEFAULT_MODEL_ID

        initial_idx = 0
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == desired_id:
                initial_idx = i
                break
        self._model_combo.setCurrentIndex(initial_idx)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)
        self._model_combo.setStyleSheet(
            "QComboBox{background:#1e293b;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
        )
        # combo 자체가 가로로 가능한 작게 — 라벨(예: "Sonnet 4.6") 너비만큼.
        self._model_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._model_combo.setMinimumContentsLength(8)
        model_row.addWidget(self._model_combo)

        # 컨텍스트 사용률 동그라미 + % 라벨 — 첫 응답 전엔 숨김, 응답 후 색상 + 숫자.
        self._ctx_dot = QLabel()
        self._ctx_dot.setFixedSize(14, 14)
        self._ctx_dot.setVisible(False)
        self._ctx_dot.setToolTip("")
        self._set_ctx_dot_color("#64748b")
        model_row.addWidget(self._ctx_dot)

        self._ctx_pct_label = QLabel("")
        self._ctx_pct_label.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
        self._ctx_pct_label.setVisible(False)
        model_row.addWidget(self._ctx_pct_label)

        # /clear /compact 버튼 — 슬래시 명령과 동일 흐름. % 라벨 오른쪽에 붙음.
        _slash_btn_style = (
            "QPushButton{background:#1e293b;color:#cbd5e1;border:1px solid #334155;"
            "border-radius:3px;padding:1px 6px;font-size:11px;}"
            "QPushButton:hover{background:#334155;color:#f1f5f9;}"
        )
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setToolTip("/clear — 대화 초기화, 새 세션 시작")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setStyleSheet(_slash_btn_style)
        self._clear_btn.clicked.connect(lambda: self._handle_slash_command("/clear"))
        model_row.addWidget(self._clear_btn)

        self._compact_btn = QPushButton("Compact")
        self._compact_btn.setToolTip("/compact — Claude 에게 지금까지 대화 요약 요청")
        self._compact_btn.setCursor(Qt.PointingHandCursor)
        self._compact_btn.setStyleSheet(_slash_btn_style)
        self._compact_btn.clicked.connect(lambda: self._handle_slash_command("/compact"))
        model_row.addWidget(self._compact_btn)

        model_row.addStretch(1)

        # 추론(thinking) 표시 ON/OFF — Claude 의 내부 추론 + 도구 호출/결과 박스를 가리거나 보임.
        self._thinking_check = QCheckBox("추론 보기")
        self._thinking_check.setChecked(bool(initial_show_thinking))
        self._thinking_check.setStyleSheet(
            "QCheckBox{color:#94a3b8;font-size:11px;}"
            "QCheckBox::indicator{width:13px;height:13px;}"
        )
        self._thinking_check.setToolTip(
            "추론 보기: ON 이면 Claude 의 내부 사고 + 도구 호출/결과 표시. OFF 면 대화만."
        )
        self._thinking_check.toggled.connect(self._on_show_thinking_toggled)
        model_row.addWidget(self._thinking_check)
        v.addLayout(model_row)

        # 첨부 표시 — Ctrl+V 로 이미지 붙여넣으면 "📎 N개 첨부됨 [✕ 취소]" 표시.
        # QFrame 안에 라벨 + 취소 버튼 — 사용자가 잘못 paste 한 이미지 제거 가능.
        self._attach_row = QFrame()
        self._attach_row.setStyleSheet(
            "QFrame{background:#1e1b4b;border-radius:4px;}"
        )
        _attach_lay = QHBoxLayout(self._attach_row)
        _attach_lay.setContentsMargins(8, 3, 6, 3)
        _attach_lay.setSpacing(6)
        self._attach_label = QLabel("")
        self._attach_label.setStyleSheet("color:#a5b4fc;font-size:11px;background:transparent;")
        _attach_lay.addWidget(self._attach_label, 1)
        self._attach_cancel_btn = QPushButton("✕ 취소")
        self._attach_cancel_btn.setCursor(Qt.PointingHandCursor)
        self._attach_cancel_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#c4b5fd;border:1px solid #7c3aed;"
            "border-radius:3px;padding:1px 6px;font-size:11px;}"
            "QPushButton:hover{background:#7c3aed;color:white;}"
        )
        self._attach_cancel_btn.clicked.connect(self._on_attach_cancel)
        _attach_lay.addWidget(self._attach_cancel_btn)
        self._attach_row.setVisible(False)
        v.addWidget(self._attach_row)

        # ---- 입력 행 ----
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        input_row.setAlignment(Qt.AlignBottom)
        self._input = _ChatInputEdit()
        self._input.setPlaceholderText(
            "에이전트에게 질문 또는 명령... (Enter=보내기, Shift+Enter=줄바꿈)"
        )
        self._input.setStyleSheet(
            "QPlainTextEdit{background:#0f172a;color:#e2e8f0;border:1px solid #334155;"
            "border-radius:4px;padding:4px 6px;font-size:12px;}"
        )
        self._input.submit_requested.connect(self._on_submit)
        self._send_btn = QPushButton("보내기")
        self._send_btn.clicked.connect(self._on_submit)
        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.setStyleSheet(
            "QPushButton{background:#7f1d1d;color:#fef2f2;border:none;border-radius:4px;padding:4px 8px;}"
            "QPushButton:hover{background:#991b1b;}"
        )
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.setVisible(False)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        input_row.addWidget(self._cancel_btn)
        v.addLayout(input_row)

        self.setWidget(body)

        # 마지막으로 추가된 assistant / thinking 말풍선 (스트리밍 chunk 누적 대상).
        # 새 사용자 입력 또는 다른 role 메시지(tool_use 등) 도착 시 None 으로 reset.
        # SDK 의 include_partial_messages 가 thinking 도 partial 로 보내므로 누적 필수 —
        # 누적 안 하면 partial 마다 새 박스가 추가돼서 화면이 점프하며 빈 박스가 쌓임.
        self._current_assistant_bubble: Optional[_MessageBubble] = None
        self._current_thinking_bubble: Optional[_MessageBubble] = None
        # 최신 active proposals card — 외부에서 mark_resolved 호출 가능.
        self._active_proposals_card: Optional[_ProposalsPreviewCard] = None
        # 최신 active whisper download card.
        self._active_whisper_card: Optional[_WhisperDownloadCard] = None

        # 대화 영속화 — set_history_path 로 활성화. 메시지 추가마다 디바운스 저장.
        self._history_path: Optional[Path] = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1000)  # 1초 디바운스.
        self._save_timer.timeout.connect(self._flush_history)

        # 누적 토큰 사용량 — 매 ResultMessage 에 done detail 로 도착.
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        # 최근 턴의 입력 토큰 = 현재 컨텍스트 사용량 근사 (Claude 가 매 턴 전체 대화를 다시 읽음).
        self._last_input_tokens = 0
        # Ctrl+V 로 붙여넣은 PNG bytes 대기열 — 다음 submit 때 전달.
        self._pending_images: list[bytes] = []
        # 입력 위젯의 image_pasted 시그널 연결 — pending 에 추가 + 첨부 표시 갱신.
        self._input.image_pasted.connect(self._on_image_pasted)

        # PlanGate 연결 — plan_submitted 시그널 → _PlanCard 삽입.
        # plan_id → _PlanCard registry — plan_resolved 시 stale card 갱신용.
        self._plan_cards: dict[str, "_PlanCard"] = {}
        self._plan_gate: Optional[PlanGate] = plan_gate
        if self._plan_gate is not None:
            self._plan_gate.plan_submitted.connect(self._on_plan_submitted)
            self._plan_gate.plan_resolved.connect(self._on_plan_resolved)

    # ---- 외부 진입점 ----
    def append_message(self, msg: AgentMessage) -> None:
        """AgentRuntime.message_received 와 직접 연결 가능.

        thinking / tool_use / tool_result 는 새 말풍선으로. assistant 는 연속 청크
        면 이전 말풍선에 누적. tool_result 의 image_bytes 있으면 인라인 표시.
        proposals_preview 는 interactive 카드 (적용/취소 버튼) 로 표시.
        """
        # 추론 표시 OFF 면 thinking 뿐 아니라 도구 호출/결과도 숨김 — 사용자/Claude 대화만 보기.
        # tool_use/tool_result 는 Claude 의 *내부 작업* 이라 일반 대화 흐름에서 잡음으로 인식.
        if (msg.role in ("thinking", "tool_use", "tool_result")
                and not self._thinking_check.isChecked()):
            return
        if msg.role == "proposals_preview" and msg.proposals is not None:
            card = _ProposalsPreviewCard(msg.proposals)
            card.apply_clicked.connect(self.proposals_apply_confirmed)
            card.cancel_clicked.connect(self.proposals_apply_canceled)
            self._insert_bubble(card)
            self._active_proposals_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()
            return
        if msg.role == "whisper_download_request":
            # text 에 "model_size=base" 형식으로 Claude 가 제안한 크기.
            meta = self._parse_whisper_meta(msg.text)
            card = _WhisperDownloadCard(meta["model_size"])
            card.download_clicked.connect(self.whisper_download_confirmed)
            card.cancel_clicked.connect(self.whisper_download_canceled)
            self._insert_bubble(card)
            self._active_whisper_card = card
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()
            return
        # 같은 role 연속 streaming chunk 면 마지막 bubble 에 누적.
        if (msg.role == "assistant"
                and self._current_assistant_bubble is not None
                and not msg.image_bytes):
            self._current_assistant_bubble.append_text(msg.text)
        elif (msg.role == "thinking"
                and self._current_thinking_bubble is not None):
            self._current_thinking_bubble.append_text(msg.text)
        else:
            bubble = _MessageBubble(
                msg.role, msg.text,
                image_bytes=msg.image_bytes, image_mime=msg.image_mime,
            )
            self._insert_bubble(bubble)
            if msg.role == "assistant":
                self._current_assistant_bubble = bubble
                self._current_thinking_bubble = None
            elif msg.role == "thinking":
                self._current_thinking_bubble = bubble
                self._current_assistant_bubble = None
            else:
                # tool_use / tool_result / system / error 등 — streaming 누적 대상 아님.
                self._current_assistant_bubble = None
                self._current_thinking_bubble = None
        self._scroll_to_bottom()
        self._schedule_history_save()

    def mark_proposals_resolved(self, outcome: str) -> None:
        """외부에서 적용/취소 처리 완료 후 카드 상태 갱신.

        outcome: "applied" / "canceled".
        """
        if self._active_proposals_card is not None:
            self._active_proposals_card.mark_resolved(outcome)
            self._active_proposals_card = None

    @Slot(str, str)
    def mark_whisper_download_resolved(self, outcome: str, message: str = "") -> None:
        """Whisper 다운로드 카드 상태 갱신. outcome: 'done' / 'failed' / 'canceled'.

        @Slot 데코레이터로 QMetaObject.invokeMethod 에서 호출 가능하게 등록.
        """
        if self._active_whisper_card is not None:
            self._active_whisper_card.mark_resolved(outcome, message)
            self._active_whisper_card = None

    @staticmethod
    def _parse_whisper_meta(text: str) -> dict:
        """text 'model_size=base' → {model_size}."""
        out = {"model_size": "base"}
        for part in (text or "").split():
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "model_size":
                    out["model_size"] = v
        return out

    def append_event(self, evt: AgentEvent) -> None:
        """AgentRuntime.event_received 와 직접 연결 가능. 상태 라벨 + 보내기/취소 전환."""
        if evt.kind == "started":
            # 모델 이름 동적 표시 — Claude/Qwen/사용자 추가 모델 어느 것이든 정확히.
            model_label = self._model_combo.currentText() if self._model_combo else "에이전트"
            self._status.setText(f"{model_label} 응답 중… (도구 호출/추론 과정도 아래에 표시됨)")
            self._status.setVisible(True)
            self._send_btn.setVisible(False)
            self._cancel_btn.setVisible(True)
        elif evt.kind == "tool_use":
            self._status.setText(f"🔧 {evt.detail}")
            self._status.setVisible(True)
        elif evt.kind == "tool_result":
            pass
        elif evt.kind == "done":
            # detail 포맷 "in=N out=M" — 누적 토큰 + last_input 갱신.
            self._update_token_totals(evt.detail)
            self._update_ctx_bar()
            # 상태 라벨은 단발 메시지만 (컨텍스트는 ctx_bar 가 영속 표시).
            self._status.setText("완료")
            self._send_btn.setVisible(True)
            self._cancel_btn.setVisible(False)
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
        elif evt.kind == "error":
            err_bubble = _MessageBubble("error", f"⚠ 오류: {evt.detail}")
            self._insert_bubble(err_bubble)
            self._status.setVisible(False)
            self._send_btn.setVisible(True)
            self._cancel_btn.setVisible(False)
            self._current_assistant_bubble = None
            self._current_thinking_bubble = None
            self._scroll_to_bottom()

    def message_count(self) -> int:
        """테스트용 — addStretch 1개 제외한 실제 말풍선 개수."""
        return max(0, self._messages_lay.count() - 1)

    def last_bubble_role(self) -> Optional[str]:
        """테스트용 — 가장 최근 말풍선의 role.

        stretch 는 index 0, 말풍선은 그 뒤에 차례로 append → 마지막 = count()-1.
        """
        idx = self._messages_lay.count() - 1
        if idx <= 0:
            return None
        item = self._messages_lay.itemAt(idx)
        w = item.widget() if item else None
        return w.role() if isinstance(w, _MessageBubble) else None

    def current_model_id(self) -> str:
        return self._model_combo.currentData() or DEFAULT_MODEL_ID

    def show_thinking(self) -> bool:
        return self._thinking_check.isChecked()

    # ---- 대화 영속화 ----
    def set_history_path(self, path: Path) -> None:
        """디스크 경로 설정 + 즉시 로드."""
        self._history_path = Path(path)
        history = load_history(self._history_path)
        if history:
            sep = AgentMessage(
                role="system",
                text=f"이전 세션의 대화 {len(history)}건 복원됨.",
            )
            self.append_message(sep)
            for role, text in history:
                self.append_message(AgentMessage(role=role, text=text))

    def flush_history_now(self) -> None:
        """앱 종료 시 호출 — 디바운스 우회 즉시 저장."""
        self._save_timer.stop()
        self._flush_history()

    def _schedule_history_save(self) -> None:
        if self._history_path is not None:
            self._save_timer.start()  # 기존 타이머 리스타트.

    def _flush_history(self) -> None:
        if self._history_path is None:
            return
        try:
            messages: list[tuple[str, str]] = []
            # stretch 는 index 0, 말풍선은 그 뒤부터 — 순서대로 (oldest first).
            for i in range(1, self._messages_lay.count()):
                item = self._messages_lay.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, _MessageBubble) and w.role() in PERSISTABLE_ROLES:
                    messages.append((w.role(), w._raw_text))
            save_history(self._history_path, messages)
        except Exception:
            import logging
            logging.exception("chat history save failed")

    # ---- 내부 ----
    def _on_show_thinking_toggled(self, checked: bool) -> None:
        self.show_thinking_changed.emit(bool(checked))

    def _on_cancel_clicked(self) -> None:
        """진행 중 응답 취소 — runtime 이 task 를 cancel 시키고 error 이벤트로 종료."""
        self.cancel_requested.emit()
        self._cancel_btn.setEnabled(False)   # 다음 done/error 시 다시 활성.
        self._status.setText("취소 중…")

    def _update_token_totals(self, detail: str) -> None:
        """done detail ('in=1234 out=567 last_in=12345') 파싱.

        - in:       이 응답 안 모든 API 호출의 input_tokens 합 (누적용).
        - out:      output_tokens 합 (누적용).
        - last_in:  *마지막* API 호출 한 번의 context size (컨텍스트 % 용 — 200k 안에서 정확).

        SDK 가 ResultMessage.usage 에 응답 전체를 합산해서 줘서, 도구 호출 N번이면 input
        토큰이 N배 부풀려짐. last_in 은 마지막 AssistantMessage 의 usage 에서 별도 추출 —
        진짜 컨텍스트 윈도 사용량과 일치.
        """
        if not detail:
            return
        last_in_seen = False
        try:
            for part in detail.split():
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                n = int(v)
                if k == "in":
                    self._total_input_tokens += n
                    # last_in 이 따로 안 오면 backward compat 으로 in 을 last 로 사용.
                    if not last_in_seen:
                        self._last_input_tokens = n
                elif k == "out":
                    self._total_output_tokens += n
                elif k == "last_in":
                    self._last_input_tokens = n
                    last_in_seen = True
        except ValueError:
            pass

    def _context_summary(self) -> str:
        """상태 라벨 끝에 붙는 ' · 컨텍스트 12.3k/200k (6%)' 문자열.

        last_input_tokens 가 0 이면 (아직 응답 없음) 빈 string.
        """
        if self._last_input_tokens <= 0:
            return ""
        limit = _context_limit_for(self.current_model_id())
        pct = (self._last_input_tokens / limit) * 100.0 if limit > 0 else 0.0
        def _fmt(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        warn = " ⚠" if pct >= 70 else ""
        return f" · ctx {_fmt(self._last_input_tokens)}/{_fmt(limit)} ({pct:.0f}%){warn}"

    def _set_ctx_dot_color(self, hex_color: str) -> None:
        """동그라미 색 — stylesheet 로 원형 + 색 + 살짝 border."""
        self._ctx_dot.setStyleSheet(
            f"background:{hex_color};border:1px solid #0f172a;border-radius:7px;"
        )

    def _update_ctx_bar(self) -> None:
        """컨텍스트 동그라미 + % 라벨 — 첫 응답 후 영속 표시.

        색 = 사용률 (녹/노/빨). 라벨 = "X%" 숫자. tooltip = 상세 (ctx X/Y · 누적 in/out).
        """
        if self._last_input_tokens <= 0 and self._total_input_tokens <= 0:
            self._ctx_dot.setVisible(False)
            self._ctx_pct_label.setVisible(False)
            return
        limit = _context_limit_for(self.current_model_id())
        pct = (self._last_input_tokens / limit) * 100.0 if limit > 0 else 0.0
        def _fmt(n: int) -> str:
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        warn = " ⚠" if pct >= 70 else ""
        tooltip = (
            f"컨텍스트: {_fmt(self._last_input_tokens)} / {_fmt(limit)} ({pct:.0f}%){warn}\n"
            f"누적: in={self._total_input_tokens:,}  out={self._total_output_tokens:,}\n"
            f"70% 이상이면 /compact 또는 /clear 권장."
        )
        self._ctx_dot.setToolTip(tooltip)
        self._set_ctx_dot_color(_ctx_color_for(pct))
        self._ctx_dot.setVisible(True)
        # % 라벨 — 동그라미 색과 글자 색 동조.
        self._ctx_pct_label.setText(f"{pct:.0f}%{warn}")
        self._ctx_pct_label.setStyleSheet(
            f"color:{_ctx_color_for(pct)};font-size:11px;background:transparent;font-weight:600;"
        )
        self._ctx_pct_label.setToolTip(tooltip)
        self._ctx_pct_label.setVisible(True)

    def _refresh_context_status(self) -> None:
        """수동 trigger — /clear 직후처럼 done 이벤트 없이 갱신 필요한 경우."""
        self._update_ctx_bar()
        if self._last_input_tokens > 0 or self._total_output_tokens > 0:
            self._status.setText(f"준비됨{self._context_summary()}")
            self._status.setVisible(True)
        else:
            self._status.setVisible(False)

    def _on_model_changed(self, idx: int) -> None:
        """콤보 변경 → (Phase 3b) 의존성 + 캐시 단계별 체크 → set_model.

        분기:
        1) 의존성 미설치 → GpuInstallDialog(packages=PYTORCH_PACKAGES) — 설치 후 chain.
        2) 의존성 OK + 캐시 미스 → ModelDownloadWindow + ModelDownloadJob — 다운 후 chain.
        3) 둘 다 OK → 정상 set_model + 가드 fallback (claude→claude 도 안전).
        """
        model_id = self._model_combo.itemData(idx)
        if not model_id:
            return
        if self._agent is None:
            # 테스트 fixture 등 agent 미주입 — 단순 시스템 메시지만.
            self.append_message(AgentMessage(
                role="system",
                text=f"모델 전환: {self._model_combo.itemText(idx)}",
            ))
            self.model_changed.emit(str(model_id))
            return

        before = getattr(self._agent, "_model", None)
        if model_id == before:
            return

        meta = self._model_registry.get(str(model_id))
        if meta is None:
            return

        # claude 외 runtime — set_model 호출 *전* 에 의존성 + 캐시 체크.
        if meta.runtime != "claude":
            if not check_runtime_available(meta.runtime):
                self._open_installer_for(meta, before or "")
                return
            # ollama 는 HF 캐시 X — 자체 모델 스토어 (`ollama list`) 사용. HF
            # 다운로더 띄우면 잘못된 repo_id ('qwen3:8b') 로 다운 시도. 캐시 체크 건너뛰고
            # send_message 시점에 "ollama pull <tag>" 안내가 친절한 에러로 처리.
            if meta.runtime != "ollama":
                if meta.repo_id and not _models.is_model_cached(meta.repo_id):
                    self._open_downloader_for(meta, before or "")
                    return

        # 정상 set_model — Phase 3a 의 가드 fallback 동작 유지 (안전망).
        self._agent.set_model(str(model_id))
        after = getattr(self._agent, "_model", None)
        if after != model_id:
            # 런타임 가드가 차단 (드물지만 — race / 사이드 채널 등).
            self._fallback_combo_to(before or "")
            return
        self.append_message(AgentMessage(
            role="system",
            text=f"모델 전환: {self._model_combo.itemText(idx)}",
        ))
        self.model_changed.emit(str(model_id))

    def emit_startup_warnings(self) -> None:
        """KStudio 시작 시 강등된 모델이 있으면 사용자에게 알림.

        ChatPanel.__init__ 의 의존성 가드가 settings 의 모델을 default 로 강등한
        경우만 메시지 emit. main_window 가 ChatPanel 생성 직후 호출.
        """
        demoted = getattr(self, "_startup_demoted_from", None)
        if demoted:
            self.append_message(AgentMessage(
                role="system",
                text=(
                    f"⚠ 저장된 모델 '{demoted}' 의 의존성 (PyTorch 등) 이 미설치 — "
                    f"기본 모델 (Sonnet) 로 시작합니다. 콤보에서 다시 선택하면 1-클릭 "
                    f"설치 다이얼로그가 뜹니다."
                ),
            ))
            # 한 번만 알림 — 동일 메시지 중복 방지.
            self._startup_demoted_from = None

    def _fallback_combo_to(self, model_id: str) -> None:
        """콤보를 model_id 항목으로 되돌림 (signal recursion 방지 blockSignals)."""
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == model_id:
                self._model_combo.blockSignals(True)
                self._model_combo.setCurrentIndex(i)
                self._model_combo.blockSignals(False)
                return

    def _open_installer_for(self, meta, before: str) -> None:
        """PyTorch 1-클릭 설치 다이얼로그. 성공 시 set_model 재시도 (chain).

        finished_ok → importlib.invalidate_caches() 후 의존성 재체크.
          - 통과하면 _on_model_changed 다시 호출 → 다음 단계 (download or set_model).
          - 실패하면 (Windows DLL 등 — 같은 프로세스에서 import 안 됨) → "재시작 안내"
            시스템 메시지 + 콤보 fallback. **무한 chain 방지**.
        finished_error / rejected → 시스템 메시지 + 콤보 fallback.

        진입 시 이미 다이얼로그가 떠있으면 raise 만 — 중복 다이얼로그 방지.
        """
        # 중복 방지: 이미 설치 다이얼로그 진행 중이면 그걸 raise.
        existing = getattr(self, "_pending_install_dialog", None)
        try:
            already_open = (
                existing is not None
                and not existing.isHidden()   # destroy 된 후엔 raise
            )
        except RuntimeError:
            # C++ 객체 destroy 된 경우 — Qt 의 isHidden 가 raise.
            already_open = False
        if already_open:
            existing.raise_()
            existing.activateWindow()
            return

        # NVIDIA GPU 감지 → CUDA wheel 인덱스 자동 선택. None 이면 default CPU wheel.
        index_url = _pytorch_index_url_for_install()
        has_gpu = _detect_nvidia_gpu()
        if index_url:
            gpu_note = (
                f"✓ NVIDIA GPU 감지됨 — CUDA 13.0 wheel (~3GB) 설치 (GPU 가속)."
            )
        elif has_gpu:
            # GPU 있는데 이미 CUDA torch 동작 — 보통 여기 못 옴 (체크가 위에서 잡힘).
            gpu_note = "✓ NVIDIA GPU + CUDA torch 동작 중."
        else:
            gpu_note = (
                "⚠ NVIDIA GPU 미감지 — CPU wheel 설치 (Qwen 동작은 가능하나 매우 느립니다)."
            )
        info = (
            f"{meta.display_name} 사용에 필요한 PyTorch 패키지를 venv 안에 설치합니다.\n"
            f"{gpu_note}\n"
            f"설치 후 자동으로 모델 다운로드 단계로 진행됩니다.\n"
            f"(설치 완료 후 import 가 안 되면 KStudio 재시작이 필요할 수 있습니다.)"
        )
        dlg = GpuInstallDialog(
            parent=self,
            packages=PYTORCH_PACKAGES,
            title="PyTorch 설치",
            info_text=info,
            index_url=index_url,
        )

        # GpuInstallDialog 의 close_btn → QDialog.close() → rejected emit (accept() 안 부름).
        # 즉, 설치 성공 후에도 닫기 누르면 rejected 가 발화. 따라서 finished_ok/error 가 먼저
        # 처리되었다면 rejected 는 무시해야 함 — idempotency guard 로 fallback 중복 방지.
        state = {"handled": False}

        def _on_install_ok() -> None:
            state["handled"] = True
            # pip 가 venv 에 추가한 패키지를 import 시스템이 즉시 인식하도록 캐시 무효화.
            # 그래도 import 안 되는 경우 (Windows DLL / native ext 등) → 재시작 안내.
            import importlib
            importlib.invalidate_caches()
            if check_runtime_available(meta.runtime):
                # 의존성 OK — chain (download or set_model 단계).
                self._on_model_changed(self._model_combo.currentIndex())
            else:
                # 같은 프로세스에선 import 불가 — 재시작 안내 + chain 중단 (무한 루프 방지).
                self.append_message(AgentMessage(
                    role="system",
                    text=(
                        f"✓ 설치 완료. 다만 같은 KStudio 프로세스에서 즉시 import 가 안 됩니다. "
                        f"KStudio 를 재시작한 후 다시 {meta.display_name} 를 선택하세요."
                    ),
                ))
                self._fallback_combo_to(before)

        def _on_install_err(msg: str) -> None:
            state["handled"] = True
            self._on_install_or_download_failed(before, msg)

        def _on_install_rejected() -> None:
            # finished_ok 또는 finished_error 가 이미 처리됐으면 rejected 는 단순 닫기 신호.
            # 처리 안 됐다면 = 설치 시작 전/중에 닫음 → 사용자 취소로 간주 + 콤보 fallback.
            if not state["handled"]:
                self._on_install_or_download_failed(before, "사용자 취소")

        dlg.finished_ok.connect(_on_install_ok)
        dlg.finished_error.connect(_on_install_err)
        dlg.rejected.connect(_on_install_rejected)
        dlg.show()
        # 다이얼로그 참조 유지 — 가비지 컬렉터가 곧바로 destroy 하지 않도록.
        self._pending_install_dialog = dlg

    def _open_downloader_for(self, meta, before: str) -> None:
        """모델 다운로드 + ModelDownloadWindow. 완료 시 set_model 재시도 (chain).

        finished → 다시 _on_model_changed → 이번엔 캐시 hit 라 정상 set_model.
        error → 시스템 메시지 + 콤보 fallback.
        """
        win = ModelDownloadWindow(
            repo_id=meta.repo_id,
            display_name=meta.display_name,
            estimated_size_gb=meta.estimated_size_gb,
            parent=self,
        )
        win.set_phase("downloading")
        win.show()

        job = _models.ModelDownloadJob(
            repo_id=meta.repo_id,
            estimated_size_bytes=int(meta.estimated_size_gb * 1024 * 1024 * 1024),
            poll_interval_ms=500,
        )
        job.download_progress.connect(win.update_progress)

        # 영구 인디케이터: GlobalToolbar 의 라벨도 같이 갱신 — 사용자가
        # ModelDownloadWindow 를 닫아도 진행률 잃지 않게.
        display_name = meta.display_name
        def _emit_global_progress(received: int, total: int) -> None:
            self.download_progress_changed.emit(received, total, display_name)
        job.download_progress.connect(_emit_global_progress)

        def _on_finished(repo_id: str) -> None:
            win.set_phase("done")
            win.append_log(f"다운로드 완료: {repo_id}")
            self.download_finished.emit()   # 라벨 숨김.
            # 다시 _on_model_changed — 이번엔 캐시 hit 라 정상 set_model 진행.
            self._on_model_changed(self._model_combo.currentIndex())

        def _on_error(msg: str) -> None:
            win.set_phase("error")
            win.append_log(f"오류: {msg}")
            self.download_finished.emit()   # 라벨 숨김 (에러도).
            self._on_install_or_download_failed(before, msg)

        job.finished.connect(_on_finished)
        job.error.connect(_on_error)
        job.start()
        # 참조 유지 — 윈도우와 잡 모두 GC 방지.
        self._pending_download_job = job
        self._pending_download_window = win

    def _on_install_or_download_failed(self, fallback_model_id: str, msg: str) -> None:
        """설치/다운로드 실패 또는 사용자 취소 시 — 시스템 메시지 + 콤보 fallback."""
        if fallback_model_id:
            self.append_message(AgentMessage(
                role="system",
                text=f"⚠ 설치/다운로드 중단: {msg}. 모델을 이전 선택으로 되돌립니다.",
            ))
            self._fallback_combo_to(fallback_model_id)

    def _on_submit(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        _chat_log.info("submit text_len=%d n_attached_images=%d preview=%r",
                       len(text), len(self._pending_images),
                       (text[:80] + "…") if len(text) > 80 else text)
        self._input.clear()
        self._current_assistant_bubble = None
        self._current_thinking_bubble = None
        # 사용자가 새 메시지 보낼 때는 자동 스크롤 강제 활성 — 답이 보여야 하니까.
        self._auto_scroll = True
        # 슬래시 명령 — Claude 호출 없이 로컬 처리.
        if text.startswith("/"):
            if self._handle_slash_command(text):
                return
            # 알 수 없는 명령은 system 메시지 안내 후 종료.
            self.append_message(AgentMessage(
                role="system",
                text=f"알 수 없는 명령: `{text}`. `/help` 로 사용 가능한 명령 확인.",
            ))
            return
        # pending 이미지 첨부 (Ctrl+V paste) 있으면 같이 전달, 없으면 빈 list.
        images = list(self._pending_images)
        self._pending_images.clear()
        self._refresh_attach_label()
        # 사용자 말풍선은 이미지 썸네일도 같이 보여줌 — 첫 이미지만 (여러 장이면 텍스트로 표기).
        first_img = images[0] if images else None
        msg_text = text
        if len(images) > 1:
            msg_text = f"{text}\n\n[+{len(images) - 1} more images]"
        self.append_message(AgentMessage(
            role="user", text=msg_text,
            image_bytes=first_img, image_mime="image/png" if first_img else None,
        ))
        self.user_submitted.emit(text, images)

    def _handle_slash_command(self, text: str) -> bool:
        """슬래시 명령 처리. True 면 처리됨, False 면 unknown → 안내 메시지.

        /clear   — 모든 말풍선 제거 + 누적 토큰 0 + clear_requested emit (runtime 이 client 끊고
                    다음 send 시 새 세션).
        /compact — compact_requested emit (runtime 이 Claude 에게 요약 부탁 + history 교체).
        /help    — 가용 명령 목록 system 메시지로.
        """
        cmd = text.split()[0].lower()
        _chat_log.info("slash_command %s", cmd)
        if cmd == "/clear":
            self._clear_messages()
            self._total_input_tokens = 0
            self._total_output_tokens = 0
            self._last_input_tokens = 0
            self._ctx_dot.setVisible(False)   # 컨텍스트 동그라미도 숨김.
            self.append_message(AgentMessage(
                role="system",
                text="대화 초기화 완료. 다음 메시지는 새 세션으로 시작합니다.",
            ))
            self._refresh_context_status()
            self.clear_requested.emit()
            return True
        if cmd == "/compact":
            self.append_message(AgentMessage(
                role="system",
                text="Claude 에게 지금까지 대화 요약 요청 중…",
            ))
            self.compact_requested.emit()
            return True
        if cmd == "/help":
            lines = ["**사용 가능한 명령**:"]
            for name, desc in SLASH_COMMANDS:
                lines.append(f"- `{name}` — {desc}")
            self.append_message(AgentMessage(role="system", text="\n".join(lines)))
            return True
        return False

    def eventFilter(self, obj, event):
        """scroll viewport 의 resize 를 잡아 inner widget maxWidth 강제 — wrap 보장.

        widgetResizable=True 와 horizontalScrollBarPolicy=AlwaysOff 만으로는 충분하지 않음.
        자식 bubble 의 sizeHint 가 wide 면 그 따라 _messages_host 가 wide 해져 wrap 무력화.
        viewport resize 마다 명시 setMaximumWidth 로 강제.
        """
        from PySide6.QtCore import QEvent
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._messages_host.setMaximumWidth(event.size().width())
        return super().eventFilter(obj, event)

    def _on_image_pasted(self, png_bytes: bytes) -> None:
        """Ctrl+V — 입력창에 이미지 붙여넣었을 때 pending 에 누적."""
        if not png_bytes:
            return
        self._pending_images.append(png_bytes)
        self._refresh_attach_label()

    def _refresh_attach_label(self) -> None:
        """pending 첨부 row 갱신. 0 이면 숨김. 라벨 텍스트 + 취소 버튼 같이 표시."""
        n = len(self._pending_images)
        if n <= 0:
            self._attach_row.setVisible(False)
            return
        self._attach_label.setText(
            f"📎 이미지 {n}개 첨부됨 — 보내기 시 Claude 에게 함께 전송"
        )
        self._attach_row.setVisible(True)

    def _on_attach_cancel(self) -> None:
        """첨부된 이미지 전부 취소 — pending 비우고 라벨 숨김."""
        self._pending_images.clear()
        self._refresh_attach_label()

    def _clear_messages(self) -> None:
        """말풍선 전부 제거 — stretch (index 0) 는 유지.

        stretch 뒤의 항목들만 takeAt(1) 로 반복 제거. stretch 까지 제거하면 다음
        insert 시 아래쪽 정렬이 깨짐.
        """
        while self._messages_lay.count() > 1:
            item = self._messages_lay.takeAt(1)   # index 1 = stretch 바로 뒤.
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._active_proposals_card = None
        self._active_whisper_card = None
        self._current_assistant_bubble = None
        self._current_thinking_bubble = None
        # 영속화도 즉시 반영.
        self._schedule_history_save()

    def _insert_bubble(self, bubble: _MessageBubble) -> None:
        # stretch 가 *맨 위* (index 0) 에 있으니, 그 *뒤*에 차례로 append.
        # 결과: stretch / oldest_bubble / ... / newest_bubble — 콘텐츠는 아래로 쌓임.
        self._messages_lay.addWidget(bubble)

    @Slot(str, str, str)
    def _on_plan_submitted(self, plan_id: str, summary: str, markdown: str) -> None:
        """PlanGate.plan_submitted → 새 _PlanCard 생성 + 메시지 영역에 삽입."""
        card = _PlanCard(plan_id=plan_id, summary=summary, markdown=markdown)
        # plan_id 를 lambda 에 capture — 여러 plan 동시 처리 시 섞이지 않음.
        card.approved.connect(lambda pid=plan_id: self._plan_gate.approve(pid))
        card.rejected.connect(lambda reason, pid=plan_id: self._plan_gate.reject(pid, reason))
        self._plan_cards[plan_id] = card
        self._messages_lay.addWidget(card)
        self._scroll_to_bottom()

    @Slot(str, str)
    def _on_plan_resolved(self, plan_id: str, outcome: str) -> None:
        """PlanGate.plan_resolved → 기존 PlanCard 의 버튼 잠금 + 헤더 갱신.

        cancel_all 이 외부 트리거 (새 메시지 / cancel) 로 발생한 경우 stale card 가
        클릭 가능한 채로 남는 UX 갭 fix. approve/reject 도 emit 하지만 그 경로는
        이미 card 가 self._decided=True 라 동작 noop.
        """
        card = self._plan_cards.pop(plan_id, None)
        if card is None:
            return
        card.mark_externally_resolved(outcome)

    def _scroll_to_bottom(self) -> None:
        """즉시 한 번 — 이후 rangeChanged 가 layout 후 다시 호출해 정확히 정렬."""
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll_range_changed(self, _min: int, _max: int) -> None:
        """메시지/스트리밍으로 컨텐츠 크기 변할 때 — auto_scroll 이면 바닥 유지."""
        if self._auto_scroll:
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _on_scroll_value_changed(self, value: int) -> None:
        """사용자가 직접 스크롤한 경우 — 맨 아래면 auto 재활성, 위로 가면 비활성."""
        bar = self._scroll.verticalScrollBar()
        # 20px 임계값 — 사용자가 살짝 위로 스크롤했어도 auto 유지 (한 줄 분량 여유).
        self._auto_scroll = value >= bar.maximum() - 20
