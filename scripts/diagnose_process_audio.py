"""Exercise real Windows process loopback for three seconds with two distinct tones."""
from __future__ import annotations

from array import array
from contextlib import contextmanager, ExitStack
from pathlib import Path
import math
import os
import subprocess
import sys
import tempfile
import threading
import wave


@contextmanager
def _playback(mode: str, path: Path):
    # Launch the base executable directly so this test creates a single, direct
    # parent/child relationship even when run from a Windows virtual environment.
    executable = Path(sys.base_prefix) / "python.exe"
    env = os.environ.copy()
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(site_packages), env.get("PYTHONPATH"))))
    with subprocess.Popen(
        [str(executable), __file__, mode, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    ) as player:
        try:
            ready = player.stdout.readline().split() if player.stdout is not None else []
            if len(ready) != 2 or ready[0] != "ready":
                raise RuntimeError(f"{mode} playback process did not start")
            yield int(ready[1])
        finally:
            # EOF lets the tree owner stop and reap its player before exiting.
            if player.stdin is not None:
                player.stdin.close()
            try:
                player.wait(timeout=5)
            except subprocess.TimeoutExpired:
                player.terminate()
                player.wait(timeout=5)


def _write_tone(path: Path, frequency: int) -> None:
    rate = 48000
    samples = array("h", (
        int(6000 * math.sin(math.tau * frequency * frame / rate))
        for frame in range(rate)
    ))
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(samples.tobytes())


def _play_tone(path: Path) -> None:
    import pyaudiowpatch as pa

    stopped = threading.Event()

    def wait_for_eof() -> None:
        sys.stdin.read(1)
        stopped.set()

    threading.Thread(target=wait_for_eof, daemon=True).start()
    with wave.open(str(path), "rb") as wav, pa.PyAudio() as audio:
        wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
        tone = wav.readframes(wav.getnframes())
        offset = 0

        def render(_input, frames, _time, _flags):
            nonlocal offset
            end = offset + frames * wav.getsampwidth()
            packet = tone[offset:end] + tone[:max(0, end - len(tone))]
            offset = end % len(tone)
            return packet, pa.paContinue

        output = audio.open(
            format=pa.paInt16, channels=wav.getnchannels(), rate=wav.getframerate(), output=True,
            output_device_index=wasapi["defaultOutputDevice"], stream_callback=render,
            frames_per_buffer=480,
        )
        try:
            print(f"ready {os.getpid()}", flush=True)
            stopped.wait()
        finally:
            output.close()


def _verify_capture(capture, expected: int, unrelated: int) -> None:
    import numpy as np

    if capture.error is not None or capture.is_alive():
        raise RuntimeError(f"capture pid={capture.pid} failed: {capture.error or 'did not stop'}")
    raw = capture.output_path.read_bytes()
    if not raw or len(raw) != capture.bytes_written:
        raise RuntimeError(f"capture pid={capture.pid} wrote an invalid byte count")
    samples = np.frombuffer(raw, dtype="<i2").reshape(-1, capture.channels)
    if len(samples) < capture.sample_rate * 2:
        raise RuntimeError(f"capture pid={capture.pid} yielded less than two seconds of PCM")
    # Use a full second in the middle, avoiding playback startup and shutdown.
    start = (len(samples) - capture.sample_rate) // 2
    window = np.hanning(capture.sample_rate)[:, None]
    spectrum = np.abs(np.fft.rfft(samples[start:start + capture.sample_rate] * window, axis=0))
    tone = float(spectrum[expected].max())
    leakage = float(spectrum[unrelated].max())
    peak = int(np.max(np.abs(samples.astype(np.int32))))
    print(f"pid={capture.pid} bytes={len(raw)} peak={peak} "
          f"tone_{expected}Hz={tone:.0f} other_{unrelated}Hz={leakage:.0f} "
          f"dominant={np.argmax(spectrum.max(axis=1))}Hz", flush=True)
    if peak == 0 or tone < 1000 or leakage > tone * 0.01:
        raise RuntimeError("expected tone is silent or the unrelated tone leaked into capture")


def _diagnose() -> None:
    from screen_recorder.capture.process_audio import ProcessAudioCaptureThread

    temp_root = Path(__file__).resolve().parents[1] / "tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="process-audio-", dir=temp_root) as temp, ExitStack() as playback:
        work = Path(temp)
        tree_tone = work / "tree.wav"
        other_tone = work / "other.wav"
        _write_tone(tree_tone, 440)
        _write_tone(other_tone, 997)
        tree_pid = playback.enter_context(_playback("--tree", tree_tone))
        other_pid = playback.enter_context(_playback("--play", other_tone))
        tree = ProcessAudioCaptureThread(work / "tree.raw", tree_pid)
        other = ProcessAudioCaptureThread(work / "other.raw", other_pid)
        started = []
        try:
            for capture in (tree, other):
                capture.start()
                started.append(capture)
            for capture in started:
                if not capture.ready.wait(3) or capture.error:
                    raise RuntimeError(f"pid={capture.pid} startup failed: {capture.error or 'timeout'}")
            threading.Event().wait(3)
        finally:
            for capture in started:
                capture.stop()
            for capture in started:
                capture.join(timeout=3)
        _verify_capture(other, expected=997, unrelated=440)
        _verify_capture(tree, expected=440, unrelated=997)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _diagnose()
    elif len(sys.argv) == 3 and sys.argv[1] == "--tree":
        with _playback("--play", Path(sys.argv[2])):
            print(f"ready {os.getpid()}", flush=True)
            sys.stdin.read(1)
    elif len(sys.argv) == 3 and sys.argv[1] == "--play":
        _play_tone(Path(sys.argv[2]))
    else:
        raise SystemExit("Usage: diagnose_process_audio.py")
