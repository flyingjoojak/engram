"""크로스플랫폼 스케줄러 등록: 10분 증분 인덱싱 + 야간 정제 + 세션 동기화 충돌 해소.

- Windows: schtasks (vestige-index / vestige-enrich / vestige-sync)
- macOS:   launchd (~/Library/LaunchAgents/com.vestige.*.plist)
- Linux:   cron (crontab 관리 블록)

스케줄이 실행하는 명령은 `<python> -m vestige index|enrich|sync --once` (콘솔 PATH 불필요).
index/enrich 커맨드가 내부에서 절전방지·로그·메모리가드를 이미 처리하고,
sync --once 는 헤드리스에서 Syncthing 충돌 사본을 주기적으로 해소(웹앱 안 켜도).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 자동 축적 주기 — config(환경변수/config.env)에서 조정. 설정 변경 후 재등록하면 반영.
from . import config as _C  # noqa: E402
from .proc import NO_WINDOW  # 콘솔 창 깜빡임 방지(Windows)


def _timing() -> tuple[int, int, int]:
    """(인덱싱 주기 분, 정제 시 HH, 정제 MM). config를 매 호출 시 재평가."""
    interval = _C.INDEX_INTERVAL_MIN
    try:
        hh, mm = (_C.ENRICH_TIME or "04:00").split(":")
        return interval, int(hh), int(mm)
    except (ValueError, AttributeError):
        return interval, 4, 0


INDEX_EVERY_MIN, ENRICH_HOUR, ENRICH_MIN = _timing()

_WIN_INDEX = "vestige-index"
_WIN_ENRICH = "vestige-enrich"
_WIN_SYNC = "vestige-sync"
_CRON_BEGIN = "# >>> vestige >>>"
_CRON_END = "# <<< vestige <<<"

# 레거시(이름 변경 전) 스케줄 식별자 — 업그레이드 시 구 작업/plist/cron블록이 고아로
# 남지 않도록 uninstall 과 install(재등록 전 정리)에서 best-effort로 함께 제거한다.
_LEGACY_WIN = ("chatmem-index", "chatmem-enrich", "chatmem-sync")
_LEGACY_MAC = ("com.chatmem.index", "com.chatmem.enrich", "com.chatmem.sync")
_LEGACY_CRON = ("# >>> chatmem >>>", "# <<< chatmem <<<")


def _py() -> str:
    # Windows 스케줄 작업은 콘솔 창이 번쩍이지 않게 pythonw.exe 사용(없으면 python).
    exe = sys.executable or "python"
    if sys.platform.startswith("win") and exe.lower().endswith("python.exe"):
        cand = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def _index_cmd() -> list[str]:
    return [_py(), "-m", "vestige", "index"]


def _enrich_cmd() -> list[str]:
    return [_py(), "-m", "vestige", "enrich"]


def _sync_cmd() -> list[str]:
    # 헤드리스에서 Syncthing 충돌 사본을 주기적으로 해소(웹앱 안 켜도). 색인은 index 작업이 담당.
    return [_py(), "-m", "vestige", "sync", "--once"]


# ---------- Windows (schtasks) ----------
def _win_install(dry_run: bool) -> list[str]:
    py = _py()
    tasks = [
        (_WIN_INDEX, f'"{py}" -m vestige index',
         ["/SC", "MINUTE", "/MO", str(INDEX_EVERY_MIN)]),
        (_WIN_ENRICH, f'"{py}" -m vestige enrich',
         ["/SC", "DAILY", "/ST", f"{ENRICH_HOUR:02d}:{ENRICH_MIN:02d}"]),
        (_WIN_SYNC, f'"{py}" -m vestige sync --once',
         ["/SC", "MINUTE", "/MO", str(INDEX_EVERY_MIN)]),
    ]
    lines = []
    for name, tr, sched in tasks:
        cmd = ["schtasks", "/Create", "/TN", name, "/TR", tr, *sched, "/F"]
        lines.append(" ".join(cmd))
        if not dry_run:
            subprocess.run(cmd, check=True, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    return lines


def _win_uninstall(dry_run: bool) -> list[str]:
    lines = []
    # 신규 + 레거시(chatmem-*) 작업 모두 제거(구 작업 고아 방지). 없으면 조용히 무시.
    for name in (_WIN_INDEX, _WIN_ENRICH, _WIN_SYNC, *_LEGACY_WIN):
        cmd = ["schtasks", "/Delete", "/TN", name, "/F"]
        lines.append(" ".join(cmd))
        if not dry_run:
            subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)  # 없으면 무시
    return lines


def _win_status() -> str:
    out = []
    for name in (_WIN_INDEX, _WIN_ENRICH, _WIN_SYNC):
        r = subprocess.run(["schtasks", "/Query", "/TN", name],
                           capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
        out.append(f"{name}: {'등록됨' if r.returncode == 0 else '없음'}")
    return " · ".join(out)


# ---------- macOS (launchd) ----------
def _mac_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _mac_plist(label: str, args: list[str], *, interval: int | None = None,
               hour: int | None = None, minute: int | None = None) -> str:
    prog = "".join(f"    <string>{a}</string>\n" for a in args)
    if interval is not None:
        when = f"  <key>StartInterval</key>\n  <integer>{interval}</integer>\n"
    else:
        when = ("  <key>StartCalendarInterval</key>\n  <dict>\n"
                f"    <key>Hour</key><integer>{hour}</integer>\n"
                f"    <key>Minute</key><integer>{minute}</integer>\n  </dict>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            f'  <key>Label</key>\n  <string>{label}</string>\n'
            f'  <key>ProgramArguments</key>\n  <array>\n{prog}  </array>\n'
            f'{when}</dict>\n</plist>\n')


def _mac_jobs():
    return [
        ("com.vestige.index", _index_cmd(), {"interval": INDEX_EVERY_MIN * 60}),
        ("com.vestige.enrich", _enrich_cmd(), {"hour": ENRICH_HOUR, "minute": ENRICH_MIN}),
        ("com.vestige.sync", _sync_cmd(), {"interval": INDEX_EVERY_MIN * 60}),
    ]


def _mac_install(dry_run: bool) -> list[str]:
    d = _mac_dir()
    lines = []
    for label, args, when in _mac_jobs():
        path = d / f"{label}.plist"
        lines.append(f"write {path} + launchctl load -w")
        if not dry_run:
            d.mkdir(parents=True, exist_ok=True)
            path.write_text(_mac_plist(label, args, **when), encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
            subprocess.run(["launchctl", "load", "-w", str(path)], capture_output=True, text=True)
    return lines


def _mac_uninstall(dry_run: bool) -> list[str]:
    d = _mac_dir()
    lines = []
    # 신규 라벨 + 레거시(com.chatmem.*) plist 모두 제거(구 LaunchAgent 고아 방지).
    labels = [lbl for lbl, _, _w in _mac_jobs()] + list(_LEGACY_MAC)
    for label in labels:
        path = d / f"{label}.plist"
        lines.append(f"launchctl unload + rm {path}")
        if not dry_run:
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
            path.unlink(missing_ok=True)
    return lines


def _mac_status() -> str:
    return " · ".join(
        f"{label}: {'있음' if (_mac_dir() / f'{label}.plist').exists() else '없음'}"
        for label, _, _w in _mac_jobs())


# ---------- Linux (cron) ----------
def _cron_block() -> str:
    idx = " ".join(_index_cmd())
    enr = " ".join(_enrich_cmd())
    syn = " ".join(_sync_cmd())
    return (f"{_CRON_BEGIN}\n"
            f"*/{INDEX_EVERY_MIN} * * * * {idx}\n"
            f"{ENRICH_MIN} {ENRICH_HOUR} * * * {enr}\n"
            f"*/{INDEX_EVERY_MIN} * * * * {syn}\n"
            f"{_CRON_END}\n")


def _cron_current() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _cron_strip(text: str) -> str:
    # 신규 마커 + 레거시(chatmem) 마커 블록 모두 제거 → 재등록/제거 시 구 블록 고아 방지.
    begins = {_CRON_BEGIN, _LEGACY_CRON[0]}
    ends = {_CRON_END, _LEGACY_CRON[1]}
    out, skip = [], False
    for line in text.splitlines():
        if line.strip() in begins:
            skip = True
            continue
        if line.strip() in ends:
            skip = False
            continue
        if not skip:
            out.append(line)
    return "\n".join(out).strip("\n")


def _cron_write(text: str) -> None:
    subprocess.run(["crontab", "-"], input=text if text.endswith("\n") else text + "\n",
                   text=True, check=True)


def _linux_install(dry_run: bool) -> list[str]:
    new = _cron_strip(_cron_current())
    new = (new + "\n\n" if new else "") + _cron_block()
    if not dry_run:
        _cron_write(new)
    return [f"crontab 관리블록 등록:\n{_cron_block().rstrip()}"]


def _linux_uninstall(dry_run: bool) -> list[str]:
    new = _cron_strip(_cron_current())
    if not dry_run:
        _cron_write(new + "\n" if new else "\n")
    return ["crontab 관리블록 제거"]


def _linux_status() -> str:
    return "cron: " + ("등록됨" if _CRON_BEGIN in _cron_current() else "없음")


# ---------- 디스패치 ----------
def _platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def install(dry_run: bool = False) -> list[str]:
    # 최신 설정(시각/간격) 반영 후 등록.
    global INDEX_EVERY_MIN, ENRICH_HOUR, ENRICH_MIN
    INDEX_EVERY_MIN, ENRICH_HOUR, ENRICH_MIN = _timing()
    return {"windows": _win_install, "macos": _mac_install,
            "linux": _linux_install}[_platform()](dry_run)


def uninstall(dry_run: bool = False) -> list[str]:
    return {"windows": _win_uninstall, "macos": _mac_uninstall,
            "linux": _linux_uninstall}[_platform()](dry_run)


def status() -> str:
    return {"windows": _win_status, "macos": _mac_status,
            "linux": _linux_status}[_platform()]()


def index_scheduled() -> bool:
    """OS 레벨 색인 태스크(vestige-index)가 등록돼 있는지 값싸게 확인.
    웹앱의 인프로세스 자동 색인 루프가 이 태스크와 이중으로 돌지 않게 판정하는 용도."""
    plat = _platform()
    try:
        if plat == "windows":
            r = subprocess.run(["schtasks", "/Query", "/TN", _WIN_INDEX],
                               capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
            return r.returncode == 0
        if plat == "macos":
            return (_mac_dir() / "com.vestige.index.plist").exists()
        return _CRON_BEGIN in _cron_current()   # linux: 관리블록 존재 = index/sync cron 등록됨
    except Exception:
        return False   # 확인 실패 시 인프로세스 루프가 담당(색인이 아예 안 도는 것보다 안전)
