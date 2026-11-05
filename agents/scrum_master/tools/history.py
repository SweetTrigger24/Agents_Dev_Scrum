"""Track blocker observations. Missing tasks are not evidence of resolution."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def normalize_tasks(context: dict) -> list[dict]:
    tasks = context.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("context.tasks phải là danh sách")
    result, ids = [], set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Mỗi task phải là object")
        task_id = task.get("id", task.get("task_id"))
        if not isinstance(task_id, str) or not task_id.strip() or task_id in ids:
            raise ValueError("Task cần ID chuỗi, không rỗng và không trùng")
        status = task.get("status", "UNKNOWN")
        reason = task.get("blocked_reason")
        reason = "" if reason is None else reason
        if not isinstance(status, str) or not isinstance(reason, str):
            raise ValueError("status và blocked_reason phải là chuỗi")
        ids.add(task_id)
        result.append({"id": task_id, "status": status.strip().upper(),
                       "name": str(task.get("name", task.get("title", "")) or ""),
                       "blocked_reason": reason.strip()})
    return result


def observe(data_dir: str, project_id: str, task_id: str, tasks: list[dict], now=None, snapshot_provided=True):
    """Prepare a state update; caller commits only after producing the report."""
    now = now or datetime.now(timezone.utc)
    path = Path(data_dir) / "scrum_history" / (hashlib.sha256(project_id.encode()).hexdigest() + ".json")
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "project_id": project_id, "records": {}, "snapshots": 0,
    }
    if state.get("project_id") != project_id:
        raise ValueError("History project mismatch")
    if state.get("last_request") == task_id:
        return state["last_summary"], path, state
    records = state["records"]
    summary = {"new": [], "persistent": [], "resolved": [], "not_observed": [],
               "observed_at": now.isoformat(), "snapshot_provided": snapshot_provided,
               "snapshot_count": state["snapshots"] + int(snapshot_provided)}
    seen = set()
    for task in tasks:
        key = task["id"]
        seen.add(key)
        blocked = task["status"] in ("BLOCKED", "FAILED") or bool(task["blocked_reason"])
        previous = records.get(key)
        if blocked:
            ongoing = previous and previous["active"]
            record = dict(previous) if ongoing else {"id": key, "first_seen": now.isoformat(), "observations": 0}
            record.update(active=True, last_seen=now.isoformat(), reason=task["blocked_reason"] or task["status"],
                          observations=record["observations"] + 1, resolved_at=None)
            record["observed_age_seconds"] = max(0, int((now - datetime.fromisoformat(record["first_seen"])).total_seconds()))
            records[key] = record
            summary["persistent" if ongoing else "new"].append(dict(record))
        elif previous and previous["active"]:
            # UNKNOWN or arbitrary status is not affirmative evidence of unblocking.
            if task["status"] in ("PENDING", "RUNNING", "COMPLETED", "DONE", "CANCELLED", "SKIPPED"):
                previous.update(active=False, resolved_at=now.isoformat())
                summary["resolved"].append(dict(previous))
            else:
                summary["not_observed"].append(dict(previous))
    summary["not_observed"] += [dict(record) for key, record in records.items() if key not in seen and record["active"]]
    state.update(snapshots=summary["snapshot_count"], last_request=task_id, last_summary=summary)
    return summary, path, state


def commit(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
