"""KStudio 한글 → 영문 번역 사전.

추가 규칙:
- key 는 코드의 한글 원문 그대로 (공백, 특수문자, 줄바꿈 포함).
- 번역어는 자연스러운 영문. UI 에 보일 길이를 의식 (한글보다 길어지면 레이아웃
  깨질 수 있음 — 너무 길면 축약).
- Single source of truth: 같은 한글이 두 곳에 나오면 같은 영어로 통일.

이 모듈을 import 하면 자동으로 register() 호출됨 (모듈 부팅 시 사전 등록).
"""
from __future__ import annotations
from .i18n import register


_EN: dict[str, str] = {
    # ===== 메뉴 / 글로벌 액션 =====
    "파일": "File",
    "편집": "Edit",
    "편집 모드 켜기/끄기 (Ctrl+E)": "Toggle edit mode (Ctrl+E)",
    "보기": "View",
    "창": "Window",
    "이미지": "Image",
    "녹화": "Record",
    "도움말": "Help",
    "새로 만들기…": "New…",
    "열기…": "Open…",
    "저장": "Save",
    "저장…": "Save…",
    "다른 이름으로 저장": "Save As",
    "다른 이름으로 저장…": "Save As…",
    "내보내기": "Export",
    "저장 폴더 열기": "Open Save Folder",
    "환경설정": "Preferences",
    "환경설정…": "Preferences…",
    "종료": "Quit",
    "실행 취소": "Undo",
    "실행취소": "Undo",
    "다시 실행": "Redo",
    "다시실행": "Redo",
    "잘라내기": "Cut",
    "복사": "Copy",
    "붙여넣기": "Paste",
    "전체 선택": "Select All",
    "선택 해제": "Deselect",
    "정보": "About",
    "원본 (100%)": "Actual Size (100%)",
    "도구 팔레트": "Tool Palette",
    "레이어 (이미지 모드 전용)": "Layers (Image mode)",
    "녹화 상태 (영상 모드 전용)": "Recording Status (Video mode)",
    "배경 제거 (누끼)": "Remove Background",
    "이미지 크기 변경…": "Resize Image…",
    "정지": "Stop",

    # ===== 녹화 / 캡처 글로벌 툴바 =====
    "▭ 지정 영역": "▭ Region",
    "🪟 특정 창": "🪟 Window",
    "🖥 전체화면": "🖥 Fullscreen",
    "🎞 영상": "🎞 Video",
    "🖼 이미지": "🖼 Image",
    "영상": "Video",
    "GIF": "GIF",
    "녹화": "Record",
    "녹화 시작": "Start Recording",
    "녹화 정지": "Stop Recording",
    "일시정지": "Pause",
    "재개": "Resume",
    "이어서 녹화": "Resume",
    "스크린샷": "Screenshot",
    "전체 화면으로 전환": "Switch to fullscreen",
    "영역 캡처": "Capture Region",
    "전체 캡처": "Capture Full",
    "영역 녹화": "Region Record",
    "영역 스크린샷": "Region Screenshot",
    "영역 녹화 단축키 (3-state 무장→시작→정지)":
        "Region record shortcut (3-state arm → start → stop)",
    "영역 스크린샷 단축키": "Region screenshot shortcut",
    "전체화면 캡처/녹화 시 사용할 모니터 — 전체 모니터 또는 1개 선택":
        "Monitor to use for fullscreen capture/recording — all or one",
    "전체화면용 모니터 선택": "Select monitor for fullscreen",
    "전체 모니터": "All monitors",
    "✨ 배경 제거": "✨ Remove Background",
    "활성 ImageLayer 의 배경을 제거 (Ctrl+Shift+B)":
        "Remove background of active ImageLayer (Ctrl+Shift+B)",
    "설정": "Settings",
    "환경설정 (Ctrl+,)": "Preferences (Ctrl+,)",
    "복사": "Copy",

    # ===== 영상 모드 =====
    "● REC": "● REC",
    "◆ GIF": "◆ GIF",
    "◇ 대기 중": "◇ Standby",
    "● 대기 중": "● Standby",
    "재생/일시정지 (Space)": "Play / Pause (Space)",
    "음소거 (M)": "Mute (M)",
    "이전 프레임 (D)": "Previous frame (D)",
    "다음 프레임 (F)": "Next frame (F)",
    "풀스크린": "Fullscreen",
    "현재 프레임 → 스크린샷 탭 (Ctrl+Shift+P)":
        "Current frame → Screenshot tab (Ctrl+Shift+P)",

    # ===== 라이브러리 / 탭 =====
    "라이브러리": "Library",
    "이름 변경": "Rename",
    "삭제": "Delete",
    "복원": "Restore",
    "사본 만들기": "Duplicate",

    # ===== 도구 (이미지 편집) =====
    "선택": "Select",
    "이동": "Move",
    "자르기": "Crop",
    "사각형": "Rectangle",
    "화살표": "Arrow",
    "텍스트": "Text",
    "브러시": "Brush",
    "지우개": "Eraser",
    "마법봉": "Magic Wand",
    "마스크 페인트": "Mask Paint",
    "배경 제거": "Remove Background",
    "이미지 크기 변경": "Resize Image",
    "AI 업스케일": "AI Upscale",

    # ===== 드래그 저장 =====
    "이 버튼을 드래그해서 폴더에 놓으면 이미지로 저장됩니다":
        "Drag this button to a folder to save the image",
    "드래그 저장 실패": "Drag save failed",
    "임시 파일을 만들 수 없습니다:\n{e}":
        "Could not create temporary file:\n{e}",

    # ===== 풀스크린 =====
    "KStudio - 풀스크린": "KStudio - Fullscreen",

    # ===== 에러 / 알림 =====
    "녹화 종료 중 문제: {e}": "Recording finished with issue: {e}",
    "Capture target unavailable": "Capture target unavailable",

    # ===== 환경설정 =====
    "일반": "General",
    "단축키": "Shortcuts",
    "언어": "Language",
    "한국어": "Korean",
    "영어": "English",
    "확인": "OK",
    "취소": "Cancel",
    "적용": "Apply",
    "Windows 시작 시 자동 실행": "Run at Windows startup",
    "녹화 중 메인 창을 트레이로 숨기기": "Hide main window to tray during recording",
    "녹화 중 미니 컨트롤(⏹ ⏸) 표시": "Show mini control (⏹ ⏸) during recording",
    "언어 변경은 앱 재시작 후 적용됩니다.": "Language change takes effect after restart.",

    # ===== 영상 효과 편집 모드 (Stage 2+) =====
    "효과를 선택하면 여기에 옵션이 표시됩니다.": "Select an effect to see its options here.",
}



register({k: {"en": v} for k, v in _EN.items()})
