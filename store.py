"""Hermes-side glue shared by tools and routes: data dir, board store, events.

Everything riff-room writes lives under plugin_data_dir("riff-room").
Loaded by path from dashboard/plugin_api.py, so no relative imports here.
"""

import importlib.util
import logging
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ID = "riff-room"
logger = logging.getLogger(__name__)


def _load_board_module():
    spec = importlib.util.spec_from_file_location("riff_room_board", Path(__file__).with_name("board.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


board = _load_board_module()


def data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_ID)


def broadcast(event: str, payload: dict) -> None:
    """Push plugin.riff-room.<event> to connected Desktop windows; never raises."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_ID, event, payload)
    except Exception:
        logger.warning("riff-room: broadcast %s failed", event, exc_info=True)


def _changed(board_id, version, origin):
    broadcast("board.changed", {"board_id": board_id, "version": version, "origin": origin})


def boards():
    """A store bound to the active profile's data dir (resolved per call)."""
    return board.BoardStore(data_dir(), on_change=_changed)


def write_export(board_id):
    """Write exports/<id>-<stamp>.md; returns (path, markdown). Used by the tool and the route."""
    b, md = boards().export_markdown(board_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = data_dir() / "exports" / f"{b['id']}-{stamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    return path, md
