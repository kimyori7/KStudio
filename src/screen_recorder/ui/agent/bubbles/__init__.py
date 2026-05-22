"""말풍선 위젯 패키지 — chat_panel.py 에서 분리 (Task 7).

각 Step 완료 시마다 한 줄씩 추가.
"""
from .message_bubble import MessageBubble as _MessageBubble
from .whisper_download_card import WhisperDownloadCard as _WhisperDownloadCard
from .proposals_preview_card import ProposalsPreviewCard as _ProposalsPreviewCard

__all__ = ["_MessageBubble", "_WhisperDownloadCard", "_ProposalsPreviewCard"]
