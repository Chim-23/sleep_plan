"""计划执行历史记录。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MAX_ENTRIES = 1000

STATUS_LABELS = {
    "awaiting_confirm": "等待确认",
    "executed": "已执行",
    "cancelled": "已取消",
    "failed": "执行失败",
}


@dataclass
class HistoryEntry:
    id: str
    time_iso: str
    task_id: str
    action_key: str
    action_label: str
    trigger: str
    plan_describe: str
    status: str
    detail: str = ""

    @property
    def time_display(self) -> str:
        try:
            return datetime.fromisoformat(self.time_iso).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return self.time_iso

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class ExecutionHistory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path = Path.home() / ".sleep_plan" / "history.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[HistoryEntry] = []
        self.load()

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [HistoryEntry(**item) for item in raw]
        except (json.JSONDecodeError, TypeError, ValueError):
            self._entries = []

    def _save(self) -> None:
        data = [asdict(e) for e in self._entries]
        text = json.dumps(data, ensure_ascii=False, indent=2)
        with self._path.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                import os

                os.fsync(f.fileno())
            except OSError:
                pass

    def record(
        self,
        *,
        task_id: str,
        action_key: str,
        action_label: str,
        trigger: str,
        plan_describe: str,
        status: str,
        detail: str = "",
    ) -> HistoryEntry:
        entry = HistoryEntry(
            id=str(uuid.uuid4()),
            time_iso=datetime.now().isoformat(timespec="seconds"),
            task_id=task_id,
            action_key=action_key,
            action_label=action_label,
            trigger=trigger,
            plan_describe=plan_describe,
            status=status,
            detail=detail,
        )
        with self._lock:
            self._entries.insert(0, entry)
            if len(self._entries) > MAX_ENTRIES:
                self._entries = self._entries[:MAX_ENTRIES]
            self._save()
        return entry

    def list_entries(self, limit: int | None = None) -> list[HistoryEntry]:
        with self._lock:
            items = list(self._entries)
        if limit is not None:
            return items[:limit]
        return items

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._save()


execution_history = ExecutionHistory()


def record_task(task, status: str, detail: str = "") -> HistoryEntry:
    return execution_history.record(
        task_id=task.id,
        action_key=task.action_key,
        action_label=task.action_label,
        trigger=task.trigger,
        plan_describe=task.describe(),
        status=status,
        detail=detail,
    )