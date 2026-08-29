from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable


QUEUE_SCHEMA_VERSION = "2.0"
DISPATCHER_VERSION = "2.0"
RUNNABLE_STATES = {"READY_TO_PRODUCE", "RETRYING", "RUNNING", "QUEUED_WAITING_WORKSHOP"}
WORKSHOP_BLOCKING_STATES = {"RUNNING"}
TERMINAL_LANE_STATES = {
    "VIDEO_READY",
    "FAILED",
    "CANCELLED",
    "ARCHIVED",
    "PAUSED",
    "NEEDS_CONFIGURATION",
    "NEEDS_REPAIR",
    "AWAITING_JIANYING_EXPORT",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _pid_running(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def queue_root(data_root: Path) -> Path:
    return data_root.resolve() / "production" / "queue-v2"


def _wake_event_name(data_root: Path) -> str:
    digest = hashlib.sha256(str(data_root.resolve()).casefold().encode("utf-8")).hexdigest()[:24]
    return f"Local\\AIVCPQueueV2_{digest}"


def signal_dispatcher(data_root: Path) -> Path:
    path = queue_root(data_root) / "dispatch.wake.json"
    _atomic_json(path, {"schemaVersion": QUEUE_SCHEMA_VERSION, "eventId": uuid.uuid4().hex, "atEpoch": time.time()})
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.OpenEventW.restype = ctypes.c_void_p
        event_modify_state = 0x0002
        handle = kernel32.OpenEventW(event_modify_state, False, _wake_event_name(data_root))
        if handle:
            try:
                kernel32.SetEvent(handle)
            finally:
                kernel32.CloseHandle(handle)
    return path


def queue_position(data_root: Path, production_task_id: str) -> dict[str, Any]:
    tasks_root = data_root.resolve() / "production" / "tasks"
    rows: list[dict[str, Any]] = []
    if tasks_root.is_dir():
        for path in tasks_root.glob("*/production-task.json"):
            task = _read_json(path)
            queue = task.get("queue") if isinstance(task.get("queue"), dict) else {}
            if queue.get("schemaVersion") != QUEUE_SCHEMA_VERSION:
                continue
            if task.get("state") in TERMINAL_LANE_STATES:
                continue
            rows.append(task)
    rows.sort(key=lambda item: (str(item.get("createdAt") or ""), str(item.get("productionTaskId") or "")))
    ids = [str(item.get("productionTaskId") or "") for item in rows]
    position = ids.index(production_task_id) + 1 if production_task_id in ids else None
    status = _read_json(queue_root(data_root) / "dispatcher-status.json")
    return {
        "schemaVersion": QUEUE_SCHEMA_VERSION,
        "position": position,
        "queuedCount": len(rows),
        "dispatcherRunning": _pid_running(status.get("pid")),
        "dispatcherPid": status.get("pid") if _pid_running(status.get("pid")) else None,
        "dispatchMode": "persistent_local_event",
        "codexHeartbeatDrivesProduction": False,
    }


def ensure_dispatcher(
    *,
    data_root: Path,
    plugin_root: Path,
    workshop_executable: Path,
    workshop_isolation_root: Path,
) -> dict[str, Any]:
    root = queue_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = _read_json(root / "dispatcher-v2.lock.json")
    if lock.get("version") == DISPATCHER_VERSION and _pid_running(lock.get("pid")):
        signal_dispatcher(data_root)
        return {"started": False, "pid": lock.get("pid"), "alreadyRunning": True}

    env = os.environ.copy()
    env["AIVCP_QUEUE_WORKER"] = "1"
    env["AIVCP_DATA_ROOT"] = str(data_root.resolve())
    mcp_root = plugin_root.resolve() / "mcp"
    existing_python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(mcp_root) + (os.pathsep + existing_python_path if existing_python_path else "")
    argv = [
        sys.executable,
        "-m",
        "aivcp_tools.production_queue_worker",
        "--data-root",
        str(data_root.resolve()),
        "--plugin-root",
        str(plugin_root.resolve()),
        "--workshop-executable",
        str(workshop_executable.resolve()),
        "--workshop-isolation-root",
        str(workshop_isolation_root.resolve()),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    process = subprocess.Popen(
        argv,
        cwd=str(mcp_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    signal_dispatcher(data_root)
    return {"started": True, "pid": process.pid, "alreadyRunning": False}


class DirectoryEventWaiter:
    """Wait for real filesystem changes on Windows; timeout is crash recovery only."""

    def __init__(
        self,
        paths: list[Path],
        *,
        wake_event_name: str | None = None,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        self.paths = [path.resolve() for path in paths]
        self.recovery_timeout_seconds = max(5.0, float(recovery_timeout_seconds))
        self.handles: list[int] = []
        self.change_handle_indexes: set[int] = set()
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            if wake_event_name:
                kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p]
                kernel32.CreateEventW.restype = ctypes.c_void_p
                event_handle = kernel32.CreateEventW(None, False, False, wake_event_name)
                if event_handle:
                    self.handles.append(int(event_handle))
            kernel32.FindFirstChangeNotificationW.argtypes = [ctypes.c_wchar_p, ctypes.c_bool, ctypes.c_uint32]
            kernel32.FindFirstChangeNotificationW.restype = ctypes.c_void_p
            filters = 0x00000001 | 0x00000003 | 0x00000010 | 0x00000008
            for path in self.paths:
                path.mkdir(parents=True, exist_ok=True)
                handle = kernel32.FindFirstChangeNotificationW(str(path), True, filters)
                if handle and int(handle) not in {-1, 0xFFFFFFFFFFFFFFFF}:
                    self.change_handle_indexes.add(len(self.handles))
                    self.handles.append(int(handle))

    def wait(self) -> str:
        if self.handles and os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            array_type = ctypes.c_void_p * len(self.handles)
            wait_result = kernel32.WaitForMultipleObjects(
                len(self.handles),
                array_type(*self.handles),
                False,
                int(self.recovery_timeout_seconds * 1000),
            )
            if 0 <= wait_result < len(self.handles):
                if wait_result in self.change_handle_indexes:
                    kernel32.FindNextChangeNotification(ctypes.c_void_p(self.handles[wait_result]))
                    return "workshop_filesystem_event"
                return "queue_wake_event"
            return "recovery_watchdog"
        time.sleep(min(self.recovery_timeout_seconds, 2.0))
        return "portable_recovery_watchdog"

    def close(self) -> None:
        if self.handles and os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            for index, handle in enumerate(self.handles):
                if index in self.change_handle_indexes:
                    kernel32.FindCloseChangeNotification(ctypes.c_void_p(handle))
                else:
                    kernel32.CloseHandle(ctypes.c_void_p(handle))
        self.handles = []


class ProductionQueueDispatcher:
    def __init__(self, center: Any, *, status_writer: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.center = center
        self.status_writer = status_writer

    def _tasks(self) -> list[dict[str, Any]]:
        tasks_root = self.center.root / "tasks"
        result: list[dict[str, Any]] = []
        if not tasks_root.is_dir():
            return result
        for path in tasks_root.glob("*/production-task.json"):
            task = _read_json(path)
            queue = task.get("queue") if isinstance(task.get("queue"), dict) else {}
            if queue.get("schemaVersion") == QUEUE_SCHEMA_VERSION:
                result.append(task)
        result.sort(key=lambda item: (str(item.get("createdAt") or ""), str(item.get("productionTaskId") or "")))
        return result

    def process_once(self) -> dict[str, Any]:
        tasks = self._tasks()
        active = [item for item in tasks if item.get("state") == "RUNNING"]
        candidates = active or [item for item in tasks if item.get("state") in RUNNABLE_STATES]
        if not candidates:
            return {"action": "idle", "queuedCount": 0}
        task = candidates[0]
        task_id = str(task.get("productionTaskId") or "")
        try:
            result = self.center.run_task(task_id)
        except Exception as exc:
            return {"action": "task_error", "productionTaskId": task_id, "error": str(exc)[:500]}
        refreshed = result.get("task") if isinstance(result, dict) else None
        state = str((refreshed or {}).get("state") or task.get("state") or "")
        return {
            "action": "dispatched",
            "productionTaskId": task_id,
            "state": state,
            "laneBlocked": state in WORKSHOP_BLOCKING_STATES or state == "QUEUED_WAITING_WORKSHOP",
            "queuedCount": len([item for item in tasks if item.get("state") in RUNNABLE_STATES]),
        }

    def drain_until_blocked(self, *, max_dispatches: int = 1000) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for _ in range(max_dispatches):
            result = self.process_once()
            results.append(result)
            if result.get("action") in {"idle", "task_error"} or bool(result.get("laneBlocked")):
                return {
                    "action": "drained",
                    "dispatchCount": len([item for item in results if item.get("action") == "dispatched"]),
                    "lastResult": result,
                    "laneBlocked": bool(result.get("laneBlocked")),
                }
        return {
            "action": "drain_limit_reached",
            "dispatchCount": len(results),
            "lastResult": results[-1],
            "laneBlocked": True,
        }


def _acquire_worker_lock(root: Path) -> Path | None:
    path = root / "dispatcher-v2.lock.json"
    payload = {"version": DISPATCHER_VERSION, "pid": os.getpid(), "startedAtEpoch": time.time()}
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = _read_json(path)
        if current.get("version") == DISPATCHER_VERSION and _pid_running(current.get("pid")):
            return None
        try:
            path.unlink()
        except OSError:
            return None
        return _acquire_worker_lock(root)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.write("\n")
    return path


def run_worker(args: argparse.Namespace) -> int:
    from .production import ProductionCenter
    from .workshop_bridge import WorkshopBridge

    data_root = Path(args.data_root).resolve()
    plugin_root = Path(args.plugin_root).resolve()
    isolation_root = Path(args.workshop_isolation_root).resolve()
    root = queue_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_worker_lock(root)
    if lock_path is None:
        return 0
    status_path = root / "dispatcher-status.json"

    def write_status(value: dict[str, Any]) -> None:
        _atomic_json(
            status_path,
            {
                "schemaVersion": QUEUE_SCHEMA_VERSION,
                "version": DISPATCHER_VERSION,
                "pid": os.getpid(),
                "codexHeartbeatDrivesProduction": False,
                "updatedAtEpoch": time.time(),
                **value,
            },
        )

    bridge = WorkshopBridge(Path(args.workshop_executable), isolation_root)
    center = ProductionCenter(data_root, plugin_root=plugin_root, workshop_bridge=bridge)
    dispatcher = ProductionQueueDispatcher(center, status_writer=write_status)
    waiter = DirectoryEventWaiter([isolation_root], wake_event_name=_wake_event_name(data_root))
    try:
        write_status({"status": "RUNNING", "lastWakeReason": "startup"})
        while True:
            # Drain every immediately-runnable task before sleeping.  A task
            # that just reached VIDEO_READY hands the single workshop lane to
            # the next queued task in this same wake cycle.
            drain = dispatcher.drain_until_blocked()
            write_status({"status": "RUNNING", "lastResult": drain.get("lastResult"), "lastDrain": drain})
            reason = waiter.wait()
            if reason == "workshop_filesystem_event":
                # The notification may fire when the Workshop creates its
                # temporary JSON file, just before replacing the canonical
                # project file. Let that short atomic-save window finish so a
                # read-only status check does not hold the destination open on
                # Windows.
                time.sleep(0.15)
            write_status({"status": "RUNNING", "lastWakeReason": reason})
    finally:
        waiter.close()
        write_status({"status": "STOPPED"})
        current = _read_json(lock_path)
        if int(current.get("pid") or 0) == os.getpid():
            lock_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--workshop-executable", required=True)
    parser.add_argument("--workshop-isolation-root", required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(run_worker(build_parser().parse_args()))
