"""로컬 임베딩(fastembed). e5 계열은 query/passage 프리픽스를 붙인다.

벡터는 L2 정규화하여 저장 → 코사인 유사도 = 내적(검색 시 행렬곱 한 번).
백엔드 교체 가능: model_name만 바꾸면 되고, 프리픽스는 e5일 때만 적용.
"""

from __future__ import annotations

import numpy as np

from .config import E5_PASSAGE_PREFIX, E5_QUERY_PREFIX, EMBED_MODEL


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype(np.float32)


class Embedder:
    """색인·검색 공통 임베더. 같은 모델을 써야 벡터가 호환된다."""

    def __init__(self, model_name: str = EMBED_MODEL):
        self.model_name = model_name
        self._is_e5 = "e5" in model_name.lower()   # int8 id도 'e5' 포함 → 프리픽스 적용
        from .int8_model import INT8_MODEL_ID
        if model_name == INT8_MODEL_ID:
            # int8 커스텀 모델: 번들(배포)/캐시(개발)에서 로컬 로드. fastembed는 프리픽스 미적용 → _prefix가 담당.
            from .int8_model import make_text_embedding
            self._model = make_text_embedding()
        else:
            from fastembed import TextEmbedding  # 무거운 임포트 → 지연
            self._model = TextEmbedding(model_name=model_name)

    def _prefix(self, texts: list[str], prefix: str) -> list[str]:
        return [prefix + t for t in texts] if self._is_e5 else list(texts)

    def embed_passages(self, texts: list[str], parallel: int | None = None,
                       batch_size: int | None = None) -> np.ndarray:
        """passage 임베딩. parallel=N이면 fastembed 멀티프로세싱(N 프로세스)으로 대량 가속.
        parallel은 프로세스마다 모델을 또 로드하므로 RAM을 N배 쓴다(고성능 기기 전용)."""
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        kw: dict = {}
        if parallel is not None:
            kw["parallel"] = parallel
        if batch_size is not None:
            kw["batch_size"] = batch_size
        vecs = list(self._model.embed(self._prefix(texts, E5_PASSAGE_PREFIX), **kw))
        return _l2_normalize(np.asarray(vecs, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        vecs = list(self._model.embed(self._prefix([text], E5_QUERY_PREFIX)))
        return _l2_normalize(np.asarray(vecs, dtype=np.float32))[0]
