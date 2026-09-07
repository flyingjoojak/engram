#!/usr/bin/env bash
# engram 백엔드 사이드카 빌드 (Electron 데스크탑 앱에 동봉).
#
# FastAPI + fastembed(onnxruntime·tokenizers 네이티브)를 단일 폴더 exe로 번들한다.
# 기본·권장 모델(int8 e5-large, 0.52GB 디스크 / 로딩 시 약 2GB RAM)은 아래에서 생성해 동봉 → 설치 즉시 오프라인 동작.
#   (선택 옵션인 MiniLM 등 다른 모델만 첫 사용 시 다운로드/캐시)
# 결과: dist/engram-backend/  (onedir; Electron이 이 폴더를 resources로 포함)
#
# 사전: pip install ".[all]" pyinstaller onnx
#   ("onnx"는 아래 make_int8(양자화)에만 필요. 이미 생성된 e5int8 폴더가 있으면 불필요)
# 크로스플랫폼: 각 OS에서 그 OS로 실행해야 함(Win→.exe, mac→mach-o, linux→elf).
set -e
cd "$(dirname "$0")/.."

# 프론트가 빌드돼 있어야 함(백엔드가 이 dist를 / 에서 서빙). 없으면 빌드.
if [ ! -f frontend/dist/index.html ]; then
  echo "frontend 빌드 중…"; (cd frontend && npm run build)
fi

# --add-data 경로 구분자: Windows=';', Unix=':'
SEP=":"
case "${OS:-}${OSTYPE:-}" in *Windows*|*msys*|*cygwin*) SEP=";" ;; esac

# 기본·권장 모델(int8 e5-large, 0.52GB 디스크 / 로딩 시 약 2GB RAM)을 생성해 동봉 → 설치 즉시 오프라인 동작(첫 실행 다운로드 없음).
if [ ! -f packaging/build/e5int8/model.onnx ]; then
  echo "int8 e5-large 생성 중…"; python packaging/make_int8.py packaging/build/e5int8
fi

pyinstaller --noconfirm --onedir --name engram-backend \
  --noconsole \
  --paths . \
  --add-data "packaging/build/e5int8${SEP}e5int8" \
  --collect-all fastembed \
  --collect-all onnxruntime \
  --collect-all tokenizers \
  --collect-all huggingface_hub \
  --collect-all uvicorn \
  --collect-all sqlite_vec \
  --collect-submodules mcp.server \
  --collect-submodules mcp.shared \
  --collect-submodules engram \
  --add-data "frontend/dist${SEP}frontend/dist" \
  packaging/backend_entry.py

echo ""
echo "완료: dist/engram-backend/engram-backend.exe  (인자=포트, 예: engram-backend.exe 8765)"
