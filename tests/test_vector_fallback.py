"""sqlite-vec 벡터 백엔드를 못 쓰는 환경(일부 macOS: enable_load_extension 없음)에서
make_index 가 크래시하지 않고 npy(VectorIndex) 로 폴백하는지."""
import vestige.vectorindex as V
from vestige.vectorindex import VectorIndex, make_index


def test_make_index_falls_back_to_npy_when_sqlitevec_unavailable(monkeypatch):
    def _boom(*a, **k):
        raise AttributeError("'sqlite3.Connection' object has no attribute 'enable_load_extension'")
    monkeypatch.setattr(V, "SqliteVecIndex", _boom)
    idx = make_index(backend="sqlite-vec")   # 배포 설정처럼 sqlite-vec 요청
    assert isinstance(idx, VectorIndex)       # 크래시 없이 npy 로 폴백


def test_make_index_npy_default(monkeypatch):
    assert isinstance(make_index(backend="npy"), VectorIndex)
