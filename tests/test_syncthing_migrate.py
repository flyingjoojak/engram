"""Syncthing rename 잔재 폴더 자가복구 테스트.

chatmem→engram 이름 변경으로 같은 경로에 두 폴더(chatmem-/engram-claude-projects)가 생기면
Syncthing이 충돌로 동기화가 막힌다. startup의 migrate_legacy_folder가 상대 기기를 새 폴더로
옮기고 옛 폴더를 제거하는지 검증(실 REST 없이 호출만 기록)."""

from __future__ import annotations

import engram.syncthing as st


class _FakeST(st.Syncthing):
    """REST를 목킹한 Syncthing — config/device_id 고정, share/remove 호출 기록."""

    def __init__(self, folders):
        self._cfg = {"folders": folders}
        self.shared_with: list[str] | None = None
        self.removed: list[str] = []

    def device_id(self):
        return "ME"

    def config(self):
        return self._cfg

    def share_projects(self, projects_dir, remote_ids, folder_id=st.DEFAULT_FOLDER_ID, label="Claude projects"):
        self.shared_with = list(remote_ids)

    def remove_folder(self, folder_id):
        self.removed.append(folder_id)


def test_migrates_legacy_folder_and_merges_peers():
    folders = [
        {"id": st.LEGACY_FOLDER_ID, "path": "/p", "devices": [{"deviceID": "ME"}, {"deviceID": "PEER_A"}]},
        {"id": st.DEFAULT_FOLDER_ID, "path": "/p", "devices": [{"deviceID": "ME"}, {"deviceID": "PEER_B"}]},
    ]
    s = _FakeST(folders)
    assert s.migrate_legacy_folder("/p") is True
    # 옛 폴더 제거
    assert s.removed == [st.LEGACY_FOLDER_ID]
    # 두 폴더의 상대(PEER_A, PEER_B)를 새 폴더로 병합, 나(ME)는 제외
    assert set(s.shared_with) == {"PEER_A", "PEER_B"}
    assert "ME" not in s.shared_with


def test_no_legacy_folder_is_noop():
    folders = [{"id": st.DEFAULT_FOLDER_ID, "path": "/p", "devices": [{"deviceID": "ME"}, {"deviceID": "PEER_B"}]}]
    s = _FakeST(folders)
    assert s.migrate_legacy_folder("/p") is False   # 신규 설치 = 잔재 없음
    assert s.removed == []
    assert s.shared_with is None
