"""라이브러리 복원 순서 — 저장된 순서 그대로, created_at 재정렬 금지 (2026-07-14).

수동 드래그 재정렬/맨 위로 올리기를 지원하므로 시작 시 created_at 으로 다시
정렬하면 사용자가 만든 순서가 파괴된다. (MainWindow 를 띄우는 무거운 테스트라
한 파일에 격리 — 한 프로세스에 MainWindow 를 여럿 만들면 teardown AV 가 남.)
"""
from screen_recorder.core.settings import AppSettings


def test_restore_preserves_saved_order_not_created_at(qtbot, tmp_path):
    from screen_recorder.app.main import build_main_window
    entries = []
    # 저장 목록은 오래된(아래) → 최신(위) 순. a=맨 아래, c=맨 위.
    # created_at 은 반대로: a 가 가장 최신 → 정렬이 되살아나면 a 가 맨 위로 가버림.
    for name, ts in (("a.md", "2026-07-14T12:00:00"),
                     ("b.md", "2026-07-14T11:00:00"),
                     ("c.md", "2026-07-14T10:00:00")):
        f = tmp_path / name
        f.write_text("x", encoding="utf-8")
        entries.append({
            "kind": "document", "path": str(f), "display_name": name,
            "duration_ms": 0, "origin": "opened", "created_at": ts,
        })
    s = AppSettings()
    s.preferences.recent_library_entries = entries
    win = build_main_window(settings=s)
    qtbot.addWidget(win)
    qtbot.waitUntil(lambda: len(win.library_model.entries()) == 3, timeout=5000)
    names = [e.display_name for e in win.library_model.entries()]
    assert names == ["c.md", "b.md", "a.md"]
    win.close()
