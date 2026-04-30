"""자동 누끼 — rembg 모델 선택 다이얼로그.

rembg 는 다양한 사전 학습 모델을 지원한다. 각 모델은 학습 데이터셋과 목적이 달라
이미지 종류에 따라 결과 품질이 크게 갈린다 (예: 인물 사진은 u2net_human_seg 가
일반 u2net 보다 정확, UI/그래픽은 isnet-general-use 가 더 선명한 경계).
사용자가 자기 입력에 맞는 모델을 고르도록 라디오 + 설명 라벨로 노출.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget,
)


# (model_id, 표시 이름, 한 줄 설명)
# 권장도/일반성 순으로 정렬 — 가장 무난한 것부터.
MODELS: list[tuple[str, str, str]] = [
    (
        "u2net",
        "u2net (기본)",
        "일반 용도. 인물·동물·상품 사진에 가장 무난. 가장 많이 검증된 표준 모델.",
    ),
    (
        "isnet-general-use",
        "isnet-general-use",
        "신형 일반 모델. u2net 보다 경계가 선명한 경우가 많고 그래픽·UI 이미지에도 종종 더 잘 맞음.",
    ),
    (
        "u2netp",
        "u2netp (경량)",
        "u2net 의 가벼운 버전. 추론이 더 빠르지만 경계 정밀도는 낮음. 빠른 미리보기용.",
    ),
    (
        "silueta",
        "silueta (경량 일반)",
        "u2net 의 압축판. 작고 빠르며 품질은 비슷한 수준.",
    ),
    (
        "u2net_human_seg",
        "u2net_human_seg (인물 전용)",
        "사람 전신 분할에 특화. 인물 사진에서 일반 u2net 보다 정확.",
    ),
    (
        "isnet-anime",
        "isnet-anime (애니/만화 전용)",
        "애니메이션·일러스트 캐릭터 분할 전용. 실사 사진에는 부적합.",
    ),
    (
        "birefnet-general",
        "birefnet-general (고품질·무거움)",
        "최신 모델 중 품질이 가장 높은 편이지만 추론이 느리고 메모리도 가장 많이 씀.",
    ),
    (
        "birefnet-general-lite",
        "birefnet-general-lite",
        "birefnet 의 경량판. 품질·속도 균형. birefnet 풀 버전이 너무 느릴 때 대안.",
    ),
    (
        "birefnet-portrait",
        "birefnet-portrait (인물 고해상도)",
        "인물 사진 전용 고해상도 모델. 머리카락 등 미세한 경계가 중요할 때.",
    ),
]

_VALID_IDS = {mid for mid, _, _ in MODELS}


def _description_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #A0A4AB; padding-left: 22px; padding-bottom: 4px;")
    return lbl


class BgRemovalModelDialog(QDialog):
    """라디오 버튼으로 rembg 모델을 고른다. 다이얼로그 종료 후 selected_model 로 조회."""

    def __init__(self, current_model: str = "u2net", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("자동 누끼 — 모델 선택")
        self.setModal(True)
        self.resize(520, 520)

        root = QVBoxLayout(self)
        intro = QLabel(
            "이미지 종류에 따라 더 잘 맞는 모델이 다릅니다.\n"
            "처음 쓰는 모델은 첫 실행 시 자동으로 다운로드됩니다 (수십 MB)."
        )
        intro.setStyleSheet("color: #c8c8c8; padding: 4px 0;")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # 스크롤 가능한 라디오 목록 (모델이 많아 작은 창에서도 다 보이도록).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(2)

        # 저장된 model id 가 목록에 없으면 기본으로 폴백.
        normalized = current_model if current_model in _VALID_IDS else "u2net"

        self._radios: dict[str, QRadioButton] = {}
        for mid, label, desc in MODELS:
            rb = QRadioButton(label)
            rb.setChecked(mid == normalized)
            self._radios[mid] = rb
            inner_layout.addWidget(rb)
            inner_layout.addWidget(_description_label(desc))

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("실행")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def selected_model(self) -> str:
        for mid, rb in self._radios.items():
            if rb.isChecked():
                return mid
        return "u2net"
