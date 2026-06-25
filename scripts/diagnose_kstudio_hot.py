"""KStudio 가 '계속 뜨거운'(idle 인데 CPU/메모리 높음) 상태의 실제 원인을 뜬다.

사용법 (KStudio 가 떠 있고 뜨거운 상태에서):
    python scripts/diagnose_kstudio_hot.py

무엇을 보나:
  1) KStudio 파이썬 프로세스 자동 탐색 (cmdline 에 screen_recorder / KStudio.exe).
  2) CPU% (1초 샘플), RSS 메모리, 스레드 수, 핸들 수.
  3) **떠 있는 ffmpeg 자식 프로세스 개수** — 썸네일/파형 추출 폭풍이면 많이 잡힘
     (= 원인이 ffmpeg 백로그). 0~1 개인데도 CPU 높으면 파이썬 쪽 루프.
  4) py-spy dump — 파이썬 메인스레드/워커가 '지금 어디서' 돌고 있는지 스택.
     (py-spy 미설치면 설치 안내만 출력하고 1~3 은 그대로 진행.)

출력은 콘솔 + logs/diag_kstudio_hot.txt 에 동시 기록 (logs/ 는 gitignore).
결과를 통째로 복사해 주세요.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_OUT_LINES: list[str] = []


def out(msg: str = "") -> None:
    print(msg)
    _OUT_LINES.append(msg)


def _flush() -> None:
    logs = Path(__file__).resolve().parent.parent / "logs"
    logs.mkdir(exist_ok=True)
    dst = logs / "diag_kstudio_hot.txt"
    dst.write_text("\n".join(_OUT_LINES), encoding="utf-8")
    print(f"\n[저장됨] {dst}")


def _find_psutil():
    try:
        import psutil  # noqa: F401
        return psutil
    except ImportError:
        out("psutil 미설치 — 설치 시도: pip install psutil")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "psutil"],
                           check=True)
            import psutil  # noqa: F811
            return psutil
        except Exception as e:  # noqa: BLE001
            out(f"psutil 설치 실패: {e}")
            return None


def _looks_like_kstudio(p, psutil) -> bool:
    try:
        name = (p.name() or "").lower()
        if "kstudio" in name:
            return True
        cmd = " ".join(p.cmdline()).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    if "screen_recorder" in cmd:
        return True
    # 'python -m screen_recorder' / pythonw 로 띄운 dev 실행.
    if ("python" in name) and ("screen_recorder" in cmd or "kstudio" in cmd):
        return True
    return False


def _count_ffmpeg_children(proc, psutil) -> tuple[int, list[str]]:
    n = 0
    samples: list[str] = []
    try:
        for ch in proc.children(recursive=True):
            try:
                cn = (ch.name() or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if "ffmpeg" in cn or "ffprobe" in cn:
                n += 1
                if len(samples) < 5:
                    try:
                        samples.append(" ".join(ch.cmdline())[:160])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return n, samples


def main() -> int:
    out("=" * 70)
    out(f"KStudio HOT 진단 — {datetime.now().isoformat(timespec='seconds')}")
    out("=" * 70)

    psutil = _find_psutil()
    if psutil is None:
        _flush()
        return 2

    candidates = []
    for p in psutil.process_iter(["pid", "name"]):
        if _looks_like_kstudio(p, psutil):
            candidates.append(p)

    if not candidates:
        out("KStudio 프로세스를 못 찾음. KStudio 가 떠 있는지 확인하세요.")
        out("(dev 실행이면 `python -m screen_recorder` 의 python.exe 입니다.)")
        _flush()
        return 1

    # 여러 개면 CPU 가장 높은 걸 고름.
    for p in candidates:
        try:
            p.cpu_percent(None)   # 1차 샘플 priming
        except Exception:  # noqa: BLE001
            pass
    import time
    time.sleep(1.0)

    def cpu_of(p):
        try:
            return p.cpu_percent(None)
        except Exception:  # noqa: BLE001
            return -1.0

    candidates.sort(key=cpu_of, reverse=True)
    proc = candidates[0]

    out(f"\n발견한 KStudio 후보 {len(candidates)}개. 분석 대상 PID={proc.pid}")
    for p in candidates:
        try:
            out(f"  - PID {p.pid:>7}  name={p.name()}")
        except Exception:  # noqa: BLE001
            pass

    out("\n[리소스]")
    try:
        with proc.oneshot():
            cpu = proc.cpu_percent(None)
            mem = proc.memory_info().rss / (1024 * 1024)
            nthreads = proc.num_threads()
            try:
                handles = proc.num_handles()  # Windows
            except (AttributeError, Exception):  # noqa: BLE001
                handles = -1
        out(f"  CPU%(1s 샘플) : {cpu:.1f}")
        out(f"  메모리 RSS    : {mem:.0f} MB")
        out(f"  스레드 수     : {nthreads}")
        out(f"  핸들 수       : {handles}")
    except Exception as e:  # noqa: BLE001
        out(f"  리소스 조회 실패: {e}")

    out("\n[ffmpeg/ffprobe 자식 프로세스] — 많으면 추출 폭풍이 원인")
    n, samples = _count_ffmpeg_children(proc, psutil)
    out(f"  떠 있는 ffmpeg/ffprobe 개수: {n}")
    for s in samples:
        out(f"    · {s}")
    if n >= 4:
        out("  >>> ffmpeg 가 여러 개 동시 실행 중 = 썸네일/파형 추출 폭풍이 유력.")
    elif n <= 1:
        out("  >>> ffmpeg 거의 없음 = CPU 가 높다면 파이썬 쪽 루프 (아래 py-spy 확인).")

    out("\n[py-spy dump] — 지금 파이썬이 어디서 도는지")
    pyspy = shutil.which("py-spy")
    if pyspy is None:
        out("  py-spy 미설치. 설치하려면: pip install py-spy")
        out("  설치 후 다시 실행하면 스택까지 나옵니다.")
    else:
        try:
            r = subprocess.run(
                [pyspy, "dump", "--pid", str(proc.pid)],
                capture_output=True, timeout=30,
            )
            text = r.stdout.decode("utf-8", "replace")
            err = r.stderr.decode("utf-8", "replace")
            if text.strip():
                out(text)
            if err.strip():
                out("[py-spy stderr]")
                out(err)
        except Exception as e:  # noqa: BLE001
            out(f"  py-spy 실행 실패: {e}")
            out("  (관리자 권한 터미널에서 재시도 필요할 수 있음)")

    _flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
