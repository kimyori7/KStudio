"""Real-ESRGAN AI 업스케일 — onnxruntime 추론.

큰 배율(>2x) 업스케일 시 LANCZOS 만으로는 흐릿함. Real-ESRGAN 같은 학습 기반
초해상화 모델은 고주파 디테일을 복원해 결과가 훨씬 선명. 본 모듈은:

1. 모델 레지스트리(`MODELS`) — 각 모델 메타데이터 + HuggingFace ONNX URL
2. 캐시 폴더(`~/.kstudio/realesrgan/`) — 첫 사용 시 자동 다운로드
3. `upscale_qimage(...)` — onnxruntime 으로 타일 단위 추론 + 결과 합성

큰 입력 이미지는 한 번에 추론하면 메모리·시간 폭증. 256×256 타일 단위로 쪼개
양쪽 16px 패딩으로 추론 후 패딩 제거한 코어 영역만 잘라 합성 — 타일 경계가
보이지 않도록 한다(논리적 비-오버랩).

Real-ESRGAN 은 정수배(2x/4x) 모델만 학습돼 있다. 호출자(다이얼로그)는 사용자가
입력한 자유 픽셀을 받아 본 함수로 4배 업스케일 → LANCZOS 로 정확한 목표 크기에
맞춤 (다이얼로그 측 책임 — 본 모듈은 4x 결과만 반환).
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage


# (id, 표시 이름, 설명, 다운로드 URL, 파일명, 대략 MB, 배율)
# 처음에는 표준 4x 한 종류만. 추후 anime/lite 등 추가 가능.
MODELS: list[dict] = [
    {
        "id": "real_esrgan_x4",
        "label": "Real-ESRGAN x4 (표준)",
        "description": "범용 4배 업스케일. 실사 사진·일러스트 모두 양호.",
        "url": "https://huggingface.co/wide-video/real-esrgan-v1.0.0/resolve/main/real_esrgan_x4.onnx",
        "filename": "real_esrgan_x4.onnx",
        "size_mb": 67,
        "scale": 4,
    },
]

DEFAULT_MODEL_ID = "real_esrgan_x4"
_VALID_IDS = {m["id"] for m in MODELS}


def cache_dir() -> Path:
    """ONNX 모델 캐시 폴더. KSTUDIO_REALESRGAN_HOME 환경변수가 우선."""
    return Path(
        os.environ.get("KSTUDIO_REALESRGAN_HOME")
        or os.path.expanduser("~/.kstudio/realesrgan")
    )


def model_info(model_id: str) -> dict:
    for m in MODELS:
        if m["id"] == model_id:
            return m
    raise ValueError(f"알 수 없는 모델: {model_id}")


def model_path(model_id: str) -> Path:
    return cache_dir() / model_info(model_id)["filename"]


def is_model_downloaded(model_id: str) -> bool:
    """캐시 폴더에 모델 파일이 이미 존재하고 비어있지 않은지."""
    p = model_path(model_id)
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def download_model(
    model_id: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """모델을 캐시 폴더에 다운로드. 이미 있으면 즉시 반환.

    `.part` 임시 파일에 받은 뒤 atomic rename — 도중에 끊겨도 캐시가 깨지지 않음.
    progress_cb(downloaded_bytes, total_bytes) 로 진행률 보고. total 이 0 이면
    Content-Length 가 안 옴 (예외적, 로딩만 빠르게 마쳐야).
    """
    import requests

    info = model_info(model_id)
    dst = cache_dir() / info["filename"]
    if dst.exists() and dst.stat().st_size > 0:
        return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    with requests.get(info["url"], stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    progress_cb(downloaded, total)

    tmp.replace(dst)
    return dst


def _qimage_to_chw_float(image: QImage) -> "tuple[any, int, int]":
    """QImage → numpy float32 [H, W, 3] in [0,1]. 알파 무시.

    bytesPerLine 이 4 정렬이라 stride 처리 필요 — width*3 와 다를 수 있음.
    """
    import numpy as np

    src = image.convertToFormat(QImage.Format_RGB888)
    h, w = src.height(), src.width()
    bpl = src.bytesPerLine()
    raw = bytes(src.constBits())
    arr = np.frombuffer(raw, dtype=np.uint8)
    if bpl == w * 3:
        np_img = arr.reshape(h, w, 3).copy()
    else:
        rows = arr.reshape(h, bpl)
        np_img = rows[:, : w * 3].reshape(h, w, 3).copy()
    return np_img.astype(np.float32) / 255.0, w, h


def _hwc_float_to_qimage(arr) -> QImage:
    """numpy [H, W, 3] uint8 → QImage(RGB888) 사본."""
    h, w = arr.shape[:2]
    bpl = w * 3
    return QImage(arr.tobytes(), w, h, bpl, QImage.Format_RGB888).copy()


def upscale_qimage(
    image: QImage,
    model_id: str = DEFAULT_MODEL_ID,
    *,
    tile_size: int = 256,
    tile_pad: int = 16,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    session_factory: Optional[Callable[[Path], "any"]] = None,
) -> QImage:
    """4배 업스케일된 새 QImage 반환. 모델은 미리 다운로드돼 있어야 한다.

    타일 단위 추론 — 큰 입력에서 메모리·시간 폭증을 막는다. 각 타일은 양쪽
    `tile_pad` 픽셀씩 패딩해 추론하고, 출력에서 패딩 부분을 잘라 코어 영역만
    합성 → 타일 경계가 보이지 않음.

    `session_factory` 는 테스트 주입용. 기본값(None)이면 onnxruntime 으로 ONNX
    모델을 로드. 진행률은 `progress_cb(processed_tiles, total_tiles)`.
    """
    import numpy as np

    info = model_info(model_id)
    scale = info["scale"]

    if session_factory is None:
        import onnxruntime as ort
        path = model_path(model_id)
        if not path.exists():
            raise FileNotFoundError(f"모델 파일이 없습니다: {path}")
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    else:
        sess = session_factory(model_path(model_id))

    inp_name = sess.get_inputs()[0].name

    np_img, w, h = _qimage_to_chw_float(image)

    out_h, out_w = h * scale, w * scale
    output = np.zeros((out_h, out_w, 3), dtype=np.float32)

    # 타일 좌표 — 코어(non-padded) 기준. 각 타일은 step 크기.
    step = max(1, tile_size)
    n_y = (h + step - 1) // step
    n_x = (w + step - 1) // step
    total_tiles = n_y * n_x
    done = 0

    for ti in range(n_y):
        for tj in range(n_x):
            y0c = ti * step
            x0c = tj * step
            y1c = min(h, y0c + step)
            x1c = min(w, x0c + step)

            # padded region (입력)
            y0p = max(0, y0c - tile_pad)
            x0p = max(0, x0c - tile_pad)
            y1p = min(h, y1c + tile_pad)
            x1p = min(w, x1c + tile_pad)

            tile = np_img[y0p:y1p, x0p:x1p, :]
            tile_chw = np.ascontiguousarray(tile.transpose(2, 0, 1)[None, ...])

            result = sess.run(None, {inp_name: tile_chw})[0]
            # [1, 3, ph*scale, pw*scale] → [ph*scale, pw*scale, 3]
            result_hwc = np.transpose(result[0], (1, 2, 0))

            # 패딩 영역 제거 — 출력에서 코어만 잘라낸다.
            crop_top = (y0c - y0p) * scale
            crop_left = (x0c - x0p) * scale
            crop_h = (y1c - y0c) * scale
            crop_w = (x1c - x0c) * scale
            core_out = result_hwc[
                crop_top : crop_top + crop_h,
                crop_left : crop_left + crop_w,
                :,
            ]

            o_y = y0c * scale
            o_x = x0c * scale
            output[o_y : o_y + crop_h, o_x : o_x + crop_w, :] = core_out

            done += 1
            if progress_cb is not None:
                progress_cb(done, total_tiles)

    output = np.clip(output * 255.0, 0, 255).astype(np.uint8)
    return _hwc_float_to_qimage(output)


# ===================== 비동기 워커 =====================


class UpscaleEmitter(QObject):
    """업스케일 워커가 메인 스레드로 보내는 시그널 묶음.

    `download_progress` 는 두 의미로 쓰인다 — total>0 이면 다운로드 진행률,
    total==0 이면 "다운로드 단계 종료, 추론 단계 시작" 신호 (UI 가
    indeterminate 로 전환할 수 있게).
    """

    download_progress = Signal(int, int)   # downloaded_bytes, total_bytes
    inference_progress = Signal(int, int)  # done_tiles, total_tiles
    finished = Signal(QImage)              # 업스케일 결과 (모델 정수배)
    failed = Signal(str)                   # 에러 메시지


class _UpscaleRunnable(QRunnable):
    def __init__(
        self,
        image: QImage,
        model_id: str,
        emitter: UpscaleEmitter,
        *,
        tile_size: int,
        tile_pad: int,
        session_factory: Optional[Callable[[Path], "any"]] = None,
        downloader: Optional[Callable] = None,
    ) -> None:
        super().__init__()
        self._image = image
        self._model_id = model_id
        self._emitter = emitter
        self._tile_size = tile_size
        self._tile_pad = tile_pad
        self._session_factory = session_factory
        self._downloader = downloader or download_model

    def run(self) -> None:
        try:
            if not is_model_downloaded(self._model_id):
                self._downloader(
                    self._model_id,
                    progress_cb=lambda d, t: self._emitter.download_progress.emit(d, t),
                )
            # 다운로드 단계 종료 → UI 가 indeterminate 추론 모드로 전환하도록
            # total=0 으로 한 번 emit (이미 캐시여도 동일하게).
            self._emitter.download_progress.emit(0, 0)

            out = upscale_qimage(
                self._image,
                self._model_id,
                tile_size=self._tile_size,
                tile_pad=self._tile_pad,
                progress_cb=lambda d, t: self._emitter.inference_progress.emit(d, t),
                session_factory=self._session_factory,
            )
            self._emitter.finished.emit(out)
        except Exception as e:
            self._emitter.failed.emit(str(e))


def start_upscale_async(
    image: QImage,
    model_id: str = DEFAULT_MODEL_ID,
    *,
    tile_size: int = 256,
    tile_pad: int = 16,
    session_factory: Optional[Callable[[Path], "any"]] = None,
    downloader: Optional[Callable] = None,
) -> UpscaleEmitter:
    """QThreadPool 백그라운드에서 업스케일 시작. 호출자는 반환된 emitter 의
    시그널에 connect 해 진행률·결과·실패를 받는다.

    `session_factory` / `downloader` 는 테스트 주입용 — 실제 모델 다운로드와
    onnxruntime 추론을 우회.
    """
    emitter = UpscaleEmitter()
    runner = _UpscaleRunnable(
        image, model_id, emitter,
        tile_size=tile_size,
        tile_pad=tile_pad,
        session_factory=session_factory,
        downloader=downloader,
    )
    QThreadPool.globalInstance().start(runner)
    return emitter
