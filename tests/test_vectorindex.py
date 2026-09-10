"""벡터 백엔드 테스트: npy(VectorIndex)와 sqlite-vec(SqliteVecIndex) 동일 인터페이스."""

from __future__ import annotations

import numpy as np
import pytest

from vestige.vectorindex import VectorIndex, make_index


def _n(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def _vecs():
    return np.array([_n([1, 0, 0, 0]), _n([0, 1, 0, 0]), _n([0.9, 0.1, 0, 0])], dtype=np.float32)


def test_factory_default_is_npy():
    assert isinstance(make_index("npy"), VectorIndex)
    assert isinstance(make_index(), VectorIndex)  # 기본


def test_sqlite_vec_roundtrip(tmp_path):
    sqlite_vec = pytest.importorskip("sqlite_vec")  # noqa: F841
    from vestige.vectorindex import SqliteVecIndex

    vi = SqliteVecIndex(tmp_path / "v.db")
    vi.add(["a#0", "b#0", "c#0"], _vecs())
    vi.save()
    assert len(vi) == 3

    res = vi.search(_n([1, 0, 0, 0]), k=3)
    keys = [k for k, _ in res]
    assert keys[0] == "a#0"           # 동일 벡터가 1위
    assert keys[1] == "c#0"           # [0.9,0.1] 가 2위(유사)
    assert res[0][1] > res[2][1]      # score 높을수록 유사

    vi.add(["a#0"], _vecs()[:1])      # 멱등 재임베딩
    assert len(vi) == 3
    assert vi.remove(["b#0", "zzz#0"]) == 1
    assert len(vi) == 2
    vi.reset()
    assert len(vi) == 0


def test_sqlite_vec_factory(tmp_path, monkeypatch):
    pytest.importorskip("sqlite_vec")
    from vestige import config as C
    from vestige.vectorindex import SqliteVecIndex
    monkeypatch.setattr(C, "VECTORS_DB_PATH", tmp_path / "v.db")
    assert isinstance(make_index("sqlite-vec"), SqliteVecIndex)
