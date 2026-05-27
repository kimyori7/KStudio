"""이미지 생성 패널 UI — 비모달 별창 형태 (2026-05-27 변경).

진입점:
- 도구 팔레트 "이미지 생성" 액션 (자동 누끼 아래)
- 창 메뉴 "이미지 생성" (Ctrl+Shift+G)
"""
from .image_gen_dialog import ImageGenDialog

__all__ = ["ImageGenDialog"]
