"""WASAPI 루프백 시스템 오디오 캡처."""
from __future__ import annotations
import logging
import time
from pathlib import Path
import threading
from typing import Optional

try:
    import pyaudiowpatch as pyaudio  # type: ignore
except ImportError:
    pyaudio = None  # type: ignore


class AudioCaptureThread(threading.Thread):
    CHUNK = 1024
    # 진단용: 이 chunk 수마다 진행 상황을 로그에 기록 (stream.read 가 멈춰서
    # 한 chunk 만 쓰고 끝나는 회귀를 다음 사고에서 즉시 식별하기 위함).
    _PROGRESS_LOG_EVERY = 500

    def __init__(self, output_path: Path):
        super().__init__(daemon=True, name="AudioCapture")
        self.output_path = Path(output_path)
        self._stop_event = threading.Event()
        self.sample_rate = 0
        self.channels = 0
        self.error: Optional[str] = None
        self.bytes_written = 0
        self.stop_requested_at: Optional[float] = None

    def stop(self) -> None:
        self.stop_requested_at = time.monotonic()
        self._stop_event.set()

    def run(self) -> None:
        log = logging.getLogger(__name__)
        pa = pyaudio.PyAudio()
        try:
            info = pa.get_default_wasapi_loopback()
        except Exception as e:
            self.error = str(e)
            log.error("WASAPI loopback unavailable: %s", e)
            pa.terminate()
            return

        self.sample_rate = int(info["defaultSampleRate"])
        self.channels = int(info["maxInputChannels"])
        device_name = info.get("name", "<unknown>")

        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.CHUNK,
                input_device_index=info["index"],
            )
        except Exception as e:
            self.error = str(e)
            log.error("audio stream open failed: %s", e)
            pa.terminate()
            return

        log.info(
            "audio capture started: device='%s' sr=%d ch=%d chunk=%d",
            device_name, self.sample_rate, self.channels, self.CHUNK,
        )
        chunks = 0
        exit_reason = "stopped"
        try:
            with self.output_path.open("wb") as f:
                while not self._stop_event.is_set():
                    # WASAPI 루프백은 출력 장치로 *실제 소리가 재생될 때만* 데이터를
                    # 준다. 조용한 화면이면 stream.read 가 무한 블록 → stop 이 와도
                    # 못 빠져나와 정지가 수 초씩 지연되고(stop_lag), 인코더와의 레이스도
                    # 악화된다. 그래서 가용 프레임을 먼저 확인하고, 없을 때만 stop_event
                    # 를 짧게 기다리며 루프를 돈다. 정지가 즉시 반응하고, 데이터가 안
                    # 오면 자연히 0바이트로 끝나 '오디오 없음'이 깔끔히 감지된다.
                    #
                    # 중요(회귀 방지): 데이터가 있으면 *있는 만큼* 읽는다(min(avail,CHUNK)).
                    # 'avail >= CHUNK 일 때만 읽기'로 하면, 어떤 장치에서 get_read_available
                    # 이 한 chunk 미만으로 과소보고할 경우 소리가 흐르는데도 영영 못 읽어
                    # *모든* 녹화가 무음이 되는 더 나쁜 회귀가 난다. avail>0 이면 무조건 읽어
                    # 이 실패 모드를 차단한다.
                    try:
                        avail = stream.get_read_available()
                    except Exception:
                        avail = self.CHUNK  # 폴백: 조회 실패 시 그냥 read 시도(기존 동작)
                    if avail <= 0:
                        # 10ms 안에 stop 이 오면 즉시 종료, 아니면 다시 가용량 확인.
                        if self._stop_event.wait(0.01):
                            break
                        continue
                    to_read = min(avail, self.CHUNK)
                    try:
                        data = stream.read(to_read, exception_on_overflow=False)
                    except Exception as e:
                        self.error = str(e)
                        exit_reason = "stream.read error"
                        log.error("audio stream.read failed at chunk %d: %s", chunks, e)
                        break
                    try:
                        f.write(data)
                    except Exception as e:
                        self.error = str(e)
                        exit_reason = "file write error"
                        log.error("audio file write failed at chunk %d: %s", chunks, e)
                        break
                    self.bytes_written += len(data)
                    chunks += 1
                    if chunks % self._PROGRESS_LOG_EVERY == 0:
                        log.debug(
                            "audio capture progress: chunks=%d bytes=%d",
                            chunks, self.bytes_written,
                        )
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()
            stop_lag = (
                time.monotonic() - self.stop_requested_at
                if self.stop_requested_at is not None
                else None
            )
            log.info(
                "audio capture finished: chunks=%d bytes=%d reason=%s "
                "stop_event=%s error=%s stop_lag=%s",
                chunks, self.bytes_written, exit_reason,
                self._stop_event.is_set(), self.error,
                f"{stop_lag:.3f}s" if stop_lag is not None else "n/a",
            )
