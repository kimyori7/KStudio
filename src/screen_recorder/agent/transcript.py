"""faster-whisper 자막 추출 + 캐시.

설계 결정 (2026-05-13):
- **모델 캐시**: faster-whisper 기본 (`~/.cache/huggingface/hub/`) — 첫 사용 시 자동
  다운로드. 별도 download_whisper_model 도구로 명시적 사전 다운로드 가능.
- **전사 캐시**: 사이드카 옆에 `<basename>_<hash>.transcript.json`. 같은 영상 두 번
  전사 안 함. 사이드카 폴더와 동일 위치 (`SidecarStore.root`).
- **모델 크기**: AgentSettings.whisper_model_size 로 영속화 — tiny/base/small/medium.
  사용자가 환경설정에서 변경.
- **동기 전사**: 1시간 영상 base 모델 기준 ~1~2분. worker(asyncio) 스레드 차단 OK
  — UI 는 별도 thread 라 응답. 백그라운드 잡 패턴은 후속.

스키마 v1:
```
{
  "version": 1,
  "source_hash": "...",
  "model_size": "base",
  "language": "ko",
  "duration_ms": 60000,
  "segments": [
    {"start_ms": 0, "end_ms": 3500, "text": "안녕하세요 ..."},
    ...
  ]
}
```
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..effects.sidecar_store import _safe_filename, compute_video_hash

_log = logging.getLogger(__name__)


def _register_nvidia_pip_dll_dirs() -> list[str]:
    """`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` 로 깔린 DLL 을 Windows 가
    찾을 수 있게 검색 경로에 추가.

    pip 패키지의 DLL 은 site-packages/nvidia/<lib>/bin/ 에 깔리는데, Windows 의
    LoadLibrary 는 site-packages 를 자동 검색하지 않음. PyTorch 는 import 시
    자동으로 등록하지만 ctranslate2 는 안 함. KStudio 부팅 시 한 번 등록해
    `pip install` 만으로 GPU 가속이 동작하도록.

    *어떻게 nvidia 폴더를 찾는가:*
    1차 — `import nvidia` 후 `Path(nvidia.__file__).parent` (가장 견고: 실제 import
    가능한 위치를 OS sys.path 가 알려줌).
    2차 폴백 — `sysconfig.get_paths()['purelib']/nvidia` (1차 실패 시 — namespace
    pkg `__init__.py` 부재 등의 케이스 대비).

    Returns: 등록된 디렉토리 경로 list (테스트/디버그 용).
    """
    if sys.platform != "win32":
        _log.debug("Transcriber: non-Windows — DLL 등록 skip")
        return []

    nvidia_root: Optional[Path] = None
    # 1차: import nvidia
    try:
        import nvidia  # type: ignore[import-not-found]
        f = getattr(nvidia, "__file__", None)
        if f:
            nvidia_root = Path(f).parent
        else:
            # namespace pkg — __path__ 첫 항목 사용.
            paths = getattr(nvidia, "__path__", None)
            if paths:
                nvidia_root = Path(list(paths)[0])
    except ImportError as e:
        _log.info("Transcriber: nvidia 패키지 import 실패 (%s) — GPU 가속 미설치", e)
    except Exception:
        _log.exception("Transcriber: nvidia 패키지 위치 감지 실패")

    # 2차 폴백: sysconfig
    if nvidia_root is None or not nvidia_root.exists():
        try:
            import sysconfig
            purelib = sysconfig.get_paths().get("purelib")
            if purelib:
                cand = Path(purelib) / "nvidia"
                if cand.exists():
                    nvidia_root = cand
        except Exception:
            _log.exception("Transcriber: sysconfig 폴백 실패")

    if nvidia_root is None or not nvidia_root.exists():
        _log.info("Transcriber: nvidia 폴더 못 찾음 — GPU 가속 미설치 가정")
        return []

    _log.info("Transcriber: nvidia 패키지 루트 = %s", nvidia_root)

    registered: list[str] = []
    for sub in nvidia_root.iterdir():
        if not sub.is_dir():
            continue
        bin_dir = sub / "bin"
        if bin_dir.exists():
            try:
                os.add_dll_directory(str(bin_dir))
                registered.append(str(bin_dir))
            except (OSError, AttributeError) as e:
                _log.warning("Transcriber: add_dll_directory(%s) 실패: %s", bin_dir, e)
    _log.info(
        "Transcriber: NVIDIA pip 패키지 DLL 경로 등록 — %d 개: %s",
        len(registered), registered,
    )
    return registered


# 모듈 import 시 한 번만 — faster_whisper / ctranslate2 가 DLL 로딩 시도 전.
_NVIDIA_DLL_DIRS = _register_nvidia_pip_dll_dirs()


# pip 패키지 이름 — 1-클릭 설치 다이얼로그 + 상태 판정에서 공통 사용.
NVIDIA_PIP_PACKAGES = ("nvidia-cublas-cu12", "nvidia-cudnn-cu12")


def nvidia_pip_packages_installed() -> bool:
    """nvidia-cublas-cu12 / nvidia-cudnn-cu12 가 site-packages 에 깔려 있는지.

    설치 후 KStudio 재시작 안 한 상태에서도 True 반환 — 디스크 검사. ctypes 로
    `cublas64_12.dll` 로딩 가능한지는 `_cuda_runtime_available()` 가 별도 판정.
    """
    if sys.platform != "win32":
        return False
    try:
        import sysconfig
        purelib = sysconfig.get_paths().get("purelib")
    except Exception:
        return False
    if not purelib:
        return False
    nvidia = Path(purelib) / "nvidia"
    if not nvidia.exists():
        return False
    # 두 패키지 모두의 bin/ 디렉토리 존재 + 안에 DLL 한 개 이상.
    cublas_bin = nvidia / "cublas" / "bin"
    cudnn_bin = nvidia / "cudnn" / "bin"
    return (cublas_bin.exists() and any(cublas_bin.glob("*.dll"))
            and cudnn_bin.exists() and any(cudnn_bin.glob("*.dll")))


def gpu_acceleration_status() -> str:
    """현재 GPU 가속 상태 — UI 메뉴 라벨 + 설치 다이얼로그 분기 용.

    반환값:
    - 'active': cuBLAS DLL 로딩 OK → 자막 export 가 GPU 사용 가능.
    - 'installed_pending_restart': nvidia pip 패키지는 깔려 있지만 DLL 검색은 아직
       못 잡음 (모듈 import 후 add_dll_directory 가 효과 없는 경우 — 재시작 필요).
    - 'not_installed': nvidia pip 패키지도 NVIDIA Toolkit 도 없음.
    - 'no_gpu': NVIDIA GPU 자체가 없음 (ctranslate2.get_cuda_device_count() == 0).
    """
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return "no_gpu"
    except Exception:
        return "no_gpu"
    if _cuda_runtime_available():
        return "active"
    if nvidia_pip_packages_installed():
        return "installed_pending_restart"
    return "not_installed"


TRANSCRIPT_EXT = ".transcript.json"
TRANSCRIPT_SCHEMA_VERSION = 1
VALID_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")

# 사용자에게 안내용 — 대략 모델 크기. 정확한 값은 첫 다운로드 후 HF 캐시에 따라 변동.
WHISPER_SIZE_MB = {
    "tiny": 39,
    "base": 74,
    "small": 244,
    "medium": 769,
    "large-v3": 1550,
}


@dataclass
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start_ms": self.start_ms, "end_ms": self.end_ms, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> "TranscriptSegment":
        return cls(
            start_ms=int(d.get("start_ms", 0)),
            end_ms=int(d.get("end_ms", 0)),
            text=str(d.get("text", "")),
        )


@dataclass
class Transcript:
    """전사 결과 — 디스크 영속화 대상."""
    source_hash: str
    model_size: str
    language: str
    duration_ms: int
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TRANSCRIPT_SCHEMA_VERSION,
            "source_hash": self.source_hash,
            "model_size": self.model_size,
            "language": self.language,
            "duration_ms": self.duration_ms,
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            source_hash=str(d.get("source_hash", "")),
            model_size=str(d.get("model_size", "base")),
            language=str(d.get("language", "ko")),
            duration_ms=int(d.get("duration_ms", 0)),
            segments=[TranscriptSegment.from_dict(s) for s in d.get("segments", [])],
        )

    def segments_in_range(self, start_ms: int, end_ms: int) -> list[TranscriptSegment]:
        return [s for s in self.segments if not (s.end_ms < start_ms or s.start_ms > end_ms)]


def transcript_path_for(
    sidecar_dir: Path, video_path: Path, source_hash: str
) -> Path:
    """전사 캐시 경로 — `<basename>_<hash>.transcript.json` (사이드카와 같은 폴더)."""
    basename = _safe_filename(Path(video_path).stem)
    return Path(sidecar_dir) / f"{basename}_{source_hash}{TRANSCRIPT_EXT}"


def load_transcript(path: Path) -> Optional[Transcript]:
    """캐시 파일 로드. 없거나 손상 시 None."""
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("version", 0)) != TRANSCRIPT_SCHEMA_VERSION:
            _log.warning("transcript version mismatch: %s", path)
            return None
        return Transcript.from_dict(data)
    except Exception:
        _log.exception("load_transcript failed: %s", path)
        return None


def save_transcript(path: Path, t: Transcript) -> None:
    """atomic write — tmp 후 rename. 중간 종료에도 기존 파일 보존."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(t.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# CUDA 추론 실패 메시지에서 찾을 키워드 — 발견 시 CPU 폴백.
_CUDA_ERROR_KEYWORDS = ("cublas", "cudnn", "cuda", "gpu", "cu_")


def _cuda_runtime_available() -> bool:
    """faster-whisper / ctranslate2 가 필요로 하는 cuBLAS DLL 로딩 가능 여부.

    Windows: cublas64_12.dll (CUDA 12) 또는 cublas64_11.dll (CUDA 11).
    Linux: libcublas.so.12 / .11. cuDNN 까지는 사전 검사 어려움 (DLL 이름 다양) —
    cuBLAS 만 확인해도 흔한 케이스(런타임 미설치) 거의 차단.
    """
    import ctypes
    import sys
    candidates = (("cublas64_12.dll", "cublas64_11.dll")
                  if sys.platform == "win32"
                  else ("libcublas.so.12", "libcublas.so.11", "libcublas.so"))
    for name in candidates:
        try:
            ctypes.CDLL(name)
            return True
        except OSError:
            continue
        except Exception:
            return False
    return False


def _is_cuda_runtime_error(exc: BaseException) -> bool:
    """예외 메시지에 CUDA/cuBLAS/cuDNN 키워드 포함 여부."""
    msg = str(exc).lower()
    return any(k in msg for k in _CUDA_ERROR_KEYWORDS)


class TranscribeCancelled(Exception):
    """전사 중간에 사용자가 취소했음을 알리는 시그널 예외.

    Transcriber.transcribe(is_cancelled=...) 콜백이 True 반환 시 segment 루프가
    즉시 raise. autoedit 의 TranscriptAnalyzer 는 이를 잡아 AnalyzerCancelled 로
    재발생시켜 worker 가 깔끔히 종료.
    """


class Transcriber:
    """faster-whisper 래퍼 — 모델 lazy load + 캐시.

    여러 transcribe 호출이 모델을 재사용 (singleton). 모델 크기 변경 시 새로 로드.
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._model_size: Optional[str] = None
        # 2026-05-20: CUDA 자동 감지. large-v3 등 큰 모델에서 CPU 만 쓰면 매우 느림.
        self._device, self._compute_type = self._detect_best_device()

    @staticmethod
    def _detect_best_device() -> tuple[str, str]:
        """가용 가속기 자동 감지.

        - CUDA GPU **+ cuBLAS DLL 로딩 가능** → ('cuda', 'float16').
        - 아니면 ('cpu', 'int8') — 양자화로 CPU 에서 그나마 빠름.

        ctranslate2 의 lazy load 특성상 cuBLAS/cuDNN 누락은 모델 생성/추론 시점에야
        드러남. 사전 ctypes 시도로 미리 판정해 사용자 첫 시도가 실패하는 것을 막음.
        """
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() <= 0:
                return "cpu", "int8"
        except Exception as e:
            _log.debug("Transcriber: CUDA 감지 실패, CPU 사용 (%s)", e)
            return "cpu", "int8"
        if not _cuda_runtime_available():
            _log.info("Transcriber: CUDA 디바이스 있지만 cuBLAS 런타임 없음 — CPU 사용")
            return "cpu", "int8"
        _log.info("Transcriber: CUDA + cuBLAS 감지 — GPU(float16) 사용")
        return "cuda", "float16"

    def _ensure_model(self, model_size: str) -> Any:
        if model_size not in VALID_MODEL_SIZES:
            raise ValueError(f"invalid whisper model size: {model_size}. "
                              f"valid: {', '.join(VALID_MODEL_SIZES)}")
        if self._model is None or self._model_size != model_size:
            from faster_whisper import WhisperModel
            _log.info("Transcriber: loading whisper model %r on %s/%s "
                      "(first call may download)",
                      model_size, self._device, self._compute_type)
            try:
                self._model = WhisperModel(
                    model_size, device=self._device, compute_type=self._compute_type,
                )
            except Exception as e:
                # CUDA 런타임 (cuBLAS/cuDNN) 누락 등 — CPU 폴백.
                if self._device != "cpu":
                    _log.warning("Transcriber: %s/%s 로딩 실패 (%s) — CPU 폴백",
                                 self._device, self._compute_type, e)
                    self._device, self._compute_type = "cpu", "int8"
                    self._model = WhisperModel(
                        model_size, device="cpu", compute_type="int8",
                    )
                else:
                    raise
            self._model_size = model_size
        return self._model

    def transcribe(
        self,
        video_path: str,
        model_size: str = "base",
        language: Optional[str] = "ko",
        on_segment: Optional[Any] = None,
        is_cancelled: Optional[Any] = None,
    ) -> Transcript:
        """전사 실행. 동기 차단 — 1시간 영상 base 기준 ~1~2분.

        language=None 이면 자동 감지. default 'ko' 는 사용자 영상이 한국어 위주일
        가능성이 높아 정확도를 위해 명시.

        on_segment(seg, duration_s) — segment 받을 때마다 호출 (스트리밍 progress + 자막
        UI 업데이트용). seg 는 TranscriptSegment, duration_s 는 전체 영상 길이(초).
        예외 던지면 무시 (전사 중단 방지). None 이면 기존 동작 (collect 후 반환).

        is_cancelled() — bool 반환 콜백. 매 segment 마다 체크 → True 면
        TranscribeCancelled raise → 즉시 중단 (faster-whisper iterator 도 함께 종료).
        None 이면 무시 (취소 불가능). 자동편집 worker thread 가 사용자 취소 버튼
        클릭 전파용.

        CUDA 추론 실패 (cuBLAS/cuDNN 누락 등) 시 자동으로 CPU 폴백 후 재시도.
        """
        try:
            return self._do_transcribe(video_path, model_size, language, on_segment, is_cancelled)
        except TranscribeCancelled:
            # 취소는 CUDA 에러로 오인하지 않도록 별도 처리 — 그대로 propagate.
            raise
        except Exception as e:
            if self._device != "cpu" and _is_cuda_runtime_error(e):
                _log.warning("Transcriber: CUDA 추론 실패 (%s) — CPU 폴백 후 재시도", e)
                # 모델/디바이스 리셋 — 다음 _ensure_model 이 CPU 로 재로드.
                self._model = None
                self._model_size = None
                self._device, self._compute_type = "cpu", "int8"
                return self._do_transcribe(video_path, model_size, language, on_segment, is_cancelled)
            raise

    def _do_transcribe(
        self,
        video_path: str,
        model_size: str,
        language: Optional[str],
        on_segment: Optional[Any],
        is_cancelled: Optional[Any] = None,
    ) -> Transcript:
        """단일 시도 — transcribe 의 폴백 없는 내부 구현."""
        model = self._ensure_model(model_size)
        segments_iter, info = model.transcribe(
            video_path,
            language=language,
            vad_filter=True,          # 침묵 구간 자동 스킵 — 토큰 절약.
            beam_size=5,              # 정확도/속도 trade-off — 5 가 기본 권장.
        )
        duration_s = float(info.duration) if info.duration else 0.0
        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            # 매 segment 시작 직전 취소 체크 — segments_iter 가 lazy generator 이므로
            # 여기서 raise 하면 faster-whisper 도 더 이상 다음 segment 추론 안 함.
            if is_cancelled is not None and is_cancelled():
                raise TranscribeCancelled()
            ts = TranscriptSegment(
                start_ms=int(round(seg.start * 1000)),
                end_ms=int(round(seg.end * 1000)),
                text=seg.text.strip(),
            )
            segments.append(ts)
            if on_segment is not None:
                try:
                    on_segment(ts, duration_s)
                except Exception:
                    _log.exception("transcribe on_segment callback raised")
        duration_ms = int(round(duration_s * 1000))
        detected_lang = info.language or language or "unknown"
        return Transcript(
            source_hash="",       # 호출자가 채움.
            model_size=model_size,
            language=detected_lang,
            duration_ms=duration_ms,
            segments=segments,
        )

    def unload(self) -> None:
        """로드된 Whisper 모델을 메모리에서 해제.

        large-v3 ~3GB / medium ~1.5GB VRAM 또는 RAM 차지. export 끝나면 회수해야
        다른 작업 + 다른 앱이 자원 쓸 수 있음. ctranslate2 는 객체 소멸 시 자동으로
        GPU 메모리 free — `self._model = None` + gc 만으로 충분.

        다음 transcribe 호출 시 _ensure_model 이 재로드 (디스크 캐시는 유지 — 다운로드는
        다시 안 함, 메모리 적재만 다시 ~3-5초).
        """
        if self._model is None:
            return
        _log.info("Transcriber: 모델 메모리 해제 (%r)", self._model_size)
        self._model = None
        self._model_size = None
        import gc
        gc.collect()

    @staticmethod
    def cache_dir_for(model_size: str) -> Optional[Path]:
        """faster-whisper 모델의 HF 캐시 디렉토리 (다운로드 watcher 용).

        실패 시 None — 디스크 크기 polling 비활성. 동작에 영향 없음.
        """
        try:
            from huggingface_hub import constants
            return (Path(constants.HF_HUB_CACHE)
                    / f"models--Systran--faster-whisper-{model_size}")
        except Exception:
            return None


# 프로세스 단일 Transcriber — 모델 한 번만 로드.
_singleton: Optional[Transcriber] = None


def get_transcriber() -> Transcriber:
    global _singleton
    if _singleton is None:
        _singleton = Transcriber()
    return _singleton


def is_model_cached(model_size: str) -> bool:
    """HuggingFace 캐시에 모델이 이미 있는지. 다운로드 필요 사전 판정용.

    경로: `<HF_HUB_CACHE>/models--Systran--faster-whisper-<size>/`. 정확한 매칭 어렵
    지만 fuzzy 검사로 충분 — faster-whisper 가 어차피 가용성 자체 검증.
    """
    try:
        from huggingface_hub import scan_cache_dir
        info = scan_cache_dir()
        target = f"faster-whisper-{model_size}"
        for repo in info.repos:
            if target in repo.repo_id.lower():
                return True
    except Exception:
        pass
    return False
