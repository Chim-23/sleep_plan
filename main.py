"""Sleep Plan — Windows 定时睡眠 / 锁屏 / 关机 / 重启"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from history import execution_history
from scheduler import CONFIRM_ACTIONS, PlannedTask, TaskScheduler
from settings import load_settings, save_settings, set_autostart
from tray_support import TrayController
from windows_actions import ACTIONS, cancel_shutdown
from win_icon import apply_hd_window_icons, enable_dpi_awareness

ROOT = Path(__file__).resolve().parent


def _asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", ROOT))
    bundled = base / "assets" / name
    if bundled.is_file():
        return bundled
    return ROOT / "assets" / name


ICON_PATH = _asset_path("icon.ico")
ICON_PNG = _asset_path("icon.png")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACTION_OPTIONS = [
    ("sleep", "睡眠"),
    ("lock", "锁屏"),
    ("shutdown", "关机"),
    ("restart", "重启"),
]

TRIGGER_OPTIONS = [
    ("once", "指定日期时间（一次）"),
    ("daily", "每天固定时间"),
    ("countdown", "倒计时"),
]

FORM_WIDTH = 292


def center_toplevel(win: ctk.CTkToplevel, *, parent: ctk.CTk | None = None) -> None:
    """将子窗口置于屏幕中央（有可见父窗口时也可相对父窗口居中）。"""
    win.update_idletasks()
    w = max(win.winfo_width(), win.winfo_reqwidth())
    h = max(win.winfo_height(), win.winfo_reqheight())
    if parent is not None and parent.winfo_viewable():
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
    else:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


class ConfirmPowerDialog(ctk.CTkToplevel):
    """计划到点前倒计时确认。"""

    def __init__(
        self,
        master: ctk.CTk,
        task: PlannedTask,
        seconds: int,
        on_execute: Callable[[str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_execute = on_execute
        self._on_cancel = on_cancel
        self._remaining = seconds
        self._closed = False
        self._tick_id: str | None = None

        action = ACTIONS.get(task.action_key, ("操作", None))[0]
        self.title("即将执行")
        self.minsize(420, 300)
        self.geometry("420x300")
        self.resizable(False, False)
        self.transient(master)
        self.attributes("-topmost", True)
        if master.winfo_viewable():
            self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self,
            text=f"即将{action}",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, pady=(20, 4), padx=24, sticky="ew")
        ctk.CTkLabel(
            self,
            text=task.describe(),
            font=ctk.CTkFont(size=13),
            text_color=("gray40", "gray65"),
        ).grid(row=1, column=0, pady=(0, 8), padx=24, sticky="ew")

        center = ctk.CTkFrame(self, fg_color="transparent")
        center.grid(row=2, column=0, sticky="nsew", padx=24)
        center.grid_columnconfigure(0, weight=1)

        self._count_label = ctk.CTkLabel(
            center,
            text=str(self._remaining),
            font=ctk.CTkFont(size=44, weight="bold"),
            text_color=("#c2410c", "#fb923c"),
        )
        self._count_label.grid(row=0, column=0, pady=(4, 0))
        ctk.CTkLabel(
            center,
            text="秒后执行",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray60"),
        ).grid(row=1, column=0, pady=(0, 4))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew", padx=24, pady=(8, 20))
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row,
            text="取消此次计划",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#b91c1c",
            hover_color="#dc2626",
            command=self._cancel,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            btn_row,
            text="立即执行",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._confirm,
        ).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        center_toplevel(self, parent=master)
        self._tick()

    def _tick(self) -> None:
        if self._closed:
            return
        self._count_label.configure(text=str(self._remaining))
        if self._remaining <= 0:
            self._finish("timeout")
            return
        self._remaining -= 1
        self._tick_id = self.after(1000, self._tick)

    def _stop_tick(self) -> None:
        if self._tick_id:
            self.after_cancel(self._tick_id)
            self._tick_id = None

    def _cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_tick()
        self._on_cancel()
        self.grab_release()
        self.destroy()

    def _confirm(self) -> None:
        self._finish("manual")

    def _finish(self, source: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_tick()
        self._on_execute(source)
        self.grab_release()
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master: SleepPlanApp) -> None:
        super().__init__(master)
        self._app = master
        self.title("设置")
        self.geometry("380x200")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="设置",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=24, pady=(20, 16))

        self.tray_var = ctk.BooleanVar(
            value=master.settings.get("minimize_to_tray_on_close", True)
        )
        self.auto_var = ctk.BooleanVar(value=master.settings.get("autostart", True))

        ctk.CTkSwitch(
            self,
            text="关闭窗口时最小化到托盘",
            variable=self.tray_var,
            command=self._apply,
        ).pack(anchor="w", padx=24, pady=8)
        ctk.CTkSwitch(
            self,
            text="开机自动启动",
            variable=self.auto_var,
            command=self._apply,
        ).pack(anchor="w", padx=24, pady=8)

        ctk.CTkButton(self, text="关闭", width=100, command=self.destroy).pack(
            pady=(16, 20)
        )
        center_toplevel(self, parent=master)

    def _apply(self) -> None:
        self._app.settings["minimize_to_tray_on_close"] = self.tray_var.get()
        self._app.settings["autostart"] = self.auto_var.get()
        save_settings(self._app.settings)
        set_autostart(self.auto_var.get())
        self._app._ensure_tray()


class HistoryDialog(ctk.CTkToplevel):
    def __init__(self, master: SleepPlanApp) -> None:
        super().__init__(master)
        self.title("执行历史")
        self.geometry("560x480")
        self.minsize(480, 360)
        self.transient(master)
        self.grab_set()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            top, text="执行历史", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(side="left")
        ctk.CTkButton(
            top,
            text="刷新",
            width=64,
            height=28,
            command=self._refresh,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            top,
            text="清空",
            width=64,
            height=28,
            fg_color=("gray75", "#8b3a3a"),
            hover_color=("gray65", "#a04545"),
            command=self._clear,
        ).pack(side="right")

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text=f"记录保存在 {Path.home() / '.sleep_plan' / 'history.json'}",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
        ).pack(pady=(0, 12))

        self._refresh()
        center_toplevel(self, parent=master)

    def _refresh(self) -> None:
        execution_history.load()
        for child in self._scroll.winfo_children():
            child.destroy()
        entries = execution_history.list_entries()
        if not entries:
            ctk.CTkLabel(
                self._scroll,
                text="暂无历史记录",
                text_color=("gray50", "gray55"),
            ).grid(row=0, column=0, pady=40)
            return
        status_colors = {
            "executed": ("#166534", "#4ade80"),
            "cancelled": ("gray45", "gray60"),
            "awaiting_confirm": ("#c2410c", "#fb923c"),
            "failed": ("#991b1b", "#f87171"),
        }
        for i, entry in enumerate(entries):
            card = ctk.CTkFrame(self._scroll, corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=4)
            card.grid_columnconfigure(0, weight=1)
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
            head.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                head,
                text=entry.time_display,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                head,
                text=entry.status_label,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=status_colors.get(entry.status, ("gray40", "gray70")),
            ).grid(row=0, column=2, sticky="e")
            ctk.CTkLabel(
                card,
                text=f"{entry.plan_describe}",
                font=ctk.CTkFont(size=13),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 2))
            if entry.detail:
                ctk.CTkLabel(
                    card,
                    text=entry.detail,
                    font=ctk.CTkFont(size=11),
                    text_color=("gray45", "gray60"),
                    anchor="w",
                ).grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))

    def _clear(self) -> None:
        execution_history.clear()
        self._refresh()


class SleepPlanApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Sleep Plan · 电源计划")
        self.minsize(640, 480)
        self._geo_save_after: str | None = None
        self._apply_window_icon()
        self.bind("<Map>", self._on_window_map, add="+")

        self.settings = load_settings()
        set_autostart(self.settings.get("autostart", True))

        self._quitting = False
        self._confirm_dialog: ConfirmPowerDialog | None = None
        self.tray: TrayController | None = None

        self.scheduler = TaskScheduler(
            on_tasks_changed=self._refresh_list,
            on_confirmation_required=self._on_confirmation_required,
            main_thread_hook=lambda fn: self.after(0, fn),
        )
        self.scheduler.load()

        self._build_ui()
        self._refresh_list()
        self._restore_window_geometry()
        self._ensure_tray()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_configure, add="+")

    def _restore_window_geometry(self) -> None:
        geo = (self.settings.get("window_geometry") or "").strip()
        if not geo:
            self.geometry("720x520")
            return
        wh = geo.split("+", 1)[0]
        try:
            w, h = (int(x) for x in wh.split("x", 1))
            if w < 640 or h < 480:
                self.geometry("720x520")
                return
        except (ValueError, TypeError):
            self.geometry("720x520")
            return
        try:
            self.geometry(geo)
            self.update_idletasks()
        except Exception:
            self.geometry("720x520")

    def _save_window_geometry(self) -> None:
        self.update_idletasks()
        geo = self.geometry()
        if not geo or "x" not in geo:
            return
        wh = geo.split("+", 1)[0]
        try:
            w, h = (int(x) for x in wh.split("x", 1))
        except (ValueError, TypeError):
            return
        if w < 640 or h < 480:
            return
        if str(self.state()) != "withdrawn" and (w < 100 or h < 100):
            return
        if self.settings.get("window_geometry") == geo:
            return
        self.settings["window_geometry"] = geo
        save_settings(self.settings)

    def _on_configure(self, event) -> None:
        if event.widget is not self:
            return
        if self._geo_save_after:
            self.after_cancel(self._geo_save_after)
        self._geo_save_after = self.after(400, self._save_window_geometry)

    def _apply_window_icon(self) -> None:
        # Windows 用系统 DPI 尺寸加载 ICO，不用 iconbitmap（易固定 16×16 发糊）
        if sys.platform != "win32" and ICON_PATH.is_file():
            try:
                self.iconbitmap(default=str(ICON_PATH))
            except Exception:
                pass
        self.after(80, self._refresh_hd_icons)
        self.after(400, self._refresh_hd_icons)

    def _on_window_map(self, _event=None) -> None:
        self._refresh_hd_icons()

    def _refresh_hd_icons(self) -> None:
        if ICON_PATH.is_file():
            try:
                apply_hd_window_icons(self, ICON_PATH)
            except Exception:
                pass

    def _ensure_tray(self) -> None:
        if not self.settings.get("minimize_to_tray_on_close", True):
            if self.tray:
                self.tray.stop()
                self.tray = None
            return
        tray_icon = ICON_PNG if ICON_PNG.is_file() else ICON_PATH
        if self.tray is None and tray_icon.is_file():
            self.tray = TrayController(
                tray_icon,
                on_show=lambda: self.after(0, self._show_from_tray),
                on_quit=lambda: self.after(0, self._quit_app),
            )
            self.tray.start()

    def _show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_confirmation_required(
        self,
        task: PlannedTask,
        countdown: int,
        execute: Callable[..., None],
        cancel: Callable[[], None],
    ) -> None:
        if self._confirm_dialog and self._confirm_dialog.winfo_exists():
            return
        self.deiconify()
        self.lift()

        def wrap_execute(source: str) -> None:
            self._confirm_dialog = None
            execute(source=source)

        def wrap_cancel() -> None:
            self._confirm_dialog = None
            cancel()

        self._confirm_dialog = ConfirmPowerDialog(
            self, task, countdown, wrap_execute, wrap_cancel
        )

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 8))
        header.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew")
        title_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_row,
            text="电源计划",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            title_row,
            text="历史",
            width=72,
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._open_history,
        ).grid(row=0, column=1, padx=(12, 0))
        ctk.CTkButton(
            title_row,
            text="设置",
            width=72,
            height=28,
            fg_color="transparent",
            border_width=1,
            command=self._open_settings,
        ).grid(row=0, column=2, padx=(8, 0))

        ctk.CTkLabel(
            header,
            text="定时睡眠、锁屏、关机或重启",
            font=ctk.CTkFont(size=13),
            text_color=("gray45", "gray60"),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=24, pady=8)
        body.grid_columnconfigure(0, minsize=FORM_WIDTH, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        form = ctk.CTkFrame(body, corner_radius=12, width=FORM_WIDTH)
        form.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        form.grid_propagate(False)
        form.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            form, text="新建计划", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 12))

        ctk.CTkLabel(form, text="操作", anchor="w").grid(
            row=1, column=0, sticky="ew", padx=20
        )
        self.action_var = ctk.StringVar(value=ACTION_OPTIONS[0][1])
        self.action_menu = ctk.CTkOptionMenu(
            form,
            variable=self.action_var,
            values=[label for _, label in ACTION_OPTIONS],
            width=FORM_WIDTH - 40,
        )
        self.action_menu.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 12))
        self._label_to_action = {label: key for key, label in ACTION_OPTIONS}

        ctk.CTkLabel(form, text="触发方式", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=20
        )
        self.trigger_var = ctk.StringVar(value=TRIGGER_OPTIONS[1][1])
        self.trigger_menu = ctk.CTkOptionMenu(
            form,
            variable=self.trigger_var,
            values=[label for _, label in TRIGGER_OPTIONS],
            width=FORM_WIDTH - 40,
            command=self._on_trigger_change,
        )
        self.trigger_menu.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 8))
        self._label_to_trigger = {label: key for key, label in TRIGGER_OPTIONS}

        self.time_slot = ctk.CTkFrame(
            form, fg_color="transparent", width=FORM_WIDTH - 32, height=40
        )
        self.time_slot.grid(row=5, column=0, sticky="ew", padx=16, pady=4)
        self.time_slot.grid_propagate(False)
        self.time_slot.grid_columnconfigure((0, 1, 2), weight=1)

        now = datetime.now()
        self.date_entry = ctk.CTkEntry(
            self.time_slot, placeholder_text="YYYY-MM-DD", width=120
        )
        self.date_entry.insert(0, now.strftime("%Y-%m-%d"))

        self.hour_spin = ctk.CTkEntry(
            self.time_slot, width=56, justify="center", placeholder_text="时"
        )
        self.hour_spin.insert(0, f"{now.hour:02d}")

        self.min_spin = ctk.CTkEntry(
            self.time_slot, width=56, justify="center", placeholder_text="分"
        )
        self.min_spin.insert(0, f"{(now.minute + 5) % 60:02d}")

        self.countdown_frame = ctk.CTkFrame(
            self.time_slot, fg_color="transparent"
        )
        self.countdown_frame.grid_columnconfigure((0, 1, 2), weight=1)
        self.cd_hour = ctk.CTkEntry(self.countdown_frame, placeholder_text="时")
        self.cd_hour.insert(0, "0")
        self.cd_hour.grid(row=0, column=0, padx=4, sticky="ew")
        self.cd_min = ctk.CTkEntry(self.countdown_frame, placeholder_text="分")
        self.cd_min.insert(0, "30")
        self.cd_min.grid(row=0, column=1, padx=4, sticky="ew")
        self.cd_sec = ctk.CTkEntry(self.countdown_frame, placeholder_text="秒")
        self.cd_sec.insert(0, "0")
        self.cd_sec.grid(row=0, column=2, padx=4, sticky="ew")

        self.quick = ctk.CTkFrame(form, fg_color="transparent", height=36)
        self.quick.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 4))
        self.quick.grid_propagate(False)
        self.quick.grid_columnconfigure((0, 1, 2), weight=1)
        for i, (text, minutes) in enumerate(
            [("15 分钟", 15), ("30 分钟", 30), ("1 小时", 60)]
        ):
            ctk.CTkButton(
                self.quick,
                text=text,
                height=28,
                fg_color=("gray85", "gray25"),
                text_color=("gray20", "gray90"),
                hover_color=("gray75", "gray35"),
                command=lambda m=minutes: self._quick_countdown(m),
            ).grid(row=0, column=i, padx=4, sticky="ew")
        self.quick.grid_remove()

        ctk.CTkButton(
            form,
            text="添加计划",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._add_task,
        ).grid(row=7, column=0, sticky="ew", padx=20, pady=(16, 20))

        list_panel = ctk.CTkFrame(body, corner_radius=12)
        list_panel.grid(row=0, column=1, sticky="nsew")
        list_panel.grid_columnconfigure(0, weight=1)
        list_panel.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(list_panel, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top_bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            top_bar, text="待执行", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            top_bar,
            text="取消系统关机倒计时",
            width=140,
            height=28,
            fg_color="transparent",
            border_width=1,
            text_color=("gray30", "gray80"),
            command=cancel_shutdown,
        ).grid(row=0, column=1)

        self.task_scroll = ctk.CTkScrollableFrame(list_panel, fg_color="transparent")
        self.task_scroll.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.task_scroll.grid_columnconfigure(0, weight=1)

        footer = ctk.CTkLabel(
            self,
            text="睡眠/锁屏/关机/重启均在到点前 15 秒弹窗确认；关闭窗口默认最小化到托盘",
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray55"),
        )
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 16))

        self._on_trigger_change(self.trigger_var.get())

    def _open_settings(self) -> None:
        SettingsDialog(self)

    def _open_history(self) -> None:
        HistoryDialog(self)

    def _layout_time_mode(self, key: str) -> None:
        for w in (
            self.date_entry,
            self.hour_spin,
            self.min_spin,
            self.countdown_frame,
        ):
            w.grid_remove()

        if key == "countdown":
            self.countdown_frame.grid(
                row=0, column=0, columnspan=3, sticky="ew", in_=self.time_slot
            )
            self.quick.grid()
        else:
            if key == "once":
                self.date_entry.grid(
                    row=0, column=0, sticky="ew", padx=4, in_=self.time_slot
                )
                self.hour_spin.grid(row=0, column=1, padx=4, in_=self.time_slot)
                self.min_spin.grid(row=0, column=2, padx=4, in_=self.time_slot)
            else:
                self.hour_spin.grid(row=0, column=0, padx=4, in_=self.time_slot)
                self.min_spin.grid(
                    row=0, column=1, columnspan=2, padx=4, in_=self.time_slot
                )
            self.quick.grid_remove()

    def _on_trigger_change(self, label: str) -> None:
        key = self._label_to_trigger.get(label, "daily")
        self._layout_time_mode(key)

    def _quick_countdown(self, minutes: int) -> None:
        self.trigger_var.set(next(l for k, l in TRIGGER_OPTIONS if k == "countdown"))
        self._on_trigger_change(self.trigger_var.get())
        self.cd_hour.delete(0, "end")
        self.cd_hour.insert(0, str(minutes // 60))
        self.cd_min.delete(0, "end")
        self.cd_min.insert(0, str(minutes % 60))
        self.cd_sec.delete(0, "end")
        self.cd_sec.insert(0, "0")

    def _parse_int(self, entry: ctk.CTkEntry, default: int = 0) -> int:
        try:
            return max(0, int(entry.get().strip()))
        except ValueError:
            return default

    def _add_task(self) -> None:
        action = self._label_to_action.get(self.action_var.get(), "sleep")
        trigger = self._label_to_trigger.get(self.trigger_var.get(), "daily")

        if trigger == "countdown":
            secs = (
                self._parse_int(self.cd_hour) * 3600
                + self._parse_int(self.cd_min) * 60
                + self._parse_int(self.cd_sec)
            )
            if secs < 1:
                self._show_error("倒计时应大于 0 秒")
                return
            self.scheduler.add_task(action, "countdown", countdown_seconds=secs)
            return

        try:
            hour = int(self.hour_spin.get().strip())
            minute = int(self.min_spin.get().strip())
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            self._show_error("请输入有效的小时 (0–23) 与分钟 (0–59)")
            return

        if trigger == "daily":
            run_at = datetime.now().replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        else:
            date_str = self.date_entry.get().strip()
            try:
                y, m, d = map(int, date_str.split("-"))
                run_at = datetime(y, m, d, hour, minute, 0)
            except ValueError:
                self._show_error("日期格式应为 YYYY-MM-DD")
                return
            if run_at <= datetime.now():
                self._show_error("指定时间必须晚于当前时间")
                return

        self.scheduler.add_task(action, trigger, run_at=run_at)

    def _show_error(self, msg: str) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("提示")
        dialog.geometry("340x140")
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text=msg, wraplength=300).pack(
            expand=True, padx=20, pady=20
        )
        ctk.CTkButton(dialog, text="确定", command=dialog.destroy).pack(pady=(0, 16))
        center_toplevel(dialog, parent=self)

    def _refresh_list(self) -> None:
        for child in self.task_scroll.winfo_children():
            child.destroy()

        tasks = self.scheduler.list_tasks()
        if not tasks:
            ctk.CTkLabel(
                self.task_scroll,
                text="暂无计划\n在左侧添加一条即可",
                text_color=("gray50", "gray55"),
            ).grid(row=0, column=0, pady=40)
            return

        for i, task in enumerate(tasks):
            self._render_task_row(i, task)

    def _render_task_row(self, row: int, task: PlannedTask) -> None:
        card = ctk.CTkFrame(self.task_scroll, corner_radius=10)
        card.grid(row=row, column=0, sticky="ew", pady=6)
        card.grid_columnconfigure(0, weight=1)

        icon = {"sleep": "🌙", "lock": "🔒", "shutdown": "⏻", "restart": "↻"}.get(
            task.action_key, "•"
        )
        extra = (
            " · 到点前 15 秒确认"
            if task.action_key in CONFIRM_ACTIONS
            else ""
        )
        ctk.CTkLabel(
            card,
            text=f"{icon}  {task.describe()}{extra}",
            font=ctk.CTkFont(size=14),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=12)

        ctk.CTkButton(
            card,
            text="删除",
            width=64,
            height=28,
            fg_color=("gray80", "#8b3a3a"),
            hover_color=("gray70", "#a04545"),
            command=lambda tid=task.id: self.scheduler.remove_task(tid),
        ).grid(row=0, column=1, padx=12, pady=8)

    def _on_close(self) -> None:
        self._save_window_geometry()
        if self.settings.get("minimize_to_tray_on_close", True) and self.tray:
            self.withdraw()
            return
        self._quit_app()

    def _quit_app(self) -> None:
        if self._quitting:
            return
        self._save_window_geometry()
        self._quitting = True
        self.scheduler.shutdown()
        if self.tray:
            self.tray.stop()
        self.destroy()


def main() -> None:
    if sys.platform != "win32":
        print("本程序仅支持 Windows。")
        sys.exit(1)
    enable_dpi_awareness()
    if not ICON_PATH.is_file():
        script = ROOT / "assets" / "generate_icon.py"
        if script.is_file():
            subprocess.run([sys.executable, str(script)], check=False)
    app = SleepPlanApp()
    app.mainloop()


if __name__ == "__main__":
    main()