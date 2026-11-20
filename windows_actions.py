"""Windows 电源与锁屏操作。"""

import ctypes
import subprocess
import sys


def _is_windows() -> bool:
    return sys.platform == "win32"


def lock_screen() -> None:
    if not _is_windows():
        raise OSError("仅支持 Windows")
    ctypes.windll.user32.LockWorkStation()


def sleep() -> None:
    if not _is_windows():
        raise OSError("仅支持 Windows")
    # SetSuspendState(bForce, bWakeup, bDisable)
    ctypes.windll.powrprof.SetSuspendState(0, 1, 0)


def shutdown(delay_seconds: int = 0) -> None:
    if not _is_windows():
        raise OSError("仅支持 Windows")
    subprocess.run(
        ["shutdown", "/s", "/f", "/t", str(max(0, delay_seconds))],
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def restart(delay_seconds: int = 0) -> None:
    if not _is_windows():
        raise OSError("仅支持 Windows")
    subprocess.run(
        ["shutdown", "/r", "/f", "/t", str(max(0, delay_seconds))],
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def cancel_shutdown() -> None:
    if not _is_windows():
        return
    subprocess.run(
        ["shutdown", "/a"],
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


ACTIONS = {
    "sleep": ("睡眠", sleep),
    "lock": ("锁屏", lock_screen),
    "shutdown": ("关机", lambda: shutdown(0)),
    "restart": ("重启", lambda: restart(0)),
}