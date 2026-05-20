"""Transcriber GPU 자동 감지 + CPU 폴백 단위 테스트.

2026-05-20: large-v3 등 큰 모델이 CPU 만 쓰면 매우 느림 → CUDA 자동 사용 +
런타임 누락 시 CPU 폴백.

세 단계 방어:
1. _detect_best_device — ctranslate2 CUDA device + cuBLAS DLL 사전 검사.
2. _ensure_model — WhisperModel 생성 실패 시 CPU 폴백.
3. transcribe — 추론 시점 CUDA 에러 (lazy DLL load) 잡고 CPU 폴백 + 재시도.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from screen_recorder.agent import transcript as tr_mod
from screen_recorder.agent.transcript import (
    Transcriber,
    _cuda_runtime_available,
    _is_cuda_runtime_error,
    _register_nvidia_pip_dll_dirs,
    gpu_acceleration_status,
    nvidia_pip_packages_installed,
)


# ============================================================
# _detect_best_device — 사전 검사 포함
# ============================================================
def test_detect_best_device_cuda_and_cublas_returns_cuda():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 1
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}), \
            patch.object(tr_mod, "_cuda_runtime_available", return_value=True):
        device, compute_type = Transcriber._detect_best_device()
    assert device == "cuda"
    assert compute_type == "float16"


def test_detect_best_device_cuda_but_no_cublas_falls_back_to_cpu():
    """디바이스는 있지만 cuBLAS DLL 없으면 CPU. 사용자 첫 시도 실패 차단."""
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 1
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}), \
            patch.object(tr_mod, "_cuda_runtime_available", return_value=False):
        device, compute_type = Transcriber._detect_best_device()
    assert device == "cpu"
    assert compute_type == "int8"


def test_detect_best_device_no_cuda_device_returns_cpu():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 0
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        # cuBLAS 검사까지 가지 않으므로 mock 불필요.
        device, compute_type = Transcriber._detect_best_device()
    assert device == "cpu"
    assert compute_type == "int8"


def test_detect_best_device_ctranslate2_missing_returns_cpu():
    """ctranslate2 import 실패 — 예외 삼키고 CPU 디폴트."""
    with patch("builtins.__import__", side_effect=ImportError("no ctranslate2")):
        try:
            device, compute_type = Transcriber._detect_best_device()
        except Exception:
            pytest.fail("_detect_best_device 가 예외를 던지면 안 됨")
    assert device == "cpu"
    assert compute_type == "int8"


def test_detect_best_device_get_cuda_device_count_raises_returns_cpu():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.side_effect = RuntimeError("CUDA driver missing")
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        device, compute_type = Transcriber._detect_best_device()
    assert device == "cpu"
    assert compute_type == "int8"


# ============================================================
# _cuda_runtime_available — ctypes 사전 검사
# ============================================================
def test_cuda_runtime_available_succeeds_when_cublas_loads(monkeypatch):
    """ctypes.CDLL 첫 후보에서 성공 → True."""
    import ctypes
    monkeypatch.setattr(ctypes, "CDLL", lambda name: MagicMock())
    assert _cuda_runtime_available() is True


def test_cuda_runtime_available_false_when_all_candidates_fail(monkeypatch):
    """모든 후보 DLL 로딩 실패 → False."""
    import ctypes

    def _raise(name):
        raise OSError(f"{name} not found")

    monkeypatch.setattr(ctypes, "CDLL", _raise)
    assert _cuda_runtime_available() is False


# ============================================================
# _is_cuda_runtime_error
# ============================================================
@pytest.mark.parametrize("msg", [
    "Library cublas64_12.dll is not found or cannot be loaded",
    "Library cudnn_ops_infer64_8.dll is not found",
    "CUDA error 35: driver mismatch",
    "GPU memory exhausted",
    "cu_init failed",
])
def test_is_cuda_runtime_error_recognizes_messages(msg):
    assert _is_cuda_runtime_error(RuntimeError(msg))


@pytest.mark.parametrize("msg", [
    "file not found",
    "Permission denied",
    "ValueError: invalid input",
    "",
])
def test_is_cuda_runtime_error_rejects_unrelated_messages(msg):
    assert not _is_cuda_runtime_error(RuntimeError(msg))


# ============================================================
# __init__ 통합
# ============================================================
def test_init_uses_detect_best_device():
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cuda", "float16")):
        t = Transcriber()
    assert t._device == "cuda"
    assert t._compute_type == "float16"


def test_init_cpu_default_when_no_gpu():
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cpu", "int8")):
        t = Transcriber()
    assert t._device == "cpu"
    assert t._compute_type == "int8"


# ============================================================
# _ensure_model — 모델 로딩 시점 폴백
# ============================================================
def test_ensure_model_falls_back_to_cpu_on_cuda_load_failure():
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cuda", "float16")):
        t = Transcriber()

    cpu_model = MagicMock(name="cpu_model")

    class _FakeWhisperModel:
        call_count = 0

        def __new__(cls, model_size, device, compute_type):
            cls.call_count += 1
            if cls.call_count == 1:
                assert device == "cuda"
                raise RuntimeError("cuBLAS not found")
            assert device == "cpu"
            assert compute_type == "int8"
            return cpu_model

    mock_fw = MagicMock()
    mock_fw.WhisperModel = _FakeWhisperModel
    with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
        result = t._ensure_model("base")

    assert result is cpu_model
    assert t._device == "cpu"
    assert t._compute_type == "int8"
    assert _FakeWhisperModel.call_count == 2


def test_ensure_model_cpu_failure_propagates():
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cpu", "int8")):
        t = Transcriber()

    mock_fw = MagicMock()
    mock_fw.WhisperModel = MagicMock(side_effect=RuntimeError("disk full"))
    with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
        with pytest.raises(RuntimeError, match="disk full"):
            t._ensure_model("base")


def test_ensure_model_cuda_success_no_fallback():
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cuda", "float16")):
        t = Transcriber()

    cuda_model = MagicMock(name="cuda_model")
    fw_ctor = MagicMock(return_value=cuda_model)
    mock_fw = MagicMock()
    mock_fw.WhisperModel = fw_ctor
    with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
        result = t._ensure_model("large-v3")

    assert result is cuda_model
    assert t._device == "cuda"
    assert t._compute_type == "float16"
    assert fw_ctor.call_count == 1
    fw_ctor.assert_called_with("large-v3", device="cuda", compute_type="float16")


def test_ensure_model_invalid_size_raises():
    t = Transcriber()
    with pytest.raises(ValueError, match="invalid whisper model size"):
        t._ensure_model("xxx-huge")


# ============================================================
# transcribe — 추론 시점 폴백 (lazy DLL load 케이스)
# ============================================================
def test_transcribe_cuda_inference_failure_falls_back_to_cpu():
    """ctranslate2 가 lazy load 하는 cuBLAS DLL 누락 — transcribe 호출 시점에야 발현.

    실패 후 self._device 가 cpu 로 리셋되고, CPU 모델로 재시도해서 성공.
    """
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cuda", "float16")):
        t = Transcriber()

    # _ensure_model 을 모킹 — 첫 호출은 cuda 시점, 두 번째는 cpu 시점에 호출됨.
    cuda_model = MagicMock(name="cuda_model")
    cuda_model.transcribe.side_effect = RuntimeError(
        "Library cublas64_12.dll is not found or cannot be loaded"
    )
    cpu_model = MagicMock(name="cpu_model")
    cpu_segments = []
    cpu_info = MagicMock(duration=10.0, language="ko")
    cpu_model.transcribe.return_value = (iter(cpu_segments), cpu_info)

    ensure_calls = []

    def _ensure_model(model_size):
        ensure_calls.append((t._device, t._compute_type))
        return cuda_model if t._device == "cuda" else cpu_model

    with patch.object(t, "_ensure_model", side_effect=_ensure_model):
        result = t.transcribe("video.mp4", model_size="large-v3")

    # 두 번 호출됨: cuda 시도 → cpu 폴백.
    assert ensure_calls == [("cuda", "float16"), ("cpu", "int8")]
    assert t._device == "cpu"
    assert t._compute_type == "int8"
    assert result.duration_ms == 10000


def test_transcribe_cpu_inference_failure_propagates():
    """CPU 디폴트인 상태에서 transcribe 실패 — 폴백 없이 raise."""
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cpu", "int8")):
        t = Transcriber()

    cpu_model = MagicMock()
    cpu_model.transcribe.side_effect = RuntimeError("ffmpeg decode failed")
    with patch.object(t, "_ensure_model", return_value=cpu_model):
        with pytest.raises(RuntimeError, match="ffmpeg decode failed"):
            t.transcribe("video.mp4", model_size="base")


def test_unload_clears_model_and_size():
    """unload — 메모리 점유 모델 해제, 다음 transcribe 가 재로드 가능."""
    t = Transcriber()
    t._model = MagicMock(name="loaded_model")
    t._model_size = "large-v3"
    t.unload()
    assert t._model is None
    assert t._model_size is None


def test_unload_noop_when_model_not_loaded():
    """모델 로드 전 unload 호출 — 안전 (예외 없음)."""
    t = Transcriber()
    assert t._model is None
    t.unload()   # raise 안 해야 함
    assert t._model is None


def test_unload_then_transcribe_reloads_model():
    """unload 후 _ensure_model 호출 시 새 모델 다시 적재."""
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cpu", "int8")):
        t = Transcriber()

    first_model = MagicMock(name="first_model")
    second_model = MagicMock(name="second_model")
    mock_fw = MagicMock()
    mock_fw.WhisperModel = MagicMock(side_effect=[first_model, second_model])
    with patch.dict("sys.modules", {"faster_whisper": mock_fw}):
        assert t._ensure_model("base") is first_model
        t.unload()
        assert t._ensure_model("base") is second_model
    assert mock_fw.WhisperModel.call_count == 2


# ============================================================
# _register_nvidia_pip_dll_dirs — pip install nvidia-cublas-cu12 자동 활성화
# ============================================================
def _make_fake_nvidia_pkg(tmp_path, monkeypatch, subdirs=("cublas", "cudnn")):
    """가짜 nvidia 네임스페이스 패키지 — import nvidia → tmp_path/nvidia 로 가도록."""
    from types import ModuleType
    nvidia_root = tmp_path / "nvidia"
    nvidia_root.mkdir()
    for sub in subdirs:
        (nvidia_root / sub / "bin").mkdir(parents=True)
    # 'no_bin_lib' 등의 bin 없는 서브폴더도 가능.
    fake_mod = ModuleType("nvidia")
    fake_mod.__file__ = str(nvidia_root / "__init__.py")
    monkeypatch.setitem(__import__("sys").modules, "nvidia", fake_mod)
    return nvidia_root


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="add_dll_directory 는 Windows 전용")
def test_register_nvidia_pip_dll_dirs_registers_each_bin(tmp_path, monkeypatch):
    """가짜 nvidia/<lib>/bin/ 만들고 등록되는지 확인 — `import nvidia` 경로 통과."""
    nvidia_root = _make_fake_nvidia_pkg(tmp_path, monkeypatch,
                                          subdirs=("cublas", "cudnn", "no_bin_lib"))
    # no_bin_lib 는 bin 없으니 등록 안 되어야.
    import shutil
    shutil.rmtree(nvidia_root / "no_bin_lib" / "bin")

    calls: list[str] = []
    import os as os_mod
    monkeypatch.setattr(os_mod, "add_dll_directory",
                         lambda p: calls.append(p))

    registered = _register_nvidia_pip_dll_dirs()
    assert len(registered) == 2
    assert any("cublas" in r for r in registered)
    assert any("cudnn" in r for r in registered)
    assert len(calls) == 2
    assert not any("no_bin_lib" in c for c in calls)


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="add_dll_directory 는 Windows 전용")
def test_register_nvidia_pip_dll_dirs_empty_when_no_nvidia_pkg(tmp_path, monkeypatch):
    """nvidia 패키지 미설치 — 빈 리스트, 예외 없음."""
    import sys as sys_mod
    monkeypatch.delitem(sys_mod.modules, "nvidia", raising=False)
    # import nvidia 가 ImportError 던지도록 — sys.path 에 없게 설정.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _faulty_import(name, *args, **kwargs):
        if name == "nvidia":
            raise ImportError("no nvidia")
        return real_import(name, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "__import__", _faulty_import)

    # sysconfig 폴백도 빈 디렉토리 가리키도록.
    fake_site = tmp_path / "site-packages"
    fake_site.mkdir()
    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths",
                         lambda: {"purelib": str(fake_site)})

    registered = _register_nvidia_pip_dll_dirs()
    assert registered == []


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="add_dll_directory 는 Windows 전용")
def test_register_nvidia_pip_dll_dirs_swallows_add_dll_errors(tmp_path, monkeypatch):
    """add_dll_directory 자체가 OSError 던져도 함수는 안전 (다른 dir 시도 계속)."""
    _make_fake_nvidia_pkg(tmp_path, monkeypatch, subdirs=("cublas", "cudnn"))

    import os as os_mod

    def _raise_first(p):
        if "cublas" in p:
            raise OSError("denied")

    monkeypatch.setattr(os_mod, "add_dll_directory", _raise_first)

    registered = _register_nvidia_pip_dll_dirs()
    assert len(registered) == 1
    assert "cudnn" in registered[0]


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="add_dll_directory 는 Windows 전용")
def test_register_nvidia_pip_dll_dirs_falls_back_to_sysconfig(tmp_path, monkeypatch):
    """nvidia import 실패 시 sysconfig purelib 폴더로 폴백."""
    import sys as sys_mod
    monkeypatch.delitem(sys_mod.modules, "nvidia", raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _faulty_import(name, *args, **kwargs):
        if name == "nvidia":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    import builtins
    monkeypatch.setattr(builtins, "__import__", _faulty_import)

    fake_site = tmp_path / "site-packages"
    nvidia = fake_site / "nvidia"
    (nvidia / "cublas" / "bin").mkdir(parents=True)

    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths",
                         lambda: {"purelib": str(fake_site)})

    calls = []
    import os as os_mod
    monkeypatch.setattr(os_mod, "add_dll_directory",
                         lambda p: calls.append(p))

    registered = _register_nvidia_pip_dll_dirs()
    assert len(registered) == 1
    assert "cublas" in registered[0]


# ============================================================
# nvidia_pip_packages_installed — site-packages 검사
# ============================================================
@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="현재 구현은 Windows 한정")
def test_nvidia_pip_packages_installed_true_when_dlls_present(tmp_path, monkeypatch):
    fake_site = tmp_path / "site-packages"
    cublas_bin = fake_site / "nvidia" / "cublas" / "bin"
    cudnn_bin = fake_site / "nvidia" / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    (cublas_bin / "cublas64_12.dll").write_bytes(b"x")
    (cudnn_bin / "cudnn_ops_infer64_8.dll").write_bytes(b"x")

    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths",
                         lambda: {"purelib": str(fake_site)})
    assert nvidia_pip_packages_installed() is True


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="현재 구현은 Windows 한정")
def test_nvidia_pip_packages_installed_false_when_dirs_empty(tmp_path, monkeypatch):
    fake_site = tmp_path / "site-packages"
    cublas_bin = fake_site / "nvidia" / "cublas" / "bin"
    cudnn_bin = fake_site / "nvidia" / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    # DLL 비어 있음 → False.
    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths",
                         lambda: {"purelib": str(fake_site)})
    assert nvidia_pip_packages_installed() is False


@pytest.mark.skipif(__import__("sys").platform != "win32",
                    reason="현재 구현은 Windows 한정")
def test_nvidia_pip_packages_installed_false_when_only_one_present(tmp_path, monkeypatch):
    """cublas 만 있고 cudnn 없으면 False — 둘 다 있어야 GPU 가속 동작."""
    fake_site = tmp_path / "site-packages"
    cublas_bin = fake_site / "nvidia" / "cublas" / "bin"
    cublas_bin.mkdir(parents=True)
    (cublas_bin / "cublas64_12.dll").write_bytes(b"x")

    import sysconfig
    monkeypatch.setattr(sysconfig, "get_paths",
                         lambda: {"purelib": str(fake_site)})
    assert nvidia_pip_packages_installed() is False


# ============================================================
# gpu_acceleration_status — UI 분기용
# ============================================================
def test_gpu_acceleration_status_no_gpu():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 0
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}):
        assert gpu_acceleration_status() == "no_gpu"


def test_gpu_acceleration_status_active():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 1
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}), \
            patch.object(tr_mod, "_cuda_runtime_available", return_value=True):
        assert gpu_acceleration_status() == "active"


def test_gpu_acceleration_status_installed_pending_restart():
    """pip 패키지는 있지만 DLL 로딩은 아직 안 잡힘 — 재시작 필요."""
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 1
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}), \
            patch.object(tr_mod, "_cuda_runtime_available", return_value=False), \
            patch.object(tr_mod, "nvidia_pip_packages_installed", return_value=True):
        assert gpu_acceleration_status() == "installed_pending_restart"


def test_gpu_acceleration_status_not_installed():
    mock_ct2 = MagicMock()
    mock_ct2.get_cuda_device_count.return_value = 1
    with patch.dict("sys.modules", {"ctranslate2": mock_ct2}), \
            patch.object(tr_mod, "_cuda_runtime_available", return_value=False), \
            patch.object(tr_mod, "nvidia_pip_packages_installed", return_value=False):
        assert gpu_acceleration_status() == "not_installed"


def test_transcribe_cuda_unrelated_failure_propagates():
    """CUDA 모드라도 CUDA 키워드 없는 예외는 폴백 안 함 (시간 낭비 방지)."""
    with patch.object(Transcriber, "_detect_best_device",
                       return_value=("cuda", "float16")):
        t = Transcriber()

    cuda_model = MagicMock()
    cuda_model.transcribe.side_effect = FileNotFoundError("video.mp4 missing")
    with patch.object(t, "_ensure_model", return_value=cuda_model):
        with pytest.raises(FileNotFoundError):
            t.transcribe("video.mp4", model_size="base")
    # 폴백 안 함 — device 그대로 cuda.
    assert t._device == "cuda"
