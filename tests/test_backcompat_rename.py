"""chatmem→engram→vestige 이름 변경 시 도입한 하위호환(back-compat) 동작 검증.

- 구 ENGRAM_*/CHATMEM_* 환경변수를 신규 VESTIGE_* 로 미러(config.py 임포트 시).
- 우선순위 VESTIGE_ > ENGRAM_ > CHATMEM_.
- 아카이브 import가 레거시 .engram-archive·.chatmem-archive 스냅샷도 함께 읽는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_config_subprocess(overrides: dict[str, str], code: str, tmp_path: Path) -> str:
    """격리된 파이썬 프로세스에서 vestige.config 를 임포트하고 code 출력을 돌려준다.

    부모 환경을 상속(PYTHONPATH 등 유지)하되, 홈 폴더 이전이 절대 발동하지 않도록
    VESTIGE_/CHATMEM_ CONFIG·DATA_DIR 를 tmp 경로로 못박고, 관련 VESTIGE_ 키는 비운다.
    """
    env = dict(os.environ)
    # hermetic: 실행 머신에 있을 수 있는 VESTIGE_/ENGRAM_/CHATMEM_ 키를 모두 제거해
    # overrides 만으로 동작하도록(구 키 누출로 미러 우선순위가 오염되는 것 차단).
    for k in list(env):
        if k.startswith(("VESTIGE_", "ENGRAM_", "CHATMEM_")):
            env.pop(k, None)
    env["VESTIGE_CONFIG"] = str(tmp_path / "missing.env")   # 실재 config 파일 간섭 차단
    env["VESTIGE_DATA_DIR"] = str(tmp_path / "data")        # 이전 로직 스킵(명시 경로)
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env, capture_output=True, text=True, check=True,
    ).stdout


def test_legacy_chatmem_env_is_mirrored_to_vestige(tmp_path: Path):
    """구 CHATMEM_* 셸 환경변수가 신규 VESTIGE_* 로 넘어와 config가 그대로 읽는다."""
    code = (
        "import os, vestige.config as C;"
        "print(os.environ.get('VESTIGE_ENRICH_BACKEND'));"
        "print(C.ENRICH_BACKEND);"
        "print(C.INDEX_INTERVAL_MIN)"
    )
    out = _run_config_subprocess(
        {"CHATMEM_ENRICH_BACKEND": "ollama", "CHATMEM_INDEX_INTERVAL": "42"},
        code, tmp_path,
    ).split()
    assert out[0] == "ollama"      # CHATMEM_ → VESTIGE_ 미러됨
    assert out[1] == "ollama"      # config가 신규 키로 읽음
    assert out[2] == "42"          # 정수형 설정도 미러됨


def test_legacy_engram_env_is_mirrored_to_vestige(tmp_path: Path):
    """구 ENGRAM_* 셸 환경변수가 신규 VESTIGE_* 로 넘어와 config가 그대로 읽는다."""
    code = (
        "import os, vestige.config as C;"
        "print(os.environ.get('VESTIGE_ENRICH_BACKEND'));"
        "print(C.ENRICH_BACKEND)"
    )
    out = _run_config_subprocess(
        {"ENGRAM_ENRICH_BACKEND": "ollama"}, code, tmp_path,
    ).split()
    assert out[0] == "ollama"      # ENGRAM_ → VESTIGE_ 미러됨
    assert out[1] == "ollama"      # config가 신규 키로 읽음


def test_new_vestige_env_takes_precedence_over_legacy(tmp_path: Path):
    """신규 VESTIGE_* 값이 있으면 구 ENGRAM_*/CHATMEM_* 를 덮지 않는다(신규 우선)."""
    code = "import vestige.config as C; print(C.ENRICH_BACKEND)"
    out = _run_config_subprocess(
        {"CHATMEM_ENRICH_BACKEND": "ollama", "VESTIGE_ENRICH_BACKEND": "openai"},
        code, tmp_path,
    ).strip()
    assert out == "openai"


def test_engram_env_wins_over_older_chatmem(tmp_path: Path):
    """둘 다 있으면 더 최근 레거시(ENGRAM_)가 CHATMEM_ 보다 우선한다."""
    code = "import vestige.config as C; print(C.ENRICH_BACKEND)"
    out = _run_config_subprocess(
        {"CHATMEM_ENRICH_BACKEND": "ollama", "ENGRAM_ENRICH_BACKEND": "gemini"},
        code, tmp_path,
    ).strip()
    assert out == "gemini"


import pytest


@pytest.mark.parametrize("legacy_dirname", [".engram-archive", ".chatmem-archive"])
def test_import_reads_legacy_archive_dir(tmp_path: Path, legacy_dirname: str):
    """import_archives가 레거시 .engram-archive·.chatmem-archive 스냅샷도 읽어 들인다."""
    from vestige import archive_sync as A
    from vestige.store import ArchiveDB

    assert legacy_dirname in A.LEGACY_ARCHIVE_DIRNAMES
    projects = tmp_path / "projects"
    legacy = projects / legacy_dirname
    legacy.mkdir(parents=True)
    rec = {
        "t": [1, "sess", "u1", None, "2026-01-01T00:00:00Z", "proj",
              "질문?", "답변.", None, None, None],
        "c": [[0, "chunk text"]],
    }
    (legacy / "otherdev.ndjson").write_text(
        json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    db = ArchiveDB(tmp_path / "archive.db")
    added = A.import_archives(db, projects, my_did="me", log_fn=lambda *_: None)
    assert added == 1
    got = {str(row[0]) for row in db.conn.execute("SELECT id FROM turns")}
    assert got == {"1"}
