"""Storage and event helpers shared by tools and routes.

Everything riff-room writes lives under plugin_data_dir("riff-room").
"""

import json
import logging
import os
import tempfile
from pathlib import Path

PLUGIN_ID = "riff-room"
logger = logging.getLogger(__name__)


def data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_ID)


def write_json(path: Path, obj) -> None:
    """Atomic write: temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def broadcast(event: str, payload: dict) -> None:
    """Push plugin.riff-room.<event> to connected Desktop windows; never raises."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_ID, event, payload)
    except Exception:
        logger.warning("riff-room: broadcast %s failed", event, exc_info=True)
