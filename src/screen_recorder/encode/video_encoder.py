"""프레임 큐 -> ffmpeg pipe 영상 인코딩 + 오디오 mux."""
from __future__ import annotations
import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from ..core.settings import VideoSettings, SoundSettings
from ..core.ffmpeg_args import video_pipe_args, audio_encode_args, mux_args


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class VideoEncoder(threading.Thread):
    """프레임 큐(numpy ndarray 또는 bytes)에서 None을 받으면 종료."""

    # 캡처 스레드가 raw 를 다 쓰고 닫을(flush) 때까지 기다리는 상한. 정상이면
    # stop 직후 ~수십 ms 안에 끝나지만, 루프백이 idle 이라 stream.read 에 묶여
    # 늦게 빠져나오는 경우에 대비해 넉넉히 잡는다(상위 finalizer 가 60s join).
    AUDIO_JOIN_TIMEOUT = 10.0
    # 이보다 적게 캡처됐으면 '사실상 오디오 없음'으로 보고 mux 를 건너뛴다.
    # (조용한 화면 / 출력 장치 무음 → WASAPI 루프백이 데이터를 주지 않음.)
    MIN_AUDIO_SECONDS = 0.5

    def __init__(
        self,
        video_settings: VideoSettings,
        sound_settings: SoundSettings,
        width: int,
        height: int,
        ffmpeg_path: Path,
        output_path: Path,
        frame_queue: queue.Queue,
        audio_raw_path: Optional[Path] = None,
        audio_sample_rate: int = 0,
        audio_channels: int = 0,
        audio_thread: Optional[threading.Thread] = None,
    ):
        super().__init__(daemon=True, name="VideoEncoder")
        self.video_settings = video_settings
        self.sound_settings = sound_settings
        self.width = width
        self.height = height
        self.ffmpeg_path = ffmpeg_path
        self.output_path = Path(output_path)
        self.frame_queue = frame_queue
        self.audio_raw_path = audio_raw_path
        self.audio_sample_rate = audio_sample_rate
        self.audio_channels = audio_channels
        self.audio_thread = audio_thread
        self.error: Optional[str] = None

    def run(self) -> None:
        log = logging.getLogger(__name__)
        has_audio = (
            self.sound_settings.system_audio_enabled
            and self.audio_raw_path is not None
            and self.audio_sample_rate > 0
        )
        if has_audio:
            video_only = self.output_path.with_suffix(".video.tmp" + self.output_path.suffix)
        else:
            video_only = self.output_path

        argv = video_pipe_args(self.video_settings, self.width, self.height, str(video_only))
        argv[0] = str(self.ffmpeg_path)

        # ffmpeg stderr 를 임시 파일로 보내 디버깅용 로그 보존 (DEVNULL 이면 사용자가
        # 'mp4 가 0초로 떨어진' 원인을 추적할 길이 없음). 정상 종료 시엔 자동 삭제.
        stderr_log_path = self.output_path.with_suffix(".ffmpeg.log")
        try:
            stderr_log = open(stderr_log_path, "wb")
        except OSError:
            stderr_log = subprocess.DEVNULL  # 폴백 — 로그 못 열어도 인코딩은 계속
            stderr_log_path = None

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_log,
                creationflags=_NO_WINDOW,
            )
        except Exception as e:
            self.error = f"ffmpeg start failed: {e}"
            log.error(self.error)
            if isinstance(stderr_log, int) is False:
                try:
                    stderr_log.close()
                except Exception:
                    pass
            return

        log.info("ffmpeg video pipe started: %s (size %dx%d)",
                 video_only.name, self.width, self.height)
        frame_count = 0
        try:
            while True:
                item = self.frame_queue.get()
                if item is None:
                    break
                if proc.poll() is not None:
                    self.error = (
                        f"ffmpeg exited unexpectedly (code={proc.returncode}); "
                        f"see {stderr_log_path}"
                    )
                    log.error(self.error)
                    break
                data = item if isinstance(item, (bytes, bytearray)) else item.tobytes()
                try:
                    proc.stdin.write(data)
                    frame_count += 1
                except (BrokenPipeError, OSError) as e:
                    self.error = f"pipe write failed after {frame_count} frames: {e}"
                    log.error(self.error)
                    break
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.wait(timeout=5)
            if hasattr(stderr_log, "close"):
                try:
                    stderr_log.close()
                except Exception:
                    pass
        log.info("ffmpeg video pipe finished: %d frames written, exit=%s",
                 frame_count, proc.returncode)
        # 정상 종료 + 충분한 프레임이면 stderr 로그 정리. 비정상이면 보존.
        if (stderr_log_path is not None
                and proc.returncode == 0
                and frame_count > 0
                and self.error is None):
            try:
                Path(stderr_log_path).unlink(missing_ok=True)
            except OSError:
                pass

        if not has_audio:
            return

        # ----- 오디오 인코딩 + mux. 실패해도 비디오는 살린다. -----
        # ffmpeg stderr 는 파일로 보내서 실패 시 사용자/우리가 사고 후에라도 원인을
        # 추적할 수 있게 한다. 정상 종료(audio_ok / mux_ok) 시에는 자동 삭제.
        audio_encoded = self.output_path.with_suffix(".audio.tmp." + self.sound_settings.codec)
        audio_log_path = self.output_path.with_suffix(".audio.ffmpeg.log")
        mux_log_path = self.output_path.with_suffix(".mux.ffmpeg.log")

        # 캡처 스레드가 raw 를 다 쓰고 닫을(=flush) 때까지 기다린다. 캡처는 stop 후에도
        # 잠깐 더 돌 수 있고(특히 idle 루프백이 stream.read 에 묶이면), 파일은 버퍼드
        # 쓰기라 닫히기 전엔 디스크에 0바이트로 보인다. 기다리지 않으면 인코더가 그
        # 0바이트를 읽어 '오디오 0바이트'로 오인한다(실제 사고: 2026-05-29).
        if self.audio_thread is not None:
            try:
                self.audio_thread.join(timeout=self.AUDIO_JOIN_TIMEOUT)
            except RuntimeError:
                pass

        # 진단용: raw 파일 크기 — '한 chunk 만 쓰고 끝남' 같은 캡처-측 회귀를 노출.
        try:
            raw_size = Path(self.audio_raw_path).stat().st_size
        except OSError:
            raw_size = -1
        bytes_per_sec = self.audio_sample_rate * self.audio_channels * 2  # s16le
        audio_dur = (raw_size / bytes_per_sec) if (bytes_per_sec > 0 and raw_size > 0) else 0.0
        video_dur = (frame_count / self.video_settings.fps) if self.video_settings.fps > 0 else 0.0
        log.info("audio raw ready for mux: path=%s size=%d audio_dur=%.3fs video_dur=%.3fs",
                 self.audio_raw_path, raw_size, audio_dur, video_dur)

        # 오디오 부재 가드: 캡처된 소리가 사실상 없으면(조용한 화면/출력 장치 무음)
        # mux 자체를 건너뛴다. 이렇게 해야 (1) -shortest 가 빠졌어도 무음 트랙을
        # 굳이 붙이지 않고, (2) 사용자에게 'mux 실패'가 아니라 '오디오 없음'을
        # 솔직히 알릴 수 있다. encode 를 안 하므로 audio_log 도 만들지 않는다.
        audio_absent = raw_size <= 0 or audio_dur < self.MIN_AUDIO_SECONDS

        audio_ok = False
        if not audio_absent:
            a_argv = audio_encode_args(
                self.sound_settings,
                str(self.audio_raw_path),
                self.audio_sample_rate,
                self.audio_channels,
                str(audio_encoded),
            )
            a_argv[0] = str(self.ffmpeg_path)
            try:
                with open(audio_log_path, "wb") as a_log:
                    proc_a = subprocess.Popen(
                        a_argv,
                        stdout=subprocess.DEVNULL,
                        stderr=a_log,
                        creationflags=_NO_WINDOW,
                    )
                    proc_a.wait(timeout=30)
                audio_ok = (proc_a.returncode == 0
                            and audio_encoded.exists()
                            and audio_encoded.stat().st_size > 0)
                if not audio_ok:
                    log.warning(
                        "audio encode failed: code=%s exists=%s size=%s log=%s",
                        proc_a.returncode,
                        audio_encoded.exists(),
                        audio_encoded.stat().st_size if audio_encoded.exists() else "n/a",
                        audio_log_path,
                    )
            except Exception as e:
                log.warning("audio encode crashed: %s (log=%s)", e, audio_log_path)

        mux_ok = False
        if audio_ok:
            m_argv = mux_args(str(video_only), str(audio_encoded), str(self.output_path))
            m_argv[0] = str(self.ffmpeg_path)
            try:
                with open(mux_log_path, "wb") as m_log:
                    proc_m = subprocess.Popen(
                        m_argv,
                        stdout=subprocess.DEVNULL,
                        stderr=m_log,
                        creationflags=_NO_WINDOW,
                    )
                    proc_m.wait(timeout=30)
                mux_ok = (proc_m.returncode == 0
                          and self.output_path.exists()
                          and self.output_path.stat().st_size > 0)
                if not mux_ok:
                    log.warning(
                        "mux failed: code=%s exists=%s size=%s log=%s",
                        proc_m.returncode,
                        self.output_path.exists(),
                        self.output_path.stat().st_size if self.output_path.exists() else "n/a",
                        mux_log_path,
                    )
            except Exception as e:
                log.warning("mux crashed: %s (log=%s)", e, mux_log_path)

        if mux_ok:
            # mux 성공 → 임시 파일들 + ffmpeg 로그 정리
            for p in (video_only, audio_encoded, self.audio_raw_path,
                      audio_log_path, mux_log_path):
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
        else:
            # mux 미완료 → 비디오는 살리고(오디오는 포기) 임시 파일 정리.
            # 두 경우를 구분: (a) audio_absent = 캡처된 소리가 사실상 없음(정상적
            # 결과, 진단 로그 불필요) (b) 진짜 encode/mux 실패(원인 추적용 로그 보존).
            if audio_absent:
                log.warning(
                    "audio absent; preserving video-only output. raw_size=%d audio_dur=%.3fs",
                    raw_size, audio_dur,
                )
            else:
                log.warning(
                    "audio mux failed; preserving video-only output. audio_ok=%s "
                    "raw_size=%d audio_log=%s mux_log=%s",
                    audio_ok, raw_size, audio_log_path,
                    mux_log_path if audio_ok else "(skipped)",
                )
            try:
                if video_only != self.output_path and Path(video_only).exists():
                    # output_path 가 부분 생성되어 있으면 지우고 video_only 로 대체
                    if self.output_path.exists():
                        try:
                            self.output_path.unlink()
                        except Exception:
                            pass
                    Path(video_only).rename(self.output_path)
            except Exception as e:
                self.error = f"recovery failed: {e}"
                log.error(self.error)
            for p in (audio_encoded, self.audio_raw_path):
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
            # 오디오 인코드까지도 안 갔으면(audio_absent 또는 encode 실패 전) mux/audio
            # 로그는 비어있거나 없을 테니 정리. 진짜 실패한 단계의 로그만 남긴다.
            if audio_absent:
                for p in (audio_log_path, mux_log_path):
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
            elif not audio_ok:
                try:
                    Path(mux_log_path).unlink(missing_ok=True)
                except Exception:
                    pass
            # 사용자 메시지 — 추측 없이 사실만(원인 단정 X).
            if audio_absent:
                # 영상은 정상. 오디오만 캡처된 소리가 없어 제외 — 'mux 실패'와 구분.
                self.error = self.error or (
                    "영상은 저장됐지만 오디오는 캡처된 소리가 없어 제외했습니다 "
                    "(조용한 구간이었거나 선택된 출력 장치에 소리가 없었습니다)."
                )
            else:
                self.error = self.error or (
                    f"audio mux failed; saved video-only "
                    f"(audio raw {raw_size} bytes — see {audio_log_path.name})"
                )
