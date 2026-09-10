"""int8 양자화 e5-large 커스텀 모델: 준비(생성/번들 해석) + fastembed 등록.

- 배포(frozen exe): int8 모델 디렉터리를 PyInstaller가 번들(_MEIPASS/e5int8) → 다운로드·양자화 없이 즉시 로드.
- 개발(python): 캐시에 없으면 그 자리에서 생성(fp32 다운로드 → 동적 int8 양자화 → 토크나이저 복사).
  onnx/onnxruntime.quantization은 개발·빌드에서만 필요하고 frozen exe 런타임엔 불필요(번들을 쓰므로).

fastembed는 커스텀 모델에 query/passage 프리픽스를 자동으로 붙이지 않으므로, 임베딩 시
호출측(Embedder._prefix, 이름에 'e5' 포함 → 적용)이 프리픽스를 넣어야 한다.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

INT8_MODEL_ID = "intfloat/multilingual-e5-large-int8"
FP32_MODEL_ID = "intfloat/multilingual-e5-large"
_TOKENIZER_FILES = ["tokenizer.json", "config.json", "special_tokens_map.json", "tokenizer_config.json"]
_registered = False


def _bundled_dir() -> Path | None:
    """frozen exe에 번들된 int8 디렉터리(_MEIPASS/e5int8). 없으면 None."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        d = Path(base) / "e5int8"
        if (d / "model.onnx").exists():
            return d
    return None


def _cache_dir() -> Path:
    """개발 환경에서 생성/보관하는 int8 디렉터리 경로."""
    from . import config as C
    return C.DATA_DIR / "models" / "e5int8"


def generate_int8_dir(dst: Path, log_fn=print) -> Path:
    """fp32 e5-large를 받아 동적 int8 양자화 → dst에 model.onnx + 토크나이저 구성.
    개발/빌드 전용(onnx·onnxruntime.quantization 필요)."""
    from fastembed import TextEmbedding
    from onnxruntime.quantization import QuantType, quantize_dynamic

    import tempfile

    dst.mkdir(parents=True, exist_ok=True)
    log_fn("fp32 e5-large 확보(fastembed 캐시)…")
    te = TextEmbedding(FP32_MODEL_ID)
    src = Path(te.model._model_dir)   # 다운로드된 fp32 onnx + 토크나이저 위치
    # HF 캐시는 외부 가중치(model.onnx_data)를 심볼릭 링크로 둘 수 있는데, onnx 체커/양자화기가
    # 심링크 외부데이터를 거부한다("should be stored in ..., but it is a symbolic link").
    # → model.onnx + 외부데이터를 임시 폴더로 복사(shutil.copy는 심링크를 따라가 실제 파일로 복사)한 뒤 양자화.
    work = Path(tempfile.mkdtemp(prefix="e5int8_src_"))
    try:
        shutil.copy(src / "model.onnx", work / "model.onnx")
        for extra in src.iterdir():
            if extra.name.startswith("model.onnx") and extra.name != "model.onnx":
                shutil.copy(extra, work / extra.name)   # model.onnx_data 등 외부 가중치(심링크 해제)
        log_fn("int8 동적 양자화…")
        quantize_dynamic(str(work / "model.onnx"), str(dst / "model.onnx"), weight_type=QuantType.QInt8)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for f in _TOKENIZER_FILES:
        shutil.copy(src / f, dst / f)
    log_fn(f"int8 준비 완료: {dst}")
    return dst


def ensure_dir(log_fn=print) -> Path:
    """int8 모델 디렉터리를 반환. 번들 우선, 없으면(개발) 캐시에 생성."""
    d = _bundled_dir()
    if d is not None:
        return d
    d = _cache_dir()
    if not (d / "model.onnx").exists():
        generate_int8_dir(d, log_fn=log_fn)
    return d


def register(model_dir: Path) -> None:
    """fastembed에 int8 커스텀 모델 등록(멱등). MEAN 풀링 + L2정규화."""
    global _registered
    if _registered:
        return
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType
    with_supported = {m["model"] for m in TextEmbedding.list_supported_models()}
    if INT8_MODEL_ID not in with_supported:
        TextEmbedding.add_custom_model(
            model=INT8_MODEL_ID, pooling=PoolingType.MEAN, normalization=True,
            sources=ModelSource(hf="qdrant/multilingual-e5-large-onnx"),  # 로컬 로드 시 미사용
            dim=1024, model_file="model.onnx", size_in_gb=0.52,
            additional_files=list(_TOKENIZER_FILES),
        )
    _registered = True


def make_text_embedding(log_fn=print):
    """int8 e5-large용 fastembed TextEmbedding 인스턴스(로컬 디렉터리에서 로드)."""
    from fastembed import TextEmbedding
    d = ensure_dir(log_fn=log_fn)
    register(d)
    return TextEmbedding(INT8_MODEL_ID, specific_model_path=str(d))
