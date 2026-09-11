"""임베디드 Syncthing 관리 단위 테스트 (E1) — 네트워크 없이 순수 로직만."""

from __future__ import annotations

from vestige import syncthing as S


def test_plat_returns_known_shape():
    osname, arch, ext, exe = S._plat()
    assert osname in ("windows", "macos", "linux")
    assert ext in (".zip", ".tar.gz")
    assert exe in ("syncthing", "syncthing.exe")


def test_asset_url_shape():
    url, name = S._asset_url("v2.1.3")
    # 릴리스 자산명 규칙: syncthing-<os>-<arch>-<ver><ext>
    assert name.startswith("syncthing-") and "v2.1.3" in name
    assert url == f"https://github.com/syncthing/syncthing/releases/download/v2.1.3/{name}"


def test_binary_path_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "syncthing-custom"
    fake.write_text("x")
    monkeypatch.setenv("VESTIGE_SYNCTHING_BIN", str(fake))
    assert S.binary_path() == fake


def test_free_port_is_usable():
    p = S._free_port()
    assert 1 <= p <= 65535


def test_add_device_request_shape(monkeypatch):
    st = S.Syncthing(gui_port=1, apikey="k")
    calls = []
    monkeypatch.setattr(st, "_req", lambda m, p, body=None, timeout=8.0: calls.append((m, p, body)) or {})
    st.add_device("DEVID123", "friend")
    m, path, body = calls[-1]
    assert m == "PUT" and path == "/rest/config/devices/DEVID123"
    assert body["deviceID"] == "DEVID123" and body["name"] == "friend"


def test_share_projects_request_shape(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    calls = []
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "_req", lambda m, p, body=None, timeout=8.0: calls.append((m, p, body)) or {})
    st.share_projects(tmp_path / "proj", ["REMOTE1"], folder_id="fid")
    m, path, body = calls[-1]
    assert m == "PUT" and path == "/rest/config/folders/fid"
    assert body["id"] == "fid" and body["path"].endswith("proj") and body["type"] == "sendreceive"
    ids = {d["deviceID"] for d in body["devices"]}
    assert ids == {"MYID", "REMOTE1"}   # 내 기기 + 상대(중복·self 제거)
    assert body["versioning"]["type"] == "staggered"   # 삭제·덮어쓰기 이력 보존


def test_share_projects_dedupes_devices(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    calls = []
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "_req", lambda m, p, body=None, timeout=8.0: calls.append((m, p, body)) or {})
    st.share_projects(tmp_path / "p", ["REMOTE1", "REMOTE1", "MYID", ""])   # 중복·self·빈값
    ids = [d["deviceID"] for d in calls[-1][2]["devices"]]
    assert ids == ["MYID", "REMOTE1"]   # 순서 유지 + 중복/빈값 제거


def _sync_with(monkeypatch, status: dict) -> dict:
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "folder_status", lambda folder_id=S.DEFAULT_FOLDER_ID: status)
    return st.folder_sync()


def test_folder_sync_idle_is_complete(monkeypatch):
    r = _sync_with(monkeypatch, {"state": "idle", "globalBytes": 1000, "needBytes": 0})
    assert r["state"] == "idle" and r["completion"] == 100.0 and r["need_items"] == 0


def test_folder_sync_partial_completion(monkeypatch):
    r = _sync_with(monkeypatch, {"state": "syncing", "globalBytes": 1000, "needBytes": 250,
                                 "needFiles": 3, "needDirectories": 1})
    assert r["state"] == "syncing" and r["completion"] == 75.0 and r["need_items"] == 4


def test_folder_sync_empty_global_is_100(monkeypatch):
    # 빈 폴더(글로벌 0바이트)는 0으로 나누지 않고 최신(100%)으로 취급
    r = _sync_with(monkeypatch, {"state": "idle", "globalBytes": 0, "needBytes": 0})
    assert r["completion"] == 100.0


def test_pair_summary_folds_remote_completion(monkeypatch):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "config", lambda: {
        "devices": [{"deviceID": "MYID"}, {"deviceID": "PEER1"}, {"deviceID": "PEER2"}],
        "folders": [{"id": S.DEFAULT_FOLDER_ID, "path": "/p", "devices": []}],
    })
    # PEER1 연결·80%, PEER2 미연결 → 연결된 상대만 집계, 최소치 채택
    monkeypatch.setattr(st, "connections", lambda: {"connections": {
        "PEER1": {"connected": True}, "PEER2": {"connected": False}}})
    monkeypatch.setattr(st, "folder_sync", lambda fid=S.DEFAULT_FOLDER_ID: {
        "state": "idle", "completion": 100.0, "need_items": 0, "need_bytes": 0, "global_bytes": 1})
    monkeypatch.setattr(st, "device_completion", lambda did, fid=S.DEFAULT_FOLDER_ID: 80.0 if did == "PEER1" else 0.0)
    out = st.pair_summary()
    assert out["sync"]["remote_complete"] == 80.0   # 연결된 PEER1만
    assert out["sync"]["peers_connected"] == 1


def test_device_completion_parses(monkeypatch):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "_get", lambda p, timeout=5.0: {"completion": 42.5})
    assert st.device_completion("PEER1") == 42.5


# ── #153: Codex 원본 폴더 두 번째 공유 ─────────────────────────────
def test_merge_sync_takes_worst_case():
    merged = S._merge_sync([
        {"state": "idle", "completion": 100.0, "need_items": 0, "need_bytes": 0, "global_bytes": 5},
        {"state": "syncing", "completion": 30.0, "need_items": 2, "need_bytes": 7, "global_bytes": 5},
    ])
    assert merged["completion"] == 30.0        # 가장 덜 받은 폴더 기준
    assert merged["state"] == "syncing"        # 더 심각한 상태
    assert merged["need_items"] == 2 and merged["need_bytes"] == 7 and merged["global_bytes"] == 10


def test_ensure_codex_folder_mirrors_projects_peers(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "config", lambda: {"folders": [
        {"id": S.DEFAULT_FOLDER_ID, "devices": [{"deviceID": "MYID"}, {"deviceID": "PEER1"}]}]})
    calls = []
    monkeypatch.setattr(st, "_req", lambda m, p, body=None, timeout=8.0: calls.append((m, p, body)) or {})
    assert st.ensure_codex_folder(tmp_path / "codex") is True
    m, path, body = calls[-1]
    assert m == "PUT" and path == f"/rest/config/folders/{S.CODEX_FOLDER_ID}"
    assert body["id"] == S.CODEX_FOLDER_ID and body["label"] == "Codex sessions"
    assert {d["deviceID"] for d in body["devices"]} == {"MYID", "PEER1"}   # projects 상대 미러
    assert (tmp_path / "codex").exists()   # 파리티: 상대가 codex 안 써도 받도록 로컬 폴더 생성


def test_ensure_codex_folder_noop_before_pairing(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "config", lambda: {"folders": []})   # 아직 projects 폴더 없음
    calls = []
    monkeypatch.setattr(st, "_req", lambda *a, **k: calls.append(a) or {})
    assert st.ensure_codex_folder(tmp_path / "codex") is False
    assert calls == []   # 단독 사용자 → PUT 없음


def test_ensure_codex_folder_noop_without_peers(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "config", lambda: {"folders": [
        {"id": S.DEFAULT_FOLDER_ID, "devices": [{"deviceID": "MYID"}]}]})   # 나만
    calls = []
    monkeypatch.setattr(st, "_req", lambda *a, **k: calls.append(a) or {})
    assert st.ensure_codex_folder(tmp_path / "codex") is False
    assert calls == []


def test_remove_device_updates_both_folders(monkeypatch, tmp_path):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "config", lambda: {"folders": [
        {"id": S.DEFAULT_FOLDER_ID, "devices": [{"deviceID": d} for d in ("MYID", "PEER1", "GONE")]},
        {"id": S.CODEX_FOLDER_ID, "devices": [{"deviceID": d} for d in ("MYID", "PEER1", "GONE")]},
    ]})
    calls = []
    monkeypatch.setattr(st, "_req", lambda m, p, body=None, timeout=8.0: calls.append((m, p, body)) or {})
    assert st.remove_device("GONE", tmp_path / "proj") is True
    puts = [(p, body) for (m, p, body) in calls if m == "PUT"]
    proj_put = next(b for (p, b) in puts if p.endswith(S.DEFAULT_FOLDER_ID))
    codex_put = next(b for (p, b) in puts if p.endswith(S.CODEX_FOLDER_ID))
    assert {d["deviceID"] for d in proj_put["devices"]} == {"MYID", "PEER1"}   # GONE 제거
    assert {d["deviceID"] for d in codex_put["devices"]} == {"MYID", "PEER1"}  # codex 폴더도 동일
    assert ("DELETE", "/rest/config/devices/GONE", None) in calls             # device 등록도 삭제


def test_pair_summary_aggregates_projects_and_codex(monkeypatch):
    st = S.Syncthing(gui_port=1, apikey="k")
    monkeypatch.setattr(st, "device_id", lambda: "MYID")
    monkeypatch.setattr(st, "config", lambda: {
        "devices": [{"deviceID": "MYID"}, {"deviceID": "PEER1"}],
        "folders": [{"id": S.DEFAULT_FOLDER_ID, "path": "/p", "devices": []},
                    {"id": S.CODEX_FOLDER_ID, "path": "/c", "devices": []}],
    })
    monkeypatch.setattr(st, "connections", lambda: {"connections": {"PEER1": {"connected": True}}})
    monkeypatch.setattr(st, "folder_sync", lambda fid=S.DEFAULT_FOLDER_ID: (
        {"state": "idle", "completion": 100.0, "need_items": 0, "need_bytes": 0, "global_bytes": 10}
        if fid == S.DEFAULT_FOLDER_ID else
        {"state": "syncing", "completion": 40.0, "need_items": 3, "need_bytes": 6, "global_bytes": 10}))
    # PEER1: projects 100% · codex 50% → 폴더별 최소 50%
    monkeypatch.setattr(st, "device_completion",
                        lambda did, fid=S.DEFAULT_FOLDER_ID: 100.0 if fid == S.DEFAULT_FOLDER_ID else 50.0)
    s = st.pair_summary()["sync"]
    assert s["completion"] == 40.0 and s["state"] == "syncing"   # 최소·최악
    assert s["need_items"] == 3 and s["need_bytes"] == 6
    assert s["remote_complete"] == 50.0 and s["peers_connected"] == 1   # 폴더별 최소로 접음
