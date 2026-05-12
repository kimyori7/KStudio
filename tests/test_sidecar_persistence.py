"""사이드카 저장 → 재시작 → 자동 로드 시나리오 단위 테스트.

Phase 19.5 사용자 보고: "편집 → 앱 종료 → 재시작 → 편집 사라짐". 그 시나리오를 코드
수준으로 그대로 재현하여 SidecarStore / EditController / hash 매칭 / glob 패턴 중
어디서 깨지는지 정확히 잡는다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from screen_recorder.core.ffmpeg_check import find_ffmpeg
from screen_recorder.effects import (
    Sidecar, SidecarStore, Trim, compute_video_hash,
)
from screen_recorder.effects.sidecar import save_atomic, load as load_sidecar
from screen_recorder.effects.types.caption import CaptionEffect


# ---------- fixtures ----------

@pytest.fixture
def ffmpeg_or_skip():
    p = find_ffmpeg()
    if not p:
        pytest.skip("ffmpeg required for fixture mp4")
    p = Path(p).resolve()
    if not p.exists():
        pytest.skip(f"ffmpeg not at: {p}")
    return p


@pytest.fixture
def fixture_mp4(tmp_path, ffmpeg_or_skip):
    """1초 검은 화면 mp4 — 영상 hash 계산용 fixture."""
    out = tmp_path / "rec_20260507_191821.mp4"
    subprocess.run(
        [str(ffmpeg_or_skip), "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1", str(out)],
        check=True,
    )
    return out


# ---------- 1. hash 일관성 ----------

def test_compute_video_hash_is_stable(fixture_mp4):
    """같은 파일에 대해 매번 같은 hash."""
    h1 = compute_video_hash(fixture_mp4)
    h2 = compute_video_hash(fixture_mp4)
    assert h1 == h2
    assert len(h1) == 40   # SHA1 hex


# ---------- 2. SidecarStore round-trip ----------

def test_sidecar_store_save_then_load_returns_same_sidecar(fixture_mp4, tmp_path):
    """save_for → 같은 폴더에서 load_for → 동일 sidecar."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    store = SidecarStore(sc_dir)
    sc = Sidecar(
        source_path=str(fixture_mp4),
        source_hash=compute_video_hash(fixture_mp4),
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=100, out_ms=500, text="hello")],
    )
    saved_path = store.save_for(fixture_mp4, sc)
    assert saved_path.exists()
    # 파일명 형식 확인 — `<basename>_<hash>.kstudio`.
    assert saved_path.name.startswith("rec_20260507_191821_")
    assert saved_path.suffix == ".kstudio"

    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    assert len(loaded.effects) == 1
    assert loaded.effects[0].text == "hello"


def test_sidecar_store_load_finds_new_format_file(fixture_mp4, tmp_path):
    """폴더에 `<basename>_<hash>.kstudio` 파일이 있으면 load_for 가 그걸 찾는다.

    glob 패턴이 새 형식을 정확히 매칭하는지 검증.
    """
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    target = sc_dir / f"rec_20260507_191821_{h}.kstudio"
    sc = Sidecar(
        source_path=str(fixture_mp4),
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=200, out_ms=600, text="x")],
    )
    save_atomic(target, sc)

    store = SidecarStore(sc_dir)
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None, (
        f"load_for 가 새 형식 파일 매칭 실패. "
        f"폴더={sc_dir}, 파일={list(sc_dir.iterdir())}, hash={h}"
    )
    assert loaded.effects[0].text == "x"


def test_sidecar_store_load_finds_legacy_format_file(fixture_mp4, tmp_path):
    """구 형식 `<hash>.kstudio` 파일도 load_for 가 찾는다 (backward compat)."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    target = sc_dir / f"{h}.kstudio"
    sc = Sidecar(
        source_path=str(fixture_mp4),
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=200, out_ms=600, text="legacy")],
    )
    save_atomic(target, sc)

    store = SidecarStore(sc_dir)
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    assert loaded.effects[0].text == "legacy"


def test_sidecar_store_save_migrates_legacy_to_new_format(fixture_mp4, tmp_path):
    """구 형식 파일이 있는 상태에서 save_for → 새 형식으로 저장 + 구 파일 삭제."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    legacy = sc_dir / f"{h}.kstudio"
    sc = Sidecar(
        source_path=str(fixture_mp4),
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=0, out_ms=100, text="old")],
    )
    save_atomic(legacy, sc)
    assert legacy.exists()

    # 새 사이드카로 저장.
    sc2 = Sidecar(
        source_path=str(fixture_mp4),
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=0, out_ms=100, text="new")],
    )
    store = SidecarStore(sc_dir)
    new_path = store.save_for(fixture_mp4, sc2)
    assert new_path.name.startswith("rec_20260507_191821_")
    assert new_path.exists()
    # 구 파일 자동 삭제.
    assert not legacy.exists(), "구 형식 파일이 자동 삭제되지 않음"

    # load 도 새 파일에서.
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    assert loaded.effects[0].text == "new"


# ---------- 3. EditController init → 편집 → 재 init = "재시작" 시나리오 ----------

def test_edit_controller_persists_effect_across_restart(qtbot, fixture_mp4, tmp_path):
    """편집 → save → 새 EditController(같은 video, 같은 dir) → 편집 살아있다.

    사용자 보고 "편집 → 종료 → 재시작 → 편집 사라짐" 의 코드 레벨 재현.
    """
    from screen_recorder.ui.video.edit_controller import EditController
    import copy

    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    # 1. 첫 세션 — EditController 생성, effect 추가, save_now.
    ctrl1 = EditController(fixture_mp4, sc_dir)
    qtbot.addWidget(ctrl1) if hasattr(ctrl1, "show") else None
    new_sc = copy.deepcopy(ctrl1.sidecar())
    new_sc.effects.append(
        CaptionEffect(in_ms=200, out_ms=800, text="persistent")
    )
    ctrl1.update_sidecar(new_sc)
    ok = ctrl1.save_now()
    assert ok, "save_now 가 False 반환"

    # 사이드카 폴더에 파일 생성 확인.
    files = list(sc_dir.glob("*.kstudio"))
    assert len(files) == 1, f"폴더 안 파일들: {files}"

    # 2. 재시작 — 새 EditController 인스턴스.
    ctrl2 = EditController(fixture_mp4, sc_dir)
    sidecar2 = ctrl2.sidecar()
    assert len(sidecar2.effects) == 1, (
        f"재시작 후 effect 가 사라짐. 폴더={sc_dir}, "
        f"파일들={list(sc_dir.iterdir())}"
    )
    assert sidecar2.effects[0].text == "persistent"


def test_edit_controller_persists_after_flush_autosave(qtbot, fixture_mp4, tmp_path):
    """autosave 디바운스 의존 — update_sidecar 후 flush → 새 EditController 가 load."""
    from screen_recorder.ui.video.edit_controller import EditController
    import copy

    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    ctrl1 = EditController(fixture_mp4, sc_dir)
    new_sc = copy.deepcopy(ctrl1.sidecar())
    new_sc.effects.append(
        CaptionEffect(in_ms=100, out_ms=400, text="via_flush")
    )
    ctrl1.update_sidecar(new_sc)
    # 디바운스 타이머가 active 상태 — flush 가 즉시 저장.
    flushed = ctrl1.flush_autosave()
    assert flushed, "flush_autosave 가 False 반환 (타이머 비활성)"

    ctrl2 = EditController(fixture_mp4, sc_dir)
    assert len(ctrl2.sidecar().effects) == 1
    assert ctrl2.sidecar().effects[0].text == "via_flush"


# ---------- 4. settings 의 sidecar_dir 가 디스크에 저장/복원 ----------

# ---------- 5. cross-path 자동 마이그레이션 (hash-only 매칭) ----------

def test_load_for_migrates_source_path_when_file_moved(fixture_mp4, tmp_path):
    """파일 이동: 같은 hash, 다른 source_path → load_for 가 새 경로로 자동 갱신."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    # 옛 경로로 저장된 사이드카.
    old_source = r"C:\old\path\rec_20260507_191821.mp4"
    target = sc_dir / f"rec_old_{h}.kstudio"
    sc = Sidecar(
        source_path=old_source,
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=100, out_ms=500, text="kept")],
    )
    save_atomic(target, sc)

    # 새 경로 (fixture_mp4) 로 load — hash 만 매칭하므로 hit.
    store = SidecarStore(sc_dir)
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    assert loaded.effects[0].text == "kept"
    # source_path 가 새 경로로 자동 마이그레이션됨.
    assert loaded.source_path == str(fixture_mp4)


def test_load_for_migrates_segment_src_for_same_source(fixture_mp4, tmp_path):
    """video_track segment 의 src 도 같은 source 이면 같이 마이그레이션."""
    from screen_recorder.effects.sidecar import VideoSegment

    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    old_source = r"C:\old\path\rec.mp4"
    target = sc_dir / f"rec_{h}.kstudio"
    sc = Sidecar(
        source_path=old_source,
        source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        video_track=[
            VideoSegment(src=old_source, src_in_ms=0, src_out_ms=1000,
                         src_duration_ms=1000, start_ms=0),
            # 다른 src 의 segment — 마이그레이션 영향 받지 않음.
            VideoSegment(src=r"C:\other\different.mp4",
                         src_in_ms=0, src_out_ms=500,
                         src_duration_ms=500, start_ms=1000),
        ],
    )
    save_atomic(target, sc)

    store = SidecarStore(sc_dir)
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    # 같은 source 의 segment 만 마이그레이션.
    assert loaded.video_track[0].src == str(fixture_mp4)
    # 다른 src 의 segment 는 그대로.
    assert loaded.video_track[1].src == r"C:\other\different.mp4"


def test_load_for_prefers_matching_source_path_over_stale(fixture_mp4, tmp_path):
    """같은 hash 의 사이드카가 둘 — source_path 매칭이 우선, stale 은 후순위."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    # Stale: 다른 source_path.
    stale_target = sc_dir / f"rec_stale_{h}.kstudio"
    stale_sc = Sidecar(
        source_path=r"C:\old\rec.mp4", source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=0, out_ms=100, text="stale")],
    )
    save_atomic(stale_target, stale_sc)
    # Fresh: 정확히 매칭하는 source_path.
    fresh_target = sc_dir / f"rec_fresh_{h}.kstudio"
    fresh_sc = Sidecar(
        source_path=str(fixture_mp4), source_hash=h,
        trim=Trim(in_ms=0, out_ms=0),
        effects=[CaptionEffect(in_ms=0, out_ms=100, text="fresh")],
    )
    save_atomic(fresh_target, fresh_sc)

    store = SidecarStore(sc_dir)
    loaded = store.load_for(fixture_mp4)
    assert loaded is not None
    # fresh 가 우선 — stale 이 알파벳 먼저여도.
    assert loaded.effects[0].text == "fresh"


def test_save_for_cleans_up_other_same_hash_sidecars(fixture_mp4, tmp_path):
    """save_for 가 같은 hash 의 다른 사이드카를 정리 (hash-only 매칭이라 stale 의미 없음)."""
    sc_dir = tmp_path / "sidecars"
    sc_dir.mkdir()
    h = compute_video_hash(fixture_mp4)
    # 옛 사이드카 두 개 (다른 source_path).
    a = sc_dir / f"rec_a_{h}.kstudio"
    b = sc_dir / f"rec_b_{h}.kstudio"
    save_atomic(a, Sidecar(source_path=r"C:\old_a.mp4", source_hash=h,
                            trim=Trim(in_ms=0, out_ms=0)))
    save_atomic(b, Sidecar(source_path=r"C:\old_b.mp4", source_hash=h,
                            trim=Trim(in_ms=0, out_ms=0)))

    store = SidecarStore(sc_dir)
    new_sc = Sidecar(source_path=str(fixture_mp4), source_hash=h,
                     trim=Trim(in_ms=0, out_ms=0),
                     effects=[CaptionEffect(in_ms=0, out_ms=100, text="new")])
    new_path = store.save_for(fixture_mp4, new_sc)
    # 새 파일만 남고 옛 a, b 는 삭제.
    remaining = sorted(sc_dir.glob("*.kstudio"))
    assert remaining == [new_path], (
        f"같은 hash 의 stale 사이드카가 안 지워짐: {remaining}"
    )


# ---------- 6. settings sidecar_dir round-trip ----------

def test_preferences_sidecar_dir_persists_to_settings(tmp_path):
    """preferences.sidecar_dir 가 save → load round-trip 으로 복원된다."""
    from screen_recorder.core import settings as settings_mod

    settings_file = tmp_path / "settings.json"
    # 1. AppSettings 생성 + sidecar_dir 설정 + save.
    s1 = settings_mod.AppSettings()
    s1.preferences.sidecar_dir = str(tmp_path / "my_sidecar_folder")
    settings_mod.save(s1, settings_file)
    assert settings_file.exists()

    # 2. load → 같은 값?
    s2 = settings_mod.load(settings_file)
    assert s2.preferences.sidecar_dir == str(tmp_path / "my_sidecar_folder"), (
        f"sidecar_dir 가 디스크 round-trip 에서 사라짐. "
        f"settings.json 내용: {settings_file.read_text(encoding='utf-8')}"
    )
