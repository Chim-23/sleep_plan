"""系统托盘。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PIL import Image

try:
    import pystray
except ImportError:  # pragma: no cover
    pystray = None  # type: ignore


class TrayController:
    def __init__(
        self,
        icon_path: Path,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._icon_path = icon_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return pystray is not None and self._icon_path.is_file()

    def start(self) -> None:
        if not self.available or self._icon is not None:
            return

        image = Image.open(self._icon_path).convert("RGBA")
        if image.size[0] < 128:
            image = image.resize((128, 128), Image.Resampling.LANCZOS)

        def show(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
            self._on_show()

        def quit_(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
            self._on_quit()

        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", show, default=True),
            pystray.MenuItem("退出", quit_),
        )
        self._icon = pystray.Icon("SleepPlan", image, "Sleep Plan · 电源计划", menu)

        def run() -> None:
            assert self._icon is not None
            self._icon.run()

        self._thread = threading.Thread(target=run, daemon=True, name="tray")
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None