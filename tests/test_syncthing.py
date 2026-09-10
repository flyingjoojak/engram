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
