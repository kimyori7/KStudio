"""Claude Agent SDK 런타임 래퍼 + Qt 시그널 어댑터.

스레드 모델 (2026-05-13 수정):
- worker 스레드는 자체 asyncio loop 만 돌림 (Qt event loop X).
- UI → worker: `asyncio.run_coroutine_threadsafe()` 로 직접 코루틴 스케줄.
  (이전엔 Qt signal 로 보냈는데 worker 가 Qt event queue 처리 못해 dead-end.)
- worker → UI: Qt signal emit — main 스레드는 Qt event loop 가 있어 자동 큐잉.

스트리밍:
- `include_partial_messages=True` — 부분 메시지 즉시 표시.
- `ThinkingBlock` — Claude 의 추론 과정도 별도 메시지 (`role="thinking"`).
- `ToolUseBlock` — 도구 호출 시점 + 입력값 표시.

Phase B 편집 제안:
- VideoTools 의 apply 콜백이 `proposals_apply_requested` 시그널 emit → UI 슬롯에서
  처리 → `concurrent.futures.Future` 로 worker 측에 결과 전달.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .tools_video import VideoTools, VideoSessionAdapter
from .proposals import EffectProposal, ProposalQueue
from .plan_gate import PlanGate
from .backends.claude_backend import ClaudeBackend
# AgentMessage / AgentEvent 는 backends/base.py 로 이전 — 외부 호환 위해 re-export.
from .backends import AgentEvent, AgentMessage, ChatInput
from .backends.factory import create_backend, build_backend_tools, runtime_dependency_label
from .models import ModelRegistry, check_runtime_available


_log = logging.getLogger(__name__)


# Claude 에게 매 세션마다 주입하는 시스템 프롬프트. 모듈 상수로 둬서 회귀 테스트 가능.
# 수정 시 좌표 정확도 회귀 위험 — `tests/test_agent_system_prompt.py` 도 같이 검토.
SYSTEM_PROMPT = (
    "당신은 KStudio 영상 편집 보조 에이전트입니다. 사용자의 한국어 요청을 받아 "
    "도구를 호출해 영상 상태를 확인하고 답변하세요.\n"
    "\n"
    "사용 가능한 도구 (모두 mcp__kstudio_video__ prefix):\n"
    "- 읽기: get_video_state / get_sidecar_summary / get_effects_in_range / get_duration_ms / get_current_position_ms\n"
    "- 보기: get_frame_at(ms, width) / get_timeline_strip(start_ms, end_ms, n=8)\n"
    "- 계획 (편집 전 필수): submit_plan(summary, markdown) — 사용자 ✓/✗ 게이트\n"
    "- 편집: propose_effect(type, payload) / propose_remove_effect(effect_id) / propose_modify_effect(effect_id, payload) / list_proposals / discard_proposals / apply_proposals\n"
    "- 미리보기: preview_proposal(proposal_id, ms, width) — apply 전에 효과 결과 확인 (zoom/arrow/caption)\n"
    "- 자막: transcribe_video / get_transcript_range(start_ms, end_ms) / get_transcript_status / download_whisper_model\n"
    "\n"
    "원칙:\n"
    "0. **편집 전 plan 제출 필수**: propose_effect / propose_remove_effect / "
    "propose_modify_effect / apply_proposals 호출 전에 반드시 submit_plan(summary, markdown) "
    "으로 무엇을 할지 한국어로 사용자에게 제출. 사용자가 ✓ 하면 도구가 {\"approved\": true} "
    "응답 → 그때 propose_*. ✗ + reason 받으면 reason 보고 plan 수정해 submit_plan 재호출. "
    "단순 정보 조회 (get_*, list_proposals, preview_proposal, transcribe_*) 는 plan 없이 자유.\n"
    "\n"
    "Plan 본문 작성 가이드:\n"
    "- summary: 1줄 (PlanCard 헤더). 예 '필러 단어 12곳 cut + 자막 5개 추가'.\n"
    "- markdown: 3~10줄. 각 효과 종류 + ms 구간 + 이유. "
    "좌표 결정 (zoom/arrow/caption) 은 plan 작성 *이전* 에 아래 5단계 (get_frame_at → "
    "픽셀 위치 묘사 → 정규화 → 자기 검증) 를 끝내고 plan 본문에 결과 좌표 포함.\n"
    "\n"
    "1. 사용자가 영상 내용을 묻기 시작하면 먼저 get_video_state + get_sidecar_summary 로 큰 그림 파악.\n"
    "2. 특정 시점·구간이 궁금하면 get_effects_in_range 또는 get_timeline_strip 사용 — 전체 덤프 X.\n"
    "3. 편집은 propose_* 로 큐에 쌓은 뒤 apply_proposals 호출 — **2026-05-14~ 자동 적용**: "
    "사용자 확인 카드 없이 즉시 sidecar 에 반영됨. 사용자는 잘못된 결과면 Ctrl+Z 로 되돌림. "
    "그래도 apply 전에 list_proposals 로 *무엇을 적용할지* 한 줄 알려주고, 시각 효과는 "
    "preview_proposal 로 자기 검증 권장 — 한 번에 적용된 N 개 효과를 Ctrl+Z N 번이 필요하므로 "
    "처음부터 정확하게 propose 하는 게 사용자 부담 적음.\n"
    "4. 자막은 캐시 우선. get_transcript_range 가 캐시 miss 면 사용자 확인 후 transcribe_video.\n"
    "5. 시간은 밀리초(int).\n"
    "\n"
    "**추측 금지 — 사실 주장은 반드시 도구 결과에 근거**:\n"
    "- 효과 *종류* (자르기/캡션/배속/줌/화살표/곁들임) 는 effects_by_type 또는 "
    "get_sidecar_summary / get_effects_in_range 결과에서 직접 확인. "
    "n_effects 숫자만 보고 '컷 N개' 같은 종류 추론 절대 금지.\n"
    "- 영상 길이 보고는 **세 값을 정확히 구분**해서 사용 (get_video_state 가 다 반환):\n"
    "  * `source_duration_ms`: 원본 파일 길이 (미디어 플레이어로 봤을 때 보이는 시간).\n"
    "  * `duration_ms`: 현재 *편집 타임라인* 길이 — **KStudio 의 cut 효과는 편집 타임라인에 "
    "즉시 적용 안 됨**. 사이드카에 마커로만 등록 → export 시점에 잘림. 그래서 cut 효과가 "
    "있어도 duration_ms = source_duration_ms 인 게 *정상 상태*. trim/segment 삭제 같은 "
    "트랙-수준 편집이 있을 때만 짧아짐.\n"
    "  * `export_duration_ms`: cut 효과 적용된 *예상 출력* 길이. = source - cut_planned_ms.\n"
    "  * `cut_planned_ms`: 단순 자르기 cut 효과들이 export 시 제거할 총 ms (B-roll 삽입 cut 제외).\n"
    "  사용자가 '이 영상 몇 분짜리야?' 같이 모호하게 물으면 *맥락 같이 제시*: "
    "'원본 X분짜리이고, 등록된 cut N개로 export 하면 Y분이 됩니다'. "
    "  **절대 안 됨**: duration_ms 만 보고 '2분 영상이네요' 처럼 한 값만 보고. "
    "사용자 사례 (2026-05-13/14): 원본 3분 24초인데 등록된 cut 2개 (총 84초) 가 있는 상태에서 "
    "에이전트가 'duration=204267 → 3분 24초, cut 적용 후 = 변화 없음' 식으로 보고하면서 사용자에게 "
    "'그래서 cut 이 적용된 거야 안 된 거야' 헷갈리게 함. 정답: '원본 3분 24초. 등록된 cut 2개로 "
    "export 시 약 2분 0초. 단, 편집 타임라인은 아직 3분 24초 그대로 — 자르기는 export 시점에만 "
    "적용됨'. 사용자가 '왜 안 잘렸어' 라고 하면 이 KStudio 동작을 친절히 설명.\n"
    "- 영상 *내용* (무엇이 보이는지, 어떤 도구 데모인지 등) 은 get_frame_at / "
    "get_timeline_strip / get_transcript_range 로 본 것만 묘사. 보지 않았으면 묘사 금지.\n"
    "- 한 번도 호출하지 않은 도구의 결과를 가정해서 말하지 마세요. "
    "예: 'cut 효과 2개 확인했습니다' — 그런 결과를 받은 적이 없으면 거짓.\n"
    "\n"
    "**좌표 시스템 기본**:\n"
    "- 모든 공간 좌표 (arrow.start/end, zoom.start/end 의 x,y) 는 **0~1 정규화**.\n"
    "  0,0 = 영상 프레임의 좌상단. 1,1 = 우하단. 0.5,0.5 = 중앙.\n"
    "- 픽셀 단위 값 (예: x=160, y=90) 은 **절대 금지** — propose 가 거부합니다.\n"
    "- get_timeline_strip 은 여러 썸네일 가로 합성 — 좌표 결정용 아님 (gestalt 전용).\n"
    "\n"
    "**시각 위치 결정 — 추측 금지, 단계별 진행**:\n"
    "사용자가 화면 안의 특정 객체를 가리키라고 하면 (예: '버튼에 화살표', "
    "'타이틀 강조해줘'), 추측으로 좌표를 만들지 마세요. 사용자 보고에 따르면 "
    "낮은 해상도에서 추측하면 실제 객체와 어긋난 위치를 자주 그립니다.\n"
    "\n"
    "다음 순서를 반드시 따르세요:\n"
    "1) get_frame_at(ms, width=960) — 위치를 결정하려면 *고해상도* 프레임 사용. "
    "기본 width=320 은 검증/요약용이지 위치 결정용 아님. 작은 UI 요소(글자/버튼)는 "
    "더 크게 (width=1280) 잡아야 정확.\n"
    "2) 받은 이미지에서 객체의 *픽셀 위치*를 한 줄로 명시: 예: '타이틀 \"새 기획서\"는 "
    "width=960 이미지에서 가로 ≈ 480px (이미지 중앙), 세로 ≈ 110px'.\n"
    "3) 정규화 계산: x = pixel_x / image_width, y = pixel_y / image_height. "
    "위 예시면 x = 480/960 = 0.5, y = 110/(960*9/16) ≈ 110/540 ≈ 0.20.\n"
    "4) 자기 검증 — 묘사한 위치와 계산된 좌표가 의미적으로 일치하는가? "
    "예: 묘사 '이미지 중앙'인데 x=0.12 면 모순. 다시 단계 2부터.\n"
    "5) propose_effect 호출.\n"
    "6) **자기 검증 (시각 효과 — zoom/arrow/caption 필수)**: preview_proposal(proposal_id, ms) "
    "로 결과 이미지 받아 확인. 묘사한 객체에 잘 닿는지 / zoom center 가 맞는지 / "
    "caption 위치가 맞는지 등. 어긋났으면 propose_modify_effect 로 좌표 보정 후 다시 preview.\n"
    "7) apply_proposals 로 최종 적용. 사용자가 '더 위로' 등 말하면 propose_modify_effect.\n"
    "\n"
    "단계 1~6 을 *생략하지 마세요*. 자기 검증 한 번이 빗나간 효과 그리고 사용자가 고치는 "
    "비용보다 훨씬 쌉니다.\n"
    "\n"
    "**zoom 좌표 의미 — 자주 헷갈림**: zoom 의 start/end x,y 는 *카메라 중심점* (시간 보간의 "
    "시작/끝). scale=1 일 때도 x,y 는 보간 경로에 영향 → 무시 안 됨. \n"
    "- 단순 중앙 줌: start=end=(0.5, 0.5, scale_start=1, scale_end=2).\n"
    "- 객체로 팬+줌: start=(0.5, 0.5, 1), end=(객체.x, 객체.y, 2). 객체 좌표는 위 5단계로 결정.\n"
    "\n"
    "**zoom mode — 사용자 보고 (2026-05-13): '줌은 화면 전체를 지정하고있어서 소용이 없어'**:\n"
    "zoom 은 2가지 모드 — 어느 쪽인지 *propose 전에 명확히 결정*:\n"
    "- `mode='fit_screen'` (기본, mode 생략 시): 화면 *전체* 가 (cx,cy) 중심으로 확대. "
    "프레젠테이션 영화적 줌. 화면 전체 흐름·분위기 강조에만 적합. "
    "scale=2 면 원본 절반 영역만 화면을 채움 — 나머지 잘려 안 보임. "
    "**작은 객체(버튼/아이콘/한 줄 텍스트) 강조에는 부적합** — 다른 부분이 안 보이므로 "
    "맥락이 사라지고 '소용없는 확대' 가 됨.\n"
    "- `mode='magnify_region'`: 원본은 그대로 두고 *작은 사각 영역만* 잘라 다른 위치에 "
    "크게 띄우는 돋보기. 버튼·아이콘·UI 요소 강조의 *기본 선택지*. 필드: "
    "region_w/h (원본에서 잡을 영역 크기, 0.05~1.0), dest_cx/cy (확대 결과 표시 위치), "
    "dest_w/h (확대 결과 크기). 보통 dest 는 빈 여백에 (예 dest_cx=0.75, dest_cy=0.25).\n"
    "\n"
    "**판단 규칙**: 사용자가 '버튼 강조해줘 / 이 부분 보여줘 / 작은 객체 짚어줘' 류면 "
    "**반드시 mode='magnify_region'** 사용. 화면 전체 분위기 줌인 (예: '이 장면 강조해줘', "
    "'시작 부분 임팩트') 일 때만 fit_screen. 확신 안 서면 magnify_region 으로 가서 "
    "preview_proposal 확인 — 사용자가 '이 부분만 강조하고 싶어' 라면 fit_screen 은 거의 항상 오답.\n"
    "\n"
    "**arrow 좌표 결정 — get_frame_at 없이 추측하면 빗나감 (반복 보고됨)**:\n"
    "arrow.start = 꼬리 (출발점, 원형 마커), arrow.end = 촉 (가리킬 대상). "
    "사용자 보고 '화살표가 어디를 가리키는지 모르겠음' 의 99% 는 get_frame_at 없이 "
    "추측한 좌표 때문. 반드시 위 5단계 (get_frame_at width=960~1280 → 픽셀 위치 묘사 → "
    "정규화 → propose → preview_proposal 검증) 거칠 것.\n"
)


class _AgentThread(QThread):
    """asyncio loop 만 돌리는 워커 스레드.

    Qt event loop 는 시작 안 함 — 외부와의 통신은 모두 `asyncio.run_coroutine_threadsafe`.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()

    def run(self) -> None:   # QThread override — 실제 워커 함수.
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        try:
            self._loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(self._loop)
                for t in pending:
                    t.cancel()
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            except Exception:
                pass
            self._loop.close()
            self._loop = None

    def loop(self) -> asyncio.AbstractEventLoop:
        """loop 가 준비될 때까지 (최대 5초) 대기. UI 측에서만 호출."""
        if not self._loop_ready.wait(timeout=5.0):
            raise RuntimeError("agent worker loop did not start in time")
        assert self._loop is not None
        return self._loop

    def stop_loop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)


class AgentRuntime(QObject):
    """UI 측 핸들. ChatPanel 이 이걸 통해 worker 와 통신.

    Phase A (read+visual) + Phase B (mutation) + 스트리밍 + thinking 표시.
    """

    message_received = Signal(object)              # AgentMessage
    event_received = Signal(object)                # AgentEvent
    # Phase B — (proposals: list[EffectProposal], future: concurrent.futures.Future)
    proposals_apply_requested = Signal(object, object)
    # Phase D — (model_size: str, future: concurrent.futures.Future)
    whisper_download_requested = Signal(object, object)

    def __init__(self, video_tools: VideoTools, cwd: Optional[Path] = None,
                 model: Optional[str] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._video_tools = video_tools
        # PlanGate 는 VideoTools 가 보유 — propose_* 도구와 같은 인스턴스 *반드시* 공유.
        # 두 인스턴스로 갈리면 UI 의 ✓ 가 mutation 도구 측에 전달 안 됨 → 게이트 영원히 닫힘.
        # AttributeError 면 wiring 회귀 — 즉시 노출되어야 silent split 방지.
        self._plan_gate = video_tools.plan_gate()
        self._cwd = cwd
        self._model = model or "claude-sonnet-4-6"   # 기본 Sonnet — Pro 정액제 친화적.
        self._thread = _AgentThread(self)
        self._started = False
        # 모델 레지스트리 — Qwen 등 다른 backend 라우팅.
        self._registry = ModelRegistry()
        # backend 는 model_id 에 따라 생성. 의존성 가드는 set_model 진입점에서만
        # (init 시점에 가드하면 사용자가 claude 로 시작했어도 qwen 의존성 체크해야 — 무관).
        meta = self._registry.get(self._model)
        if meta is None:
            raise ValueError(f"unknown model: {self._model}")
        self._backend = create_backend(meta, cwd=self._cwd)
        self._tools_dict: dict[str, Any] = {}
        self._build_tools_dict()
        self._session_started: bool = False

    def _build_tools_dict(self) -> None:
        """현 모델 metadata.runtime 보고 backend 별 tools dict 빌드.

        실제 조립 로직은 backends/factory.build_backend_tools 로 위임.
        """
        meta = self._registry.get(self._model)
        if meta is None:
            self._tools_dict = {
                "mcp_server": self._video_tools.mcp_server(),
                "allowed_tools": self._video_tools.tool_names(),
            }
            return
        self._tools_dict = build_backend_tools(meta, self._video_tools)

    # ---- Phase B 콜백 진입점 ----
    def emit_apply_request(
        self,
        proposals: list[EffectProposal],
        future: concurrent.futures.Future,
    ) -> None:
        """worker(asyncio) 스레드에서 호출 — Qt auto-queued connection 으로 UI 스레드
        에서 슬롯 수행. UI 측이 future.set_result() 호출까지 worker 가 await.
        """
        self.proposals_apply_requested.emit(proposals, future)

    def emit_whisper_download_request(
        self,
        model_size: str,
        future: concurrent.futures.Future,
    ) -> None:
        """Phase D — worker → UI 마샬링. UI 가 동의 카드 + 다운로드 후 future 해결."""
        self.whisper_download_requested.emit(model_size, future)

    def plan_gate(self) -> PlanGate:
        return self._plan_gate

    def _on_user_message_outgoing(self) -> None:
        """새 사용자 메시지 / 취소 / 세션 초기화. 이전 plan 승인 무효 + pending plan 거부.

        이 hook 이 있어야 Claude 가 이전 사용자 메시지의 ✓ 를 다음 메시지에 재사용 못 함.
        """
        self._plan_gate.cancel_all()
        self._plan_gate.invalidate_approval()

    # ---- 수명 관리 ----
    def start(self) -> None:
        if self._started:
            return
        self._thread.start()
        # loop 가 준비될 때까지 대기 (다음 send() 호출 직전에 race 없도록).
        self._thread.loop()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._on_user_message_outgoing()
        # 클라이언트 정리는 worker 스레드의 asyncio 루프 안에서 수행.
        loop = self._thread._loop
        if loop is not None:
            fut = asyncio.run_coroutine_threadsafe(self._backend.close(), loop)
            try:
                fut.result(timeout=2.0)
            except Exception:
                pass
        self._thread.stop_loop()
        self._thread.quit()
        self._thread.wait(3000)
        self._started = False

    # ---- UI 진입점 ----
    def send(self, prompt: str, images: Optional[list[bytes]] = None) -> None:
        """ChatPanel 에서 호출. worker 의 asyncio loop 에 코루틴 스케줄.

        images: PNG/JPEG bytes 리스트 — Ctrl+V 로 붙여넣은 스크린샷 등. Claude 가
        vision content block 으로 받아 분석 가능. None 이면 텍스트만.
        """
        self._on_user_message_outgoing()
        if not self._started:
            self.start()
        loop = self._thread.loop()
        asyncio.run_coroutine_threadsafe(
            self._run_query_with_backend(prompt, images), loop,
        )

    def cancel(self) -> None:
        """진행 중인 응답 취소 — backend.cancel() 이 내부 task 를 취소.

        SDK 의 receive_response() 가 CancelledError 로 풀리고 error 이벤트로 종료.
        새 send 후 정상 동작 복원.
        """
        self._on_user_message_outgoing()
        loop = self._thread._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._backend.cancel(), loop)

    def set_model(self, model_id: str) -> None:
        """모델 전환. 다른 runtime (claude → transformers 등) 이면 backend 자체 교체.

        다른 runtime 으로 전환 시 의존성 체크 — 없으면 가드 시스템 메시지 emit + model
        변경 차단 (호출자 = ChatPanel 이 콤보 fallback 처리).

        같은 runtime 안 모델 전환 (sonnet → opus) 은 dep check 안 함.
        """
        if not model_id or model_id == self._model:
            return

        old_meta = self._registry.get(self._model)
        new_meta = self._registry.get(model_id)
        if new_meta is None:
            _log.warning("set_model: unknown model_id %s — 무시", model_id)
            return

        # 다른 runtime 전환 시 의존성 가드.
        if old_meta and old_meta.runtime != new_meta.runtime:
            if not check_runtime_available(new_meta.runtime):
                deps_name = runtime_dependency_label(new_meta.runtime)
                self.message_received.emit(AgentMessage(
                    role="system",
                    text=(
                        f"⚠ {new_meta.display_name} 사용에 {deps_name} 가 필요합니다. "
                        f"현재 미설치 — 모델 관리 메뉴의 1-클릭 설치 (Phase 3b 예정) 또는 "
                        f"개발자 모드로 수동 설치 후 사용 가능. 모델은 변경되지 않았습니다."
                    ),
                ))
                # model 변경 차단.
                return

        self._model = model_id
        self._session_started = False

        loop = self._thread._loop
        same_runtime = old_meta and old_meta.runtime == new_meta.runtime
        if loop is not None:
            asyncio.run_coroutine_threadsafe(self._backend.close(), loop)
        if not same_runtime:
            # runtime 자체 변경 → 새 backend 생성. factory 가 ModelMetadata 로 분기.
            self._backend = create_backend(new_meta, cwd=self._cwd)
        # 모델(또는 runtime) 변경 시 tools_dict 재빌드 — tool_strategy 등 meta 변경 반영.
        self._build_tools_dict()

    def clear_session(self) -> None:
        """슬래시 `/clear` — 진행 중 응답 취소 + client disconnect. 다음 send 시 새 세션.

        UI 의 말풍선/토큰 카운터 초기화는 ChatPanel 측이 이미 수행.
        """
        self._on_user_message_outgoing()
        # 진행 중 task 가 있으면 취소.
        self.cancel()
        self._session_started = False
        loop = self._thread._loop
        if loop is not None:
            asyncio.run_coroutine_threadsafe(self._backend.close(), loop)

    def compact_session(self) -> None:
        """슬래시 `/compact` — Claude 에게 지금까지 대화 요약 부탁 후 새 세션 시작.

        구현 노트: 진정한 의미의 compact (요약본을 새 system prompt 로 prime) 는 SDK
        API 가 한정적이라 단순화 — 현재 client 에게 한 번 더 query 로 요약 요청만 보냄.
        실제 컨텍스트 줄이려면 사용자가 요약 확인 후 /clear 로 새 세션 시작.
        """
        if not self._started:
            return
        loop = self._thread.loop()
        prompt = (
            "지금까지 우리 대화를 5~10줄로 압축 요약해주세요. "
            "사용자가 원한 작업, 영상 상태, 이미 적용한 편집, 남은 할 일 위주로. "
            "이 요약을 본 뒤 사용자가 /clear 로 새 세션을 시작할 예정이니 핵심만."
        )
        asyncio.run_coroutine_threadsafe(
            self._run_query_with_backend(prompt), loop,
        )

    # ---- worker 측 코루틴 ----
    async def _run_query_with_backend(
        self, prompt: str, images: Optional[list[bytes]] = None,
    ) -> None:
        """backend 위임 — 첫 호출 시 start_session, 이후 send_message.

        모든 SDK 호출 + helper 로직은 ClaudeBackend 에 있음. 이 메서드는
        Qt Signal emit 을 위한 얇은 어댑터 역할만.
        """
        # 첫 호출이면 backend start_session.
        if not self._session_started:
            await self._backend.start_session(
                system_prompt=SYSTEM_PROMPT,
                tools=self._tools_dict,
                model=self._model,
            )
            self._session_started = True

        def _emit(item: Any) -> None:
            """backend 가 emit 하는 AgentMessage / AgentEvent → Qt Signal."""
            if isinstance(item, AgentMessage):
                self.message_received.emit(item)
            elif isinstance(item, AgentEvent):
                self.event_received.emit(item)

        msg = ChatInput(text=prompt, images=images)
        try:
            await self._backend.send_message(msg, _emit)
        except asyncio.CancelledError:
            # backend 가 이미 error 이벤트 emit + close 했음. 재진입 위해 session 재시작 플래그 OFF.
            self._session_started = False
            raise


