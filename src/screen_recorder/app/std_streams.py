"""콘솔 없는 실행에서 sys.stdout·stderr 가 None 이라 죽는 문제를 막는 시작 가드.

pythonw.exe(콘솔 없는 파이썬) 와 PyInstaller windowed 빌드(console=False)는 표준
출력/에러 스트림이 없어 sys.stdout·sys.stderr 가 None 이 된다. 이 상태에서 stderr 에
직접 쓰는 서드파티가 있으면 `AttributeError: 'NoneType' object has no attribute 'write'`
로 즉사한다.

실측 사례: 자동 누끼 모델 다운로드(rembg → pooch → tqdm 진행률 막대)가 첫 줄을 그리려
sys.stderr.write() 를 호출하는 순간 터져, 모델 파일을 0바이트도 못 받고 멈춤
("0.0 / 5 MB, 0%" 영구 정체). 콘솔 있는 python.exe 에선 재현 안 되고 pythonw.exe·.exe
에서만 발생 — 차이는 오직 표준 스트림이 None 이라는 점.

해결: 시작 시 None 인 스트림만 안전한 싱크로 교체한다. 콘솔이 있으면 None 이 아니므로
아무 것도 하지 않는다(무해·idempotent). 앱은 어차피 logging(파일 핸들러)으로 기록하므로
stderr 내용을 버려도 손실이 없다.
"""
from __future__ import annotations
import io
import sys


class _NullStream(io.TextIOBase):
    """write 를 받아 버리는 더미 텍스트 스트림.

    tqdm·print 등이 write/flush/isatty 를 호출해도 안전하게 무시한다. None 대신
    이 객체를 두면 콘솔 없는 환경에서도 stderr 쓰기가 예외 없이 통과한다.
    """

    def writable(self) -> bool:
        return True

    def write(self, s) -> int:
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def ensure_std_streams() -> None:
    """sys.stdout / sys.stderr 가 None 이면 _NullStream 으로 교체한다.

    콘솔 있는 실행에선 None 이 아니므로 그대로 둔다. 가능한 한 일찍(다른 import·로깅·
    Qt 초기화 전에) 호출해야 한다.
    """
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()
