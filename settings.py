"""应用设置与开机自启。"""

from __future__ import annotations

import json
import sys
import winreg
from pathlib import Path

APP_REG_NAME = "SleepPlan"

DEFAULTS = {
    "minimize_to_tray_on_close": True,
    "autostart": True,
    "window_geometry": "",
}


def settings_path() -> Path:
    base = Path.home() / ".sleep_plan"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    if not path.exists():
        data = dict(DEFAULTS)
        save_settings(data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = dict(DEFAULTS)
    for key, val in DEFAULTS.items():
        data.setdefault(key, val)
    return data


def save_settings(data: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update(data)
    settings_path().write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def application_command() -> str:
    """写入「运行」注册表项用的启动命令。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    script = (Path(__file__).resolve().parent / "main.py").resolve()
    exe = Path(sys.executable).resolve()
    return f'"{exe}" "{script}"'


def set_autostart(enabled: bool) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, application_command())
        else:
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass