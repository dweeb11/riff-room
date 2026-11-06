"""Tool handlers. Each returns a JSON string and never raises."""

import json
from datetime import datetime, timezone

from . import store


def riff_ping(args: dict, **kwargs) -> str:
    try:
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "origin": "tool",
            "session_id": kwargs.get("session_id"),
            "task_id": kwargs.get("task_id"),
            "kwarg_keys": sorted(kwargs),
        }
        store.write_json(store.data_dir() / "verify.json", record)
        store.broadcast("ping", record)
        return json.dumps({"ok": True, **record})
    except Exception as e:
        return json.dumps({"error": f"riff_ping failed: {e}"})
