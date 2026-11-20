"""定时任务调度。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from history import record_task
from windows_actions import ACTIONS

CONFIRM_ACTIONS = frozenset({"sleep", "lock", "shutdown", "restart"})
CONFIRM_LEAD_SECONDS = 15


@dataclass
class PlannedTask:
    id: str
    action_key: str
    trigger: str  # "once" | "daily" | "countdown"
    run_at_iso: str
    countdown_seconds: int
    enabled: bool = True
    label: str = ""

    @property
    def action_label(self) -> str:
        return ACTIONS.get(self.action_key, (self.action_key, None))[0]

    def describe(self) -> str:
        if self.trigger == "countdown":
            m, s = divmod(self.countdown_seconds, 60)
            h, m = divmod(m, 60)
            parts = []
            if h:
                parts.append(f"{h}小时")
            if m or h:
                parts.append(f"{m}分")
            parts.append(f"{s}秒")
            return f"倒计时 {' '.join(parts)} 后 · {self.action_label}"
        if self.trigger == "daily":
            t = datetime.fromisoformat(self.run_at_iso)
            return f"每天 {t.strftime('%H:%M')} · {self.action_label}"
        t = datetime.fromisoformat(self.run_at_iso)
        return f"{t.strftime('%Y-%m-%d %H:%M')} · {self.action_label}"

    def remove_after_run(self) -> bool:
        return self.trigger in ("once", "countdown")


class TaskScheduler:
    def __init__(
        self,
        on_tasks_changed: Callable[[], None] | None = None,
        on_confirmation_required: Callable[
            [PlannedTask, int, Callable[[], None], Callable[[], None]], None
        ]
        | None = None,
        main_thread_hook: Callable[[Callable[[], None]], None] | None = None,
    ):
        self._lock = threading.Lock()
        self._tasks: dict[str, PlannedTask] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._stop_daily = threading.Event()
        self._daily_thread: threading.Thread | None = None
        self._daily_confirm_slots: dict[str, str] = {}
        self._on_tasks_changed = on_tasks_changed
        self._on_confirmation_required = on_confirmation_required
        self._main_thread_hook = main_thread_hook
        self._data_path = self._default_data_path()

    @staticmethod
    def _default_data_path() -> Path:
        base = Path.home() / ".sleep_plan"
        base.mkdir(parents=True, exist_ok=True)
        return base / "tasks.json"

    def set_main_thread_hook(
        self, hook: Callable[[Callable[[], None]], None] | None
    ) -> None:
        self._main_thread_hook = hook

    def _run_on_main(self, fn: Callable[[], None]) -> None:
        if self._main_thread_hook:
            self._main_thread_hook(fn)
        else:
            fn()

    def load(self) -> None:
        if not self._data_path.exists():
            return
        try:
            raw = json.loads(self._data_path.read_text(encoding="utf-8"))
            for item in raw:
                task = PlannedTask(**item)
                if task.enabled:
                    self._tasks[task.id] = task
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        self._reschedule_all()

    def save(self) -> None:
        data = [asdict(t) for t in self._tasks.values()]
        self._data_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_tasks(self) -> list[PlannedTask]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.describe())

    def add_task(
        self,
        action_key: str,
        trigger: str,
        *,
        run_at: datetime | None = None,
        countdown_seconds: int = 0,
    ) -> PlannedTask:
        task_id = str(uuid.uuid4())
        run_at_iso = (run_at or datetime.now()).isoformat()
        task = PlannedTask(
            id=task_id,
            action_key=action_key,
            trigger=trigger,
            run_at_iso=run_at_iso,
            countdown_seconds=countdown_seconds,
        )
        with self._lock:
            self._tasks[task_id] = task
        self._schedule_task(task)
        self.save()
        self._notify()
        return task

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)
        self._cancel_timers_for(task_id)
        self.save()
        self._notify()

    def shutdown(self) -> None:
        self._stop_daily.set()
        with self._lock:
            for tid in list(self._tasks):
                self._cancel_timers_for(tid)

    def _notify(self) -> None:
        if self._on_tasks_changed:
            self._on_tasks_changed()

    def _timer_key(self, task_id: str, suffix: str = "") -> str:
        return f"{task_id}{suffix}"

    def _cancel_timers_for(self, task_id: str) -> None:
        for key in list(self._timers):
            if key == task_id or key.startswith(f"{task_id}:"):
                timer = self._timers.pop(key, None)
                if timer:
                    timer.cancel()

    def _reschedule_all(self) -> None:
        for tid in list(self._tasks):
            self._cancel_timers_for(tid)
        for task in list(self._tasks.values()):
            if task.enabled:
                self._schedule_task(task)
        self._ensure_daily_watcher()

    def _needs_confirmation(self, task: PlannedTask) -> bool:
        return task.action_key in CONFIRM_ACTIONS

    def _schedule_task(self, task: PlannedTask) -> None:
        if task.trigger == "countdown":
            delay = max(1, task.countdown_seconds)
            self._schedule_execution(task, delay)
            return
        if task.trigger == "once":
            run_at = datetime.fromisoformat(task.run_at_iso)
            delay = (run_at - datetime.now()).total_seconds()
            if delay <= 0:
                self.remove_task(task.id)
                return
            self._schedule_execution(task, delay)
            return
        if task.trigger == "daily":
            self._ensure_daily_watcher()

    def _schedule_execution(self, task: PlannedTask, delay: float) -> None:
        remove_after = task.remove_after_run()
        if self._needs_confirmation(task):
            if delay <= CONFIRM_LEAD_SECONDS:
                countdown = max(1, int(delay))
                wait = 0.0
            else:
                countdown = CONFIRM_LEAD_SECONDS
                wait = delay - CONFIRM_LEAD_SECONDS

            def begin_confirm() -> None:
                self._begin_confirmation(task, countdown, remove_after)

            if wait > 0:
                self._arm_timer(
                    task, wait, timer_suffix=":pre", on_fire=begin_confirm
                )
            else:
                self._run_on_main(begin_confirm)
            return

        self._arm_timer(
            task,
            delay,
            on_fire=lambda: self._complete_task(task, remove_after, source="direct"),
        )

    def _begin_confirmation(
        self, task: PlannedTask, countdown: int, remove_after: bool
    ) -> None:
        if task.id not in self._tasks:
            return

        def execute(*, source: str = "timeout") -> None:
            self._complete_task(task, remove_after, source=source)

        def cancel() -> None:
            record_task(task, "cancelled", detail="用户取消此次执行")
            if remove_after:
                self.remove_task(task.id)
            else:
                self._notify()

        if self._on_confirmation_required:
            self._on_confirmation_required(task, countdown, execute, cancel)
        else:
            execute(source="direct")

    def _complete_task(
        self, task: PlannedTask, remove_after: bool, *, source: str = "direct"
    ) -> None:
        detail_map = {
            "manual": "用户点击立即执行",
            "timeout": "倒计时结束自动执行",
            "direct": "到点直接执行",
        }
        detail = detail_map.get(source, source)
        try:
            # 关机/重启会立刻结束进程，必须先落盘再调用系统命令
            record_task(task, "executed", detail=detail)
            self._execute(task)
        except OSError as e:
            record_task(task, "failed", detail=str(e))
        if remove_after:
            self.remove_task(task.id)

    def _arm_timer(
        self,
        task: PlannedTask,
        delay: float,
        *,
        timer_suffix: str = "",
        on_fire: Callable[[], None] | None = None,
    ) -> None:
        key = self._timer_key(task.id, timer_suffix)
        old = self._timers.pop(key, None)
        if old:
            old.cancel()

        def fire() -> None:
            self._timers.pop(key, None)
            callback = on_fire or (
                lambda: self._complete_task(
                    task, task.remove_after_run(), source="direct"
                )
            )
            self._run_on_main(callback)

        timer = threading.Timer(max(0.05, delay), fire)
        timer.daemon = True
        self._timers[key] = timer
        timer.start()

    def _ensure_daily_watcher(self) -> None:
        has_daily = any(t.trigger == "daily" for t in self._tasks.values())
        if not has_daily:
            return
        if self._daily_thread and self._daily_thread.is_alive():
            return
        self._stop_daily.clear()
        self._daily_thread = threading.Thread(
            target=self._daily_loop, daemon=True, name="daily-watcher"
        )
        self._daily_thread.start()

    def _daily_loop(self) -> None:
        last_fired: dict[str, str] = {}
        while not self._stop_daily.wait(1):
            now = datetime.now()
            for task in list(self._tasks.values()):
                if task.trigger != "daily" or not task.enabled:
                    continue
                target = datetime.fromisoformat(task.run_at_iso)
                target_dt = now.replace(
                    hour=target.hour,
                    minute=target.minute,
                    second=0,
                    microsecond=0,
                )
                diff = (target_dt - now).total_seconds()
                slot = now.strftime("%Y-%m-%d") + target.strftime(" %H:%M")

                if self._needs_confirmation(task):
                    if CONFIRM_LEAD_SECONDS >= diff > 0:
                        if self._daily_confirm_slots.get(task.id) != slot:
                            self._daily_confirm_slots[task.id] = slot
                            countdown = max(1, int(diff))
                            self._run_on_main(
                                lambda t=task, c=countdown: self._begin_confirmation(
                                    t, c, remove_after=False
                                )
                            )
                    continue

                if 0 <= diff < 1 and last_fired.get(task.id) != slot:
                    last_fired[task.id] = slot
                    self._run_on_main(
                        lambda t=task: self._complete_task(
                            t, remove_after=False, source="direct"
                        )
                    )

    def _execute(self, task: PlannedTask) -> None:
        _, fn = ACTIONS.get(task.action_key, (None, None))
        if fn is None:
            raise OSError("未知操作")
        fn()