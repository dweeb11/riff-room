"""riff-room backend routes, mounted at /api/plugins/riff-room/.

Hermes imports this file on its own (not as part of the plugin package), so the
shared store module is loaded from the package root by path.
"""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter


def _load_sibling(name: str):
    path = Path(__file__).resolve().parent.parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"riff_room_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


store = _load_sibling("store")
router = APIRouter()


@router.get("/health")
async def health():
    return {"ok": True, "plugin": store.PLUGIN_ID}


@router.get("/verify")
async def verify():
    """Last riff_ping record (what session_id a tool call received)."""
    return {"ok": True, "last_tool_ping": store.read_json(store.data_dir() / "verify.json")}


@router.post("/ping")
async def ping(body: dict):
    """Broadcast a test event from a route, echoing what the pane sent."""
    payload = {"at": datetime.now(timezone.utc).isoformat(), "origin": "route", "echo": body}
    store.broadcast("ping", payload)
    return {"ok": True, **payload}
