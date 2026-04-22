"""WASAPI 루프백 시스템 오디오 캡처."""
from __future__ import annotations
from pathlib import Path
import threading
from typing import Optional

try:
    import pyaudiowpatch as pyaudio  # type: ignore
except ImportError:
    pyaudio = None  # type: ignore


class AudioCaptureThread(threading.Thread):
    CHUNK = 1024

    def __init__(self, output_path: Path):
        super().__init__(daemon=True, name="AudioCapture")
        self.output_path = Path(output_path)
        self._stop_event = threading.Event()
        self.sample_rate = 0
        self.channels = 0
        self.error: Optional[str] = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        pa = pyaudio.PyAudio()
        try:
            info = pa.get_default_wasapi_loopback()
        except Exception as e:
            self.error = str(e)
            pa.terminate()
            return

        self.sample_rate = int(info["defaultSampleRate"])
        self.channels = int(info["maxInputChannels"])

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
            pa.terminate()
            return

        try:
            with self.output_path.open("wb") as f:
                while not self._stop_event.is_set():
                    try:
                        data = stream.read(self.CHUNK, exception_on_overflow=False)
                    except Exception as e:
                        self.error = str(e)
                        break
                    f.write(data)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()
