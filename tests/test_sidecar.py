from screen_recorder.effects.sidecar import Sidecar


def test_audio_muted_roundtrip():
    sc = Sidecar(source_path="x.mp4", audio_muted=True)
    sc2 = Sidecar.from_dict(sc.to_dict())
    assert sc2.audio_muted is True


def test_audio_muted_defaults_false_when_missing():
    # 옛 사이드카 호환 — 키 없으면 False.
    d = {"version": 3, "source_path": "x.mp4", "video_track": []}
    assert Sidecar.from_dict(d).audio_muted is False
