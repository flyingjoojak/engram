"""빌드 전용: int8 e5-large 모델 디렉터리를 생성한다(PyInstaller가 --add-data로 번들).

fp32 e5-large를 fastembed로 받아 동적 int8 양자화 → <dst>/model.onnx + 토크나이저.
사전: pip install ".[all]" onnx (onnxruntime.quantization 사용). frozen exe 런타임엔 불필요.
"""
import sys
from pathlib import Path

# Windows CI 등 콘솔 기본 인코딩(cp1252/cp949)이 비ASCII 로그를 못 써서 UnicodeEncodeError 나는 것 방지.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 — 재설정 불가 환경은 무시
        pass

from vestige.int8_model import generate_int8_dir

dst = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("packaging/build/e5int8")
generate_int8_dir(dst)
print(f"OK: {dst.resolve()}")
