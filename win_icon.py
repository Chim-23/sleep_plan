"""Windows 高 DPI 图标与标题栏/任务栏高清图标。"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

if sys.platform != "win32":
    raise ImportError("win_icon 仅用于 Windows")

user32 = ctypes.windll.user32
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x8000
IMAGE_ICON = 1
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
GCLP_HICON = -14
GCLP_HICONSM = -34


def enable_dpi_awareness() -> None:
    """避免系统把 16×16 图标放大导致发糊。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def _hwnd_for_tk(root) -> int:
    root.update_idletasks()
    wid = int(root.winfo_id())
    if not wid:
        return 0
    # CustomTkinter / Tk 都取顶层窗口，避免绑到子控件导致图标仍发糊
    GA_ROOT = 2
    hwnd = user32.GetAncestor(wid, GA_ROOT)
    return int(hwnd) if hwnd else wid


def _load_icon(path: Path, cx: int, cy: int) -> int | None:
    h = user32.LoadImageW(
        None,
        str(path),
        IMAGE_ICON,
        cx,
        cy,
        LR_LOADFROMFILE,
    )
    return int(h) if h else None


def apply_hd_window_icons(root, ico_path: Path) -> None:
    """按当前 DPI 的系统尺寸设置大/小图标（标题栏 + 任务栏）。"""
    if not ico_path.is_file():
        return

    hwnd = _hwnd_for_tk(root)
    if not hwnd:
        return

    cx_sm = user32.GetSystemMetrics(49)
    cy_sm = user32.GetSystemMetrics(50)
    cx_big = user32.GetSystemMetrics(11)
    cy_big = user32.GetSystemMetrics(12)

    # Win11 任务栏偏大时可再设一组 32 的大图标
    sizes = (
        (ICON_SMALL, cx_sm, cy_sm),
        (ICON_BIG, cx_big, cy_big),
        (ICON_BIG, 32, 32),
        (ICON_SMALL, 20, 20),
    )
    seen: set[tuple[int, int]] = set()
    for kind, cx, cy in sizes:
        if (cx, cy) in seen:
            continue
        seen.add((cx, cy))
        hicon = _load_icon(ico_path, cx, cy)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)

    hicon_big = user32.LoadImageW(
        None,
        str(ico_path),
        IMAGE_ICON,
        0,
        0,
        LR_LOADFROMFILE | LR_DEFAULTSIZE,
    )
    if hicon_big:
        hicon_big = int(hicon_big)
        try:
            ctypes.windll.user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
            hicon_sm = _load_icon(ico_path, cx_sm, cy_sm)
            if hicon_sm:
                ctypes.windll.user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_sm)
        except Exception:
            pass