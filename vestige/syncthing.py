"""임베디드 Syncthing 관리 (E1): 바이너리 확보 + 헤드리스 spawn + 헬스체크 + Device ID.

재구현이 아니라 성숙한 Syncthing 엔진을 vestige가 대신 운전한다.
- 바이너리 확보 순서: (1) env override (2) 프리즈 번들(sys._MEIPASS) (3) 캐시 (4) GitHub 릴리스 다운로드.
- 동기를 켤 때만 spawn(지연 실행) — 단일 기기 사용자는 오버헤드 0.
- 제어는 REST(127.0.0.1:<gui_port>, X-API-Key)로. GUI 주소·키는 우리가 랜덤 생성해 주입.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import platform
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

from . import config as C
from .proc import NO_WINDOW  # Windows 콘솔 창 깜빡임 방지

SYNCTHING_VERSION = "v2.1.3"   # pin(재현성). 갱신 시 여기만 바꾸면 됨.
# 공유 폴더 ID는 양쪽 기기가 같아야 연결됨 → 고정값 사용(우리가 관리하는 전용 폴더).
DEFAULT_FOLDER_ID = "vestige-claude-projects"
# 이름 변경(chatmem→vestige) 전 폴더 ID. 남아 있으면 startup에서 새 폴더로 이관 후 제거(자가복구).
LEGACY_FOLDER_ID = "chatmem-claude-projects"

logger = logging.getLogger(__name__)
VERSIONING_MAX_AGE_SEC = 31536000   # 삭제·덮어쓰기 이력 보관 기간(기본 1년). 조정 시 여기만.
_BIN_DIR = C.DATA_DIR / "bin"
_HOME_DIR = C.DATA_DIR / "syncthing-home"


def _plat() -> tuple[str, str, str, str]:
    """(os, arch, 확장자, 실행파일명). 릴리스 자산명 규칙에 맞춤."""
    machine = platform.machine().lower()
    arch = "amd64" if machine in ("amd64", "x86_64") else ("arm64" if machine in ("arm64", "aarch64") else machine)
    if sys.platform.startswith("win"):
        return "windows", arch, ".zip", "syncthing.exe"
    if sys.platform == "darwin":
        return "macos", arch, ".zip", "syncthing"       # macOS 자산은 zip
    return "linux", arch, ".tar.gz", "syncthing"          # linux 자산은 tar.gz


def _asset_url(version: str) -> tuple[str, str]:
    osname, arch, ext, _ = _plat()
    name = f"syncthing-{osname}-{arch}-{version}{ext}"
    return f"https://github.com/syncthing/syncthing/releases/download/{version}/{name}", name


# 다운로드 무결성 검증(공급망 방어): 핀된 버전의 공식 SHA-256(릴리스 sha256sum.txt.asc 기준).
# SYNCTHING_VERSION 갱신 시 이 표도 반드시 함께 갱신해야 한다(미등록 자산은 검증 실패로 차단).
_SHA256: dict[str, str] = {
    "syncthing-windows-amd64-v2.1.3.zip": "c0b79cffa6ce5dad5ed41ede86454f3325d13ccac33447a528cb59d65fbc3a21",
    "syncthing-windows-arm64-v2.1.3.zip": "c8a00ff23ce54ca07c5749e40a72c0515150dfcc57f640832fb7eb5d55184675",
    "syncthing-macos-amd64-v2.1.3.zip": "207557c0f708578375be9a286d13078cd709bfccae43d61d004913bb512b10aa",
    "syncthing-macos-arm64-v2.1.3.zip": "e0f0d8df05bf0118c48c6515214a96bf3a3f11dbd115f56c3c0b52251b3f71aa",
    "syncthing-linux-amd64-v2.1.3.tar.gz": "f929eb8e5b72a85543eeeefb2c38f34a68e0c530e70758a2905b78840c76602c",
    "syncthing-linux-arm64-v2.1.3.tar.gz": "a5c046965b590a8de2f8c8c16a0dbf9201d99600b0cafd604040232b603e4586",
}


def _verify_sha256(path: Path, name: str) -> None:
    """다운로드한 아카이브가 핀된 공식 SHA-256과 일치하는지 검증. 불일치·미등록이면 예외."""
    expected = _SHA256.get(name)
    if not expected:
        raise RuntimeError(
            f"Syncthing 체크섬이 등록되지 않은 자산입니다: {name} "
            f"(버전 갱신 시 _SHA256 표를 갱신하세요).")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"Syncthing 다운로드 무결성 검증 실패({name}) — 변조·손상 의심. "
            f"예상 {expected[:12]}… / 실제 {actual[:12]}…")


def binary_path() -> Path:
    """확보돼 있으면 바이너리 경로(없으면 캐시 예정 위치). 존재 여부는 .exists()로 확인."""
    _, _, _, exe = _plat()
    ov = os.environ.get("VESTIGE_SYNCTHING_BIN")
    if ov and Path(ov).exists():
        return Path(ov)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass) / "syncthing" / exe
        if p.exists():
            return p
    return _BIN_DIR / exe


def ensure_binary(version: str = SYNCTHING_VERSION, log_fn=lambda m: None) -> Path:
    """바이너리가 없으면 GitHub 릴리스에서 받아 캐시(_BIN_DIR)에 풀어놓는다."""
    p = binary_path()
    if p.exists():
        return p
    _, _, ext, exe = _plat()
    _BIN_DIR.mkdir(parents=True, exist_ok=True)
    url, name = _asset_url(version)
    log_fn(f"syncthing 다운로드: {name}")
    tmp = _BIN_DIR / name
    urllib.request.urlretrieve(url, tmp)   # noqa: S310 — 고정 GitHub 릴리스 URL
    try:
        _verify_sha256(tmp, name)   # 무결성 검증 — 실패 시 추출하지 않고 임시파일 삭제 후 예외
    except Exception:
        with contextlib.suppress(Exception):
            tmp.unlink()
        raise

    out = _BIN_DIR / exe
    if ext == ".zip":
        with zipfile.ZipFile(tmp) as z:
            member = next((m for m in z.namelist() if m.rsplit("/", 1)[-1] == exe), None)
            if member is None:
                raise RuntimeError(f"'{exe}'를 zip에서 찾지 못함: {tmp}")
            with z.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    else:
        with tarfile.open(tmp) as t:
            member = next((m for m in t.getmembers() if m.name.rsplit("/", 1)[-1] == exe), None)
            src = t.extractfile(member) if member is not None else None
            if src is None:
                raise RuntimeError(f"'{exe}'를 아카이브에서 찾지 못함: {tmp}")
            with open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    with contextlib.suppress(Exception):
        tmp.unlink()
    if not sys.platform.startswith("win"):
        out.chmod(0o755)
    return out


def update_binary(version: str = SYNCTHING_VERSION, log_fn=print) -> Path:
    """캐시된 바이너리를 지우고 지정 버전을 다시 받는다(번들 버전 갱신용).
    실행 중이면 먼저 중지해야 함(파일 락). env override/번들은 건드리지 않음."""
    _, _, _, exe = _plat()
    cached = _BIN_DIR / exe
    try:
        cached.unlink(missing_ok=True)   # 없는 건 무시, 락 등 실제 오류는 표면화
    except OSError as e:
        raise RuntimeError(f"기존 바이너리 삭제 실패(Syncthing 실행 중이면 먼저 중지하세요): {e}") from e
    return ensure_binary(version=version, log_fn=log_fn)


def _free_port(preferred: int = 8384) -> int:
    for port in (preferred, 0):
        try:
            with socket.socket() as s:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
        except OSError:
            continue
    return preferred


def _alive(pid: int) -> bool:
    """POSIX: pid 생존 여부(신호 0). 실패(권한 등)면 살아있다고 보수적으로 간주."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True   # 권한 등 — 존재하나 신호 못 보냄


def _kill_tree(pid: int, log_fn=lambda m: None) -> None:
    """syncthing v2는 감시(부모)+워커(자식) 프로세스로 뜨므로 트리째 종료한다.

    Windows는 taskkill /F(강제)라 한 번에 끝난다. POSIX는 SIGTERM 후 최대 ~2초 생존을
    확인하고, 안 죽으면 SIGKILL로 에스컬레이션한다(구 코드의 kill() 보장을 복원 — 이게 없으면
    SIGTERM을 못 받은 프로세스가 락을 계속 쥐어 다음 기동이 실패한다)."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],  # noqa: S603,S607
                           capture_output=True, timeout=10, creationflags=NO_WINDOW)
            return
        # POSIX: 프로세스 그룹 우선, 안 되면 개별 pid.
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = None
        def _send(sig: int) -> None:
            if pgid is not None:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
        _send(signal.SIGTERM)
        for _ in range(20):        # 최대 ~2초 유예
            if not _alive(pid):
                return
            time.sleep(0.1)
        _send(signal.SIGKILL)      # 여전히 살아있으면 강제 종료
    except ProcessLookupError:
        return                     # 이미 종료됨
    except Exception as e:         # noqa: BLE001
        log_fn(f"프로세스 종료 실패(pid {pid}): {e}")


def _syncthing_pids_for_home(home: Path, log_fn=lambda m: None) -> list[int]:
    """커맨드라인이 우리 home 을 가리키는 모든 syncthing pid(감시·워커·재양육된 고아 전부).

    pid 기준이 아니라 home 기준이라, 부모가 죽고 워커만 다른 부모로 재양육돼 살아남은
    고아까지 확실히 잡는다(v2의 감시+워커 구조 때문). 열거 자체가 실패하면(권한·명령 없음 등)
    빈 리스트를 반환하되 log_fn 으로 남긴다 — '고아 없음'과 '조회 실패'를 로그로 구분한다."""
    home_s = str(home).lower()
    pids: list[int] = []
    try:
        if sys.platform.startswith("win"):
            # 한글 등 비ASCII 홈 경로가 CommandLine에 포함될 수 있어 UTF-8로 강제(콘솔 코드페이지
            # 불일치로 매칭이 조용히 실패하는 것 방지). encoding 도 명시.
            ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                  "Get-CimInstance Win32_Process -Filter \"Name='syncthing.exe'\" | "
                  "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],  # noqa: S603,S607
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=15, creationflags=NO_WINDOW)
            for ln in (out.stdout or "").splitlines():
                pid_s, _, cmd = ln.partition("\t")
                if home_s in cmd.lower():
                    with contextlib.suppress(ValueError):
                        pids.append(int(pid_s.strip()))
        else:
            out = subprocess.run(["ps", "-eo", "pid=,args="],  # noqa: S603,S607
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=10)
            for ln in (out.stdout or "").splitlines():
                low = ln.lower()
                if "syncthing" in low and home_s in low:
                    with contextlib.suppress(ValueError, IndexError):
                        pids.append(int(ln.split(None, 1)[0]))
    except Exception as e:  # noqa: BLE001
        log_fn(f"syncthing 프로세스 목록 조회 실패(고아 회수 불가할 수 있음): {e}")
    return pids


def _reap_orphan(home: Path, log_fn=lambda m: None) -> None:
    """기동 전, 우리 home 을 쓰는 기존 syncthing을 모두 회수해 락을 확실히 푼다.

    앱/백엔드가 재시작·크래시되면 예전에 spawn한 syncthing(특히 재양육된 워커)이 추적 핸들을
    잃은 채 살아남아 home 락을 계속 쥔다 → 새 기동이 'Failed to acquire lock'으로 즉시 실패한다.
    우리는 단일 인스턴스만 운영하므로, 우리 home 을 쓰는 syncthing은 곧 이전 잔여물 → 전부 종료."""
    pids = _syncthing_pids_for_home(home, log_fn)
    if pids:
        log_fn(f"이전 Syncthing 프로세스 {len(pids)}개 정리 후 재기동")
        for pid in pids:
            _kill_tree(pid, log_fn)


def log_error(home: Path | None = None) -> str | None:
    """syncthing.log 마지막부에서 실패 원인(ERR/락 실패)을 뽑아 반환. 없으면 None."""
    home = Path(home) if home is not None else _HOME_DIR
    try:
        lines = (home / "syncthing.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return None
    for ln in reversed(lines[-60:]):
        if "Failed to acquire lock" in ln:
            return "다른 Syncthing 인스턴스가 이미 실행 중이었어요(락 충돌) — 자동 정리 후 다시 시도해 주세요."
        if " ERR " in ln:
            return ln.split(" ERR ", 1)[-1].strip()[:200]
    return None


class Syncthing:
    """임베디드 syncthing 프로세스 핸들 + REST 헬퍼."""

    def __init__(self, gui_port: int | None = None, apikey: str | None = None, home: Path | None = None):
        self.gui_port = gui_port or _free_port()
        self.apikey = apikey or secrets.token_hex(16)
        self.home = Path(home) if home is not None else _HOME_DIR
        self.proc: subprocess.Popen | None = None

    @property
    def gui_address(self) -> str:
        return f"127.0.0.1:{self.gui_port}"

    def start(self, log_fn=lambda m: None) -> None:
        exe = ensure_binary(log_fn=log_fn)
        self.home.mkdir(parents=True, exist_ok=True)
        _reap_orphan(self.home, log_fn)   # 재시작 후 남은 고아 회수 → '락 획득 실패' 방지
        env = os.environ.copy()
        env["STGUIADDRESS"] = self.gui_address      # GUI/REST 주소
        env["STGUIAPIKEY"] = self.apikey            # REST 인증 키(우리가 주입)
        env["STNORESTART"] = "1"                     # 자체 재시작 감시 끔(우리가 관리)
        env["STNOUPGRADE"] = "1"                     # 자동 업그레이드 끔(번들 버전 고정)
        env["STNODEFAULTFOLDER"] = "1"               # 기본 ~/Sync 폴더 자동생성 안 함
        args = [str(exe), "serve", "--home", str(self.home), "--no-browser"]
        kwargs: dict = {}
        if not sys.platform.startswith("win"):
            kwargs["start_new_session"] = True       # 프로세스 그룹 분리 → 트리 종료 가능(posix)
        elif NO_WINDOW:
            kwargs["creationflags"] = NO_WINDOW      # Windows: syncthing 콘솔 창 안 뜨게
        self.proc = subprocess.Popen(  # noqa: S603
            args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs,
        )

    def stop(self, log_fn=lambda m: None) -> None:
        # 감시(부모)를 먼저 terminate 하면 워커(자식)가 재양육돼 살아남아 락을 계속 쥔다.
        # → home 을 쓰는 syncthing을 트리째 모두 종료(SIGKILL 에스컬레이션 포함)해 워커까지 회수.
        for pid in _syncthing_pids_for_home(self.home, log_fn):
            _kill_tree(pid, log_fn)
        # 혹시 열거에서 누락돼도 우리 핸들은 확실히 — 단, 아직 살아있을 때만(죽은 핸들의 pid가
        # OS에 의해 무관 프로세스로 재할당됐을 수 있으므로 poll() 로 생존 확인 후 종료).
        if self.proc is not None and self.proc.poll() is None:
            _kill_tree(self.proc.pid, log_fn)
            with contextlib.suppress(Exception):
                self.proc.wait(timeout=5)

    def _req(self, method: str, path: str, body=None, timeout: float = 8.0):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-API-Key": self.apikey}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://{self.gui_address}{path}", data=data,
                                     method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — localhost
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}

    def _get(self, path: str, timeout: float = 5.0):
        return self._req("GET", path, timeout=timeout)

    # ── E2: 설정 브리지(기기 추가 / 폴더 공유 / 상태) ──────────────────
    def add_device(self, device_id: str, name: str = "") -> None:
        """상대 기기를 추가(upsert). device_id는 상대의 Syncthing Device ID."""
        self._req("PUT", f"/rest/config/devices/{device_id}",
                  {"deviceID": device_id, "name": name or device_id[:7]})

    def share_projects(self, projects_dir, remote_ids: list[str],
                       folder_id: str = DEFAULT_FOLDER_ID, label: str = "Claude projects") -> None:
        """~/.claude/projects 를 지정 folder_id로 등록하고 이 기기+상대들과 공유(upsert)."""
        my = self.device_id()
        # 내 기기 + 상대들(빈 값·중복 제거, 순서 유지). my가 선두라 self 중복도 자동 제외.
        ids: list[str] = []
        for d in ([my] if my else []) + list(remote_ids):
            if d and d not in ids:
                ids.append(d)
        body = {
            "id": folder_id, "label": label, "path": str(projects_dir),
            "type": "sendreceive",
            "devices": [{"deviceID": d} for d in ids],
            # 삭제·덮어쓰기 이력 보존(실수 대비).
            "versioning": {"type": "staggered", "params": {"maxAge": str(VERSIONING_MAX_AGE_SEC)}},
        }
        self._req("PUT", f"/rest/config/folders/{folder_id}", body)

    def remove_folder(self, folder_id: str) -> bool:
        """공유 폴더 설정 하나 제거. 원본 파일(.claude/projects)은 건드리지 않는다. 성공 시 True."""
        try:
            self._req("DELETE", f"/rest/config/folders/{folder_id}")
            return True
        except Exception as ex:  # noqa: BLE001
            logger.warning("syncthing 폴더 제거 실패(%s): %r", folder_id, ex)
            return False

    def remove_device(self, device_id: str, projects_dir=None) -> bool:
        """페어링 해제: 공유 폴더에서 그 기기를 빼고 기기 등록을 제거. 원본 파일은 안 건드림.

        기기를 리셋해 Device ID가 바뀌면 옛 ID로의 페어링이 유령으로 남아 '전송 중 0%'에 갇힌다.
        이 잔재를 떼는 용도. 성공 시 True.
        """
        # 1) 공유 폴더 device 목록에서 대상 제거(공유 중단). 실패해도 2)의 device 삭제는 시도.
        if projects_dir is not None:
            try:
                cfg = self.config()
                my = self.device_id()
                folder = next((f for f in cfg.get("folders", []) if f.get("id") == DEFAULT_FOLDER_ID), None)
                if folder:
                    peers = [d.get("deviceID") for d in folder.get("devices", [])
                             if d.get("deviceID") and d.get("deviceID") not in (my, device_id)]
                    self.share_projects(projects_dir, peers)   # 대상 뺀 나머지로 재공유
            except Exception as ex:  # noqa: BLE001
                logger.warning("기기 해제: 폴더 공유 갱신 실패(%s): %r", device_id, ex)
        # 2) 기기 등록 제거
        try:
            self._req("DELETE", f"/rest/config/devices/{device_id}")
            return True
        except Exception as ex:  # noqa: BLE001
            logger.warning("기기 해제: device 삭제 실패(%s): %r", device_id, ex)
            return False

    def migrate_legacy_folder(self, projects_dir) -> bool:
        """rename(chatmem→vestige) 잔재 정리 — startup 자가복구.

        옛 폴더 id(`chatmem-claude-projects`)가 남아 있으면, 그 폴더에 붙어 있던 상대 기기를
        현재 폴더(`vestige-claude-projects`)로 옮기고 옛 폴더를 제거한다. 두 폴더가 같은 경로
        (.claude/projects)를 물면 Syncthing이 충돌로 한쪽을 에러 처리해 동기화가 0%에서 막히므로
        필수. 홈·아카이브·스케줄러 레거시 정리와 동일한 back-compat 정책.

        안전: 상대 기기를 새 폴더로 **옮기는 데 성공했을 때만** 옛 폴더를 지운다. 이관이 실패하면
        옛 폴더를 남겨 다음 기동에 재시도한다(병합 안 된 채 삭제해 페어링을 유실하지 않게).
        반환: 이관+제거까지 끝냈으면 True, 잔재 없음/실패면 False.
        """
        try:
            cfg = self.config()
        except Exception as ex:  # noqa: BLE001 — REST 미준비 등: 다음 기동에 재시도
            logger.warning("syncthing 레거시 폴더 정리: 설정 조회 실패, 다음 기동 재시도: %r", ex)
            return False
        folders = cfg.get("folders", [])
        legacy = next((f for f in folders if f.get("id") == LEGACY_FOLDER_ID), None)
        if legacy is None:
            return False   # 잔재 없음 — 공개 신규 설치는 여기서 no-op
        my = self.device_id()
        # 옛 폴더 + 새 폴더에 붙어 있던 상대 기기(나 제외)를 합쳐 새 폴더로 이관(중복 제거).
        peers: list[str] = []
        for f in (legacy, next((x for x in folders if x.get("id") == DEFAULT_FOLDER_ID), None)):
            for d in (f or {}).get("devices", []):
                did = d.get("deviceID")
                if did and did != my and did not in peers:
                    peers.append(did)
        try:
            self.share_projects(projects_dir, peers)   # 새 폴더에 상대 병합(upsert)
        except Exception as ex:  # noqa: BLE001 — 이관 실패: 옛 폴더 보존 → 다음 기동 재시도
            logger.warning("syncthing 레거시 폴더 정리: 상대 기기 이관 실패, 옛 폴더 보존(재시도): %r", ex)
            return False
        if not self.remove_folder(LEGACY_FOLDER_ID):   # 이관 성공 후에만 옛 폴더 제거
            return False                                # 삭제 실패: 옛 폴더 남음 → 다음 기동 재시도(로깅은 remove_folder)
        logger.info("syncthing 레거시 폴더(%s) 정리 완료 — 상대 %d대 이관", LEGACY_FOLDER_ID, len(peers))
        return True

    def config(self) -> dict:
        return self._get("/rest/config")

    def connections(self) -> dict:
        return self._get("/rest/system/connections")

    def folder_status(self, folder_id: str = DEFAULT_FOLDER_ID) -> dict:
        return self._get(f"/rest/db/status?folder={folder_id}")

    def folder_sync(self, folder_id: str = DEFAULT_FOLDER_ID) -> dict:
        """공유 폴더의 동기 상태 요약(이 기기 기준).

        state: idle(최신)/scanning(스캔 중)/syncing(동기화 중)/error 등 syncthing 원상태.
        completion: 로컬이 글로벌 대비 몇 % 받았는지(0~100). need_*: 아직 받아야 할 양.
        """
        s = self.folder_status(folder_id)
        gb = int(s.get("globalBytes") or 0)
        nb = int(s.get("needBytes") or 0)
        need_items = sum(int(s.get(k) or 0) for k in
                         ("needFiles", "needDirectories", "needSymlinks", "needDeletes"))
        completion = 100.0 if gb <= 0 else max(0.0, min(100.0, round((gb - nb) / gb * 100, 1)))
        return {"state": s.get("state") or "idle", "completion": completion,
                "need_items": need_items, "need_bytes": nb, "global_bytes": gb}

    def device_completion(self, device_id: str, folder_id: str = DEFAULT_FOLDER_ID) -> float | None:
        """상대 기기가 이 폴더를 몇 % 받았는지(우리 관점). 전송 방향 진척 판단용.

        folder_sync.completion은 '내가 받은 비율'(수신)이라, 이것과 합쳐야
        '양쪽 다 최신'(진짜 수렴)을 판정할 수 있다. None=조회 실패.
        """
        try:
            c = self._get(f"/rest/db/completion?folder={folder_id}&device={device_id}")
            return float(c.get("completion", 0.0))
        except Exception:  # noqa: BLE001
            return None

    def pair_summary(self) -> dict:
        """UI용 요약: 내 Device ID / 등록 기기 / 공유 폴더 / 연결 상태 / 동기 진행."""
        my = self.device_id()   # REST 왕복 1회로 캐시(아래 필터에서 재사용)
        cfg = self.config()
        conns = self.connections().get("connections", {})
        folders = cfg.get("folders", [])
        # 우리가 관리하는 폴더가 설정돼 있을 때만 동기 상태 조회(없으면 None → UI에서 안내)
        managed = any(f.get("id") == DEFAULT_FOLDER_ID for f in folders)
        sync = None
        if managed:
            with contextlib.suppress(Exception):
                sync = self.folder_sync(DEFAULT_FOLDER_ID)
        # 연결된 상대들이 내 폴더를 얼마나 받았는지(전송 방향) → '진짜 최신' 판정용.
        if sync is not None:
            remotes = []
            for d in cfg.get("devices", []):
                did = d.get("deviceID")
                if did and did != my and conns.get(did, {}).get("connected"):
                    v = self.device_completion(did, DEFAULT_FOLDER_ID)
                    if v is not None:
                        remotes.append(v)
            sync["peers_connected"] = len(remotes)
            sync["remote_complete"] = round(min(remotes), 1) if remotes else None
        return {
            "my_id": my,
            "devices": [{"id": d.get("deviceID"), "name": d.get("name"),
                         "connected": bool(conns.get(d.get("deviceID"), {}).get("connected"))}
                        for d in cfg.get("devices", []) if d.get("deviceID") != my],
            "folders": [{"id": f.get("id"), "path": f.get("path"),
                         "shared_with": [x.get("deviceID") for x in f.get("devices", [])]}
                        for f in folders],
            "sync": sync,
        }

    def wait_ready(self, timeout: float = 40.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                self._get("/rest/system/ping", timeout=2.0)
                return True
            except Exception:  # noqa: BLE001
                if self.proc and self.proc.poll() is not None:
                    return False   # 프로세스가 죽음
                time.sleep(0.5)
        return False

    def device_id(self) -> str | None:
        try:
            return self._get("/rest/system/status").get("myID")
        except Exception:  # noqa: BLE001
            return None


def self_check(log_fn=print) -> dict:
    """E1 검증: 바이너리 확보 → spawn → ready → Device ID → 종료. 결과 dict 반환."""
    st = Syncthing()
    log_fn(f"바이너리 확인/다운로드 (버전 {SYNCTHING_VERSION})…")
    exe = ensure_binary(log_fn=log_fn)
    log_fn(f"바이너리: {exe}")
    st.start(log_fn=log_fn)
    log_fn(f"기동(gui {st.gui_address}) — 준비 대기…")
    ready = st.wait_ready()
    dev = st.device_id() if ready else None
    if ready:
        log_fn(f"준비 완료. Device ID: {dev}")
    else:
        log_fn("준비 실패(프로세스가 뜨지 않았거나 REST 응답 없음)")
    st.stop()
    log_fn("종료함")
    return {"binary": str(exe), "ready": ready, "device_id": dev, "gui": st.gui_address}
