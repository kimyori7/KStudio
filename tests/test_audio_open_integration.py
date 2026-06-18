"""오디오 열기 통합 — _open_audio_path 가 AudioTab 을 만들고 라이브러리에 등록 +
오디오 탭 활성 시 _on_export_audio 가 그 탭을 인식하는지.

⚠ build_main_window() 는 한 프로세스에서 여러 번 만들면 오프스크린 Qt teardown 이
누적돼 크래시(test_document_library_integration 주석 참조) → 이 파일은 인스턴스 1개만.
더미 파일이라 재생/디코드는 안 함(showEvent 전 load 지연).
"""


def test_open_audio_then_export_routes_to_audio_tab(qtbot, tmp_path, monkeypatch):
    from screen_recorder.app.main import build_main_window
    from screen_recorder.ui.audio_tab import AudioTab
    from screen_recorder.ui.library_model import EntryKind
    from PySide6.QtWidgets import QMessageBox

    win = build_main_window()
    qtbot.addWidget(win)

    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"\x00")
    win._open_audio_path(mp3)

    # 1) AudioTab 으로 열렸는지 + 소스 경로.
    cur = win.tab_area.currentWidget()
    assert isinstance(cur, AudioTab)
    assert cur.source_path().endswith("song.mp3")

    # 2) 라이브러리에 AUDIO entry 등록.
    kinds = [e.kind for e in win.library_model.entries()]
    assert EntryKind.AUDIO in kinds

    # 3) 내보내기 라우팅 — 오디오 탭이 활성이면 _on_export_audio 가 그 탭을 집는다.
    #    duration 0 이라 길이 가드의 경고가 뜬다 = 라우팅이 AudioTab 을 인식했다는 증거.
    #    (인식 못 하면 tab is None 으로 조용히 return → 경고 없음.) 모달이 헤드리스에서
    #    블로킹하므로 warning 을 가로채 기록만 한다.
    warned = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warned.append(a)),
    )
    win._on_export_audio()
    assert warned, "오디오 탭이 활성인데 _on_export_audio 가 길이 가드까지 못 감(라우팅 실패)"

    # 4) 확장자 기반 kind 정정 — 라이브러리 복원 시 오디오가 IMAGE 로 가던 회귀 방지
    #    + "형식에 맞는 모드 라이브러리" 요구 충족. 저장된(틀린) kind 를 확장자가 이긴다.
    from pathlib import Path as _P
    assert win._kind_for_path(_P("a.mp3"), fallback=EntryKind.IMAGE) == EntryKind.AUDIO
    assert win._kind_for_path(_P("b.MP4"), fallback=EntryKind.IMAGE) == EntryKind.VIDEO
    assert win._kind_for_path(_P("c.png"), fallback=EntryKind.AUDIO) == EntryKind.IMAGE
    assert win._kind_for_path(_P("d.md"), fallback=EntryKind.IMAGE) == EntryKind.DOCUMENT
    # 모르는 확장자는 저장된 kind 유지.
    assert win._kind_for_path(_P("e.kstudio"), fallback=EntryKind.IMAGE) == EntryKind.IMAGE

    # 5) 전역 Space / 메뉴 Ctrl+Z 가 오디오 탭으로 라우팅된다(자체 단축키는 기존 전역
    #    Space·메뉴 Ctrl+Z 와 ambiguous 라 제거 → MainWindow 핸들러가 라우팅).
    audio_tab = win.tab_area.currentWidget()
    assert isinstance(audio_tab, AudioTab)
    toggled, undone, redone = [], [], []
    monkeypatch.setattr(audio_tab, "_toggle_play", lambda: toggled.append(1))
    monkeypatch.setattr(audio_tab, "_undo", lambda: undone.append(1))
    monkeypatch.setattr(audio_tab, "_redo", lambda: redone.append(1))
    win._on_global_space()
    assert toggled, "전역 Space 가 오디오 탭 재생으로 라우팅되지 않음"
    win._on_undo()
    assert undone, "메뉴 Ctrl+Z 가 오디오 탭 실행취소로 라우팅되지 않음"
    win._on_redo()
    assert redone, "메뉴 Ctrl+Y 가 오디오 탭 다시실행으로 라우팅되지 않음"
