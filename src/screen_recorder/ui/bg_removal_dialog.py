"""자동 누끼 — rembg 모델 선택 다이얼로그.

rembg 는 다양한 사전 학습 모델을 지원한다. 각 모델은 학습 데이터셋과 목적이 달라
이미지 종류에 따라 결과 품질이 크게 갈린다 (예: 인물 사진은 u2net_human_seg 가
일반 u2net 보다 정확, UI/그래픽은 isnet-general-use 가 더 선명한 경계).
사용자가 자기 입력에 맞는 모델을 고르도록 라디오 + 설명 라벨로 노출하고,
처음 사용하는 모델은 다운로드가 필요하므로 캐시 존재 여부도 표시.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
    QScrollArea, QVBoxLayout, QWidget,
)


# (model_id, 표시 이름, 한 줄 설명, 대략 다운로드 크기 MB)
# 권장도/일반성 순으로 정렬 — 가장 무난한 것부터.
MODELS: list[tuple[str, str, str, int]] = [
    (
        "u2net",
        "u2net (기본)",
        "일반 용도. 인물·동물·상품 사진에 가장 무난. 가장 많이 검증된 표준 모델.",
        168,
    ),
    (
        "isnet-general-use",
        "isnet-general-use",
        "신형 일반 모델. u2net 보다 경계가 선명한 경우가 많고 그래픽·UI 이미지에도 종종 더 잘 맞음.",
        168,
    ),
    (
        "u2netp",
        "u2netp (경량)",
        "u2net 의 가벼운 버전. 추론이 더 빠르지만 경계 정밀도는 낮음. 빠른 미리보기용.",
        5,
    ),
    (
        "silueta",
        "silueta (경량 일반)",
        "u2net 의 압축판. 작고 빠르며 품질은 비슷한 수준.",
        43,
    ),
    (
        "u2net_human_seg",
        "u2net_human_seg (인물 전용)",
        "사람 전신 분할에 특화. 인물 사진에서 일반 u2net 보다 정확.",
        168,
    ),
    (
        "isnet-anime",
        "isnet-anime (애니/만화 전용)",
        "애니메이션·일러스트 캐릭터 분할 전용. 실사 사진에는 부적합.",
        166,
    ),
    (
        "birefnet-general",
        "birefnet-general (고품질·무거움)",
        "최신 모델 중 품질이 가장 높은 편이지만 추론이 느리고 메모리도 가장 많이 씀.",
        880,
    ),
    (
        "birefnet-general-lite",
        "birefnet-general-lite",
        "birefnet 의 경량판. 품질·속도 균형. birefnet 풀 버전이 너무 느릴 때 대안.",
        178,
    ),
    (
        "birefnet-portrait",
        "birefnet-portrait (인물 고해상도)",
        "인물 사진 전용 고해상도 모델. 머리카락 등 미세한 경계가 중요할 때.",
        880,
    ),
]

_VALID_IDS = {mid for mid, _, _, _ in MODELS}


def rembg_cache_dir() -> Path:
    """rembg 가 다운로드한 .onnx 모델을 두는 폴더. U2NET_HOME 환경변수 우선."""
    return Path(os.environ.get("U2NET_HOME") or os.path.expanduser("~/.u2net"))


def is_model_downloaded(model_id: str) -> bool:
    """rembg 캐시 폴더에 해당 모델 파일이 이미 존재하는지."""
    f = rembg_cache_dir() / f"{model_id}.onnx"
    try:
        return f.exists() and f.stat().st_size > 0
    except OSError:
        return False


def model_size_mb(model_id: str) -> int:
    for mid, _, _, sz in MODELS:
        if mid == model_id:
            return sz
    return 0


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

        # QRadioButton 의 자동 배타성은 부모 위젯 단위라 각 row 의 라디오가 따로 부모를
        # 가지면 동시에 여러 개가 체크된다. QButtonGroup 으로 명시적으로 묶어 모델
        # 하나만 선택되도록 한다.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._radios: dict[str, QRadioButton] = {}
        for mid, label, desc, size_mb in MODELS:
            # 다운로드 상태 — 캐시에 있으면 ✓, 없으면 ⚠ + 크기.
            cached = is_model_downloaded(mid)
            status = (
                "✓ 준비 완료"
                if cached
                else f"⚠ 처음 사용 — 약 {size_mb} MB 다운로드"
            )
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            rb = QRadioButton(label)
            rb.setChecked(mid == normalized)
            self._radios[mid] = rb
            self._group.addButton(rb)
            row_layout.addWidget(rb)
            status_label = QLabel(status)
            status_label.setStyleSheet(
                "color: #5BC07C;" if cached else "color: #E0A030;"
            )
            row_layout.addWidget(status_label)
            row_layout.addStretch(1)
            inner_layout.addWidget(row)
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
