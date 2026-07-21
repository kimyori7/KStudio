"""열린 문서 파일이 디스크에서 바뀌었는지 주기적으로 확인하는 안전망.

왜 통지(QFileSystemWatcher)만으로 부족한가 — 2026-07-21 실측:
  실제 앱에서 감시가 살아 있는데도(3분 뒤 같은 폴더의 파일 생성엔 즉시 신호가 왔다)
  에이전트의 제자리 수정 1건에 대해 directoryChanged 가 오지 않았다. 단독 재현에서는
  쓰기 방식 3종(제자리/생성/atomic) × 볼륨 2종(C:/D:) 전부 수신했고, 앱과 같은 부하
  (라이브러리 60 폴더 + 탭 12 watcher)에서도 10/10 수신했다. 즉 우리 쪽 사용법의
  문제가 아니라 통지 스트림이 이따금 유실된다 — 우리가 고칠 수 있는 층이 아니다.
  ("팝업이 안 뜬다" 3회차 재발. Phase 108·110 은 통지가 도착한 *뒤*만 손봐서 못 막았다.)

그래서 통지에 의존하지 않는 두 번째 경로를 둔다. 이 클래스는 Qt 에 의존하지 않는
순수 로직 — 경로 하나의 (수정시각, 크기) 를 기억했다가 달라졌는지만 알려준다.
타이머와 실제 반영은 호출하는 쪽(MarkdownTab)의 몫이다.

내용을 읽어 비교하지 않는 이유: 폴링은 탭마다 몇 초에 한 번씩 계속 돈다. stat 은
수 마이크로초지만 수십 MB 문서 읽기는 그렇지 않다. 여기서는 값싼 stat 으로 후보만
걸러내고, 진짜 내용 비교는 기존 검사 경로(_reload_check)가 한 번만 한다.
"""
from __future__ import annotations

from pathlib import Path


class DiskPoller:
    """한 파일의 (mtime_ns, size) 지문을 기억했다가 변화를 보고한다."""

    def __init__(self) -> None:
        self._path: Path | None = None
        self._stamp: tuple[int, int] | None = None

    def watch(self, path: Path | None) -> None:
        """감시 대상을 바꾸고 '지금 상태'를 기준으로 새로 찍는다.

        저장/열기/reload 직후에 불러 기준을 맞춘다 — 안 그러면 우리 앱 자신의 쓰기가
        다음 폴링에서 외부 변경으로 보고돼 헛검사가 돈다.
        """
        self._path = Path(path) if path is not None else None
        self._stamp = self._read_stamp()

    def check(self) -> bool:
        """마지막으로 찍은 지문과 달라졌으면 True (그리고 지문을 갱신).

        감시 대상이 없으면 항상 False. 파일이 사라진 경우도 '변화'로 본다 —
        삭제/교체 도중일 수 있어 호출하는 쪽이 판단하게 넘긴다.
        """
        if self._path is None:
            return False
        stamp = self._read_stamp()
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        return True

    def _read_stamp(self) -> tuple[int, int] | None:
        p = self._path
        if p is None:
            return None
        try:
            st = p.stat()
        except OSError:
            # 없음/권한/쓰기 중 잠금 — 지문 없음으로 취급. 다음 호출에서 다시 본다.
            return None
        return (st.st_mtime_ns, st.st_size)
