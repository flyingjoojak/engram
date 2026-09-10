"""subprocess 실행 시 Windows 콘솔 창 깜빡임 방지.

PyInstaller --noconsole(windowed) 프리즌 앱은 자체 콘솔이 없어, subprocess가 콘솔
프로그램(schtasks·powershell·syncthing 등)을 부를 때마다 검은 cmd 창이 잠깐 떴다
사라진다(사용자 불안). CREATE_NO_WINDOW 플래그로 그 창 생성을 막는다.
"""
from __future__ import annotations

import subprocess
import sys

# Windows에서만 유효한 플래그. 다른 OS에선 0(=기본, 무해)이라 어디서든 그대로 넘길 수 있다.
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


def hidden(**kwargs):
    """subprocess.run/Popen kwargs에 Windows 콘솔 숨김 플래그를 병합해 반환."""
    if NO_WINDOW:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW
    return kwargs
