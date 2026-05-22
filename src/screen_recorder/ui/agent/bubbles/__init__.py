"""말풍선 위젯 패키지 — chat_panel.py 에서 분리 (Task 7).

각 위젯은 public 이름 (MessageBubble 등) 으로 노출. chat_panel.py 는 기존 코드
호환 위해 import 시점에 underscore alias 부여.
"""
from .message_bubble import MessageBubble
from .plan_card import PlanCard
from .proposals_preview_card import ProposalsPreviewCard
from .whisper_download_card import WhisperDownloadCard

__all__ = [
    "MessageBubble",
    "PlanCard",
    "ProposalsPreviewCard",
    "WhisperDownloadCard",
]
