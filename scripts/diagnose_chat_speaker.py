"""채팅 화자 구분 진단 — user/assistant 헤더 + 색 대비가 실제로 '티나게' 보이는지,
이모지(🧑🤖)가 컬러로 렌더되는지 PNG 로 확인. (2026-05-29 사용자 보고: 구분 안 됨)

실행: python scripts/diagnose_chat_speaker.py  → test_chat_speaker.png 저장 후 Read.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from screen_recorder.ui.agent.bubbles.message_bubble import MessageBubble


# 화자 구분만 보는 진단이라 내용은 무의미해도 되지만, 실제와 같은 조건이어야
# 판정이 유효하다 — 짧은 말풍선/긴 말풍선, 한글 줄바꿈, 인라인 코드, 굵은 글씨,
# 그리고 도구 호출 쌍까지 한 화면에 섞여 있어야 한다.
CONV = [
    ("user", "응?"),
    ("assistant",
     "문서에 따르면, `autosave_interval` 을 넘겨 입력이 없으면 임시 저장이 한 번 "
     "일어나고, 진행 중이던 미리보기 렌더는 중단됩니다. 이 경우 편집기는 일반 "
     "대기 상태로 돌아갑니다."),
    ("user", "저장 중에 닫으면?"),
    ("assistant",
     "문서에 명시된 것은 자동 저장 규칙까지이며, 종료 시점의 처리는 따로 "
     "정의되어 있지 않습니다.\n\n1. **즉시 종료**: 대기 중인 작업은 버려질 수 있습니다.\n"
     "2. **저장 중 종료**: 쓰기가 중단되고 앱은 복구 절차를 수행합니다."),
    ("tool_use", "get_document_state()"),
    ("tool_result", '{"path": "...v3.md", "char_count": 8421, "is_dirty": false}'),
]


def build():
    host = QWidget()
    # 채팅 패널 어두운 배경 근사.
    host.setStyleSheet("background:#0b1220;")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(4)
    for role, text in CONV:
        lay.addWidget(MessageBubble(role, text))
    lay.addStretch(1)
    host.resize(380, 460)
    return host


app = QApplication(sys.argv)
host = build()
host.show()
app.processEvents()
app.processEvents()
host.grab().save("test_chat_speaker.png")
print("saved test_chat_speaker.png")
