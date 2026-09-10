"""int8 e5-large 커스텀 모델: 등록·카탈로그·기본값 (무거운 모델 로드 없이)."""
import os
from pathlib import Path

from vestige.int8_model import INT8_MODEL_ID, register


def test_int8_in_catalog():
    from vestige import web
    assert INT8_MODEL_ID in web._EMBED_ALLOW


def test_int8_is_e5_so_prefix_applied():
    # Embedder._is_e5 = 'e5' in name → int8 id도 query/passage 프리픽스 적용돼야 함(정합 핵심).
    assert "e5" in INT8_MODEL_ID.lower()


def test_register_idempotent_and_adds_custom_model():
    from fastembed import TextEmbedding
    register(Path("dummy"))   # add_custom_model은 메타만 등록 — 모델 파일 불필요
    register(Path("dummy"))   # 두 번째 호출도 예외 없이 통과(멱등)
    assert INT8_MODEL_ID in {m["model"] for m in TextEmbedding.list_supported_models()}


def test_default_model_is_int8():
    from vestige import config
    if "VESTIGE_EMBED_MODEL" not in os.environ:
        assert config.EMBED_MODEL == INT8_MODEL_ID
