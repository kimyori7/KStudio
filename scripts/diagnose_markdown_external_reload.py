"""실제 OS→Qt directoryChanged 전달 경로 검증 (수동 emit 아님).

유닛테스트는 _reload_check 를 직접 호출하거나 시그널을 모사한다. 이 스크립트는 진짜
QFileSystemWatcher(부모 디렉터리 감시)가 외부 파일 쓰기를 감지해 열린 탭을 갱신하는지
— 사용자가 보고한 바로 그 경로 — 를 실제 이벤트 루프에서 확인한다.

PASS 조건:
  S1 깨끗한 탭: 외부 제자리 쓰기 → 탭 내용이 새 내용으로 자동 갱신
  S2 더티 탭: 미저장 편집 상태에서 외부 쓰기 → 덮어쓰지 않고 팝업(dirty 경고)
  S3 atomic save: VS Code 식 temp→rename 교체가 (a) 막히지 않고 (b) 탭에 반영
     (파일 직접 감시였으면 os.replace 가 WinError 5 로 막혔다 — 근본 원인)
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("KSTUDIO_SETTINGS_DIR", str(Path(os.environ.get("TEMP", ".")) / "kstudio_diag_reload"))

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from screen_recorder.ui.markdown_tab import MarkdownTab


def _pump_until(app, predicate, timeout_s=4.0):
    """이벤트를 돌리며 predicate 가 True 가 될 때까지 대기 (최대 timeout)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.03)
    app.processEvents()
    return predicate()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = Path(os.environ["KSTUDIO_SETTINGS_DIR"])
    tmp.mkdir(parents=True, exist_ok=True)

    ok = True

    # --- S1: 깨끗한 탭 → 외부 변경이 확인 팝업에 도달 + [예] 면 반영 ---
    p1 = tmp / "s1.md"
    p1.write_text("ORIGINAL CONTENT\n", encoding="utf-8")
    tab1 = MarkdownTab.from_file(p1)
    s1_calls = []
    tab1._confirm_external_reload = lambda dirty: (s1_calls.append(dirty) or True)  # [예]
    tab1.show()
    app.processEvents()
    assert tab1.editor.toPlainText() == "ORIGINAL CONTENT\n"
    # 외부 에디터가 파일을 덮어쓰는 것과 동일한 평범한 쓰기
    p1.write_text("CHANGED BY EXTERNAL EDITOR\n", encoding="utf-8")
    got = _pump_until(app, lambda: tab1.editor.toPlainText() == "CHANGED BY EXTERNAL EDITOR\n")
    print(f"S1 clean prompt+yes: {'PASS' if (got and s1_calls == [False]) else 'FAIL'} "
          f"(prompted={s1_calls}, editor={tab1.editor.toPlainText()!r}, needs_save={tab1.needs_save()})")
    ok = ok and got and s1_calls == [False] and not tab1.needs_save()

    # --- S2: 더티 탭 → 팝업 도달(dirty 경고) + [아니오] 면 편집 보존 ---
    p2 = tmp / "s2.md"
    p2.write_text("BASE\n", encoding="utf-8")
    tab2 = MarkdownTab.from_file(p2)
    s2_calls = []
    tab2._confirm_external_reload = lambda dirty: (s2_calls.append(dirty) or False)  # [아니오]
    tab2.show()
    app.processEvents()
    tab2.editor.setPlainText("MY UNSAVED WORK")          # 미저장 편집
    assert tab2.needs_save()
    p2.write_text("EXTERNAL CHANGE WHILE DIRTY\n", encoding="utf-8")
    asked = _pump_until(app, lambda: s2_calls == [True])
    kept = tab2.editor.toPlainText() == "MY UNSAVED WORK"
    print(f"S2 dirty prompt+no: {'PASS' if (asked and kept) else 'FAIL'} "
          f"(prompted={s2_calls}, edit_kept={kept})")
    ok = ok and asked and kept

    # --- S3: atomic save(temp→rename) 가 막히지 않고 반영 (사용자 실제 케이스: VS Code) ---
    p3 = tmp / "s3.md"
    p3.write_text("BEFORE ATOMIC\n", encoding="utf-8")
    tab3 = MarkdownTab.from_file(p3)
    s3_calls = []
    tab3._confirm_external_reload = lambda dirty: (s3_calls.append(dirty) or True)  # [예]
    tab3.show()
    app.processEvents()
    replace_ok = True
    try:
        tmp_sidecar = p3.with_name(p3.name + ".tmp")
        tmp_sidecar.write_text("AFTER ATOMIC SAVE\n", encoding="utf-8")
        os.replace(tmp_sidecar, p3)        # 파일 직접 감시였으면 WinError 5
    except OSError as e:
        replace_ok = False
        print(f"S3 atomic replace FAILED to write: {e}")
    got3 = _pump_until(app, lambda: tab3.editor.toPlainText() == "AFTER ATOMIC SAVE\n")
    print(f"S3 atomic save reflect: {'PASS' if (replace_ok and got3) else 'FAIL'} "
          f"(replace_ok={replace_ok}, prompted={s3_calls}, editor={tab3.editor.toPlainText()!r})")
    ok = ok and replace_ok and got3

    # --- S4: 통지가 죽어도 폴링 안전망이 잡는다 (2026-07-21 실측 유실 대응) ---
    # 실제 앱에서 살아있는 watcher 가 진짜 쓰기 1건을 놓친 게 관측됐다. 여기서는
    # watcher 를 아예 떼어내 그 상황을 만들고, QTimer 폴링만으로 반영되는지 본다.
    # (유닛테스트는 _poll_disk 를 직접 부른다 — 이 시나리오는 타이머 배선까지 검증.)
    p4 = tmp / "s4.md"
    p4.write_text("BEFORE POLL\n", encoding="utf-8")
    tab4 = MarkdownTab.from_file(p4)
    s4_calls = []
    tab4._confirm_external_reload = lambda dirty: (s4_calls.append(dirty) or True)
    tab4.show()
    app.processEvents()
    watched4 = tab4._fs_watcher.files() + tab4._fs_watcher.directories()
    if watched4:
        tab4._fs_watcher.removePaths(watched4)      # 통지 경로 절단
    severed = not tab4._fs_watcher.directories()
    p4.write_text("AFTER POLL\n", encoding="utf-8")
    got4 = _pump_until(app, lambda: tab4.editor.toPlainText() == "AFTER POLL\n", timeout_s=8.0)
    print(f"S4 poll fallback (watcher severed): {'PASS' if (severed and got4) else 'FAIL'} "
          f"(severed={severed}, prompted={s4_calls}, editor={tab4.editor.toPlainText()!r})")
    ok = ok and severed and got4

    print("\nRESULT:", "ALL PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
