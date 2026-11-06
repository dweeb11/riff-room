"""riff-room backend routes, mounted at /api/plugins/riff-room/.

Hermes imports this file on its own (not as part of the plugin package), so the
shared store module is loaded from the package root by path. Handlers are plain
`def` so FastAPI runs them off the event loop (they take a file lock). Every
response is the board as the *user* may see it (board.view), never the raw file.
"""

import functools
import importlib.util
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def _load_store():
    path = Path(__file__).resolve().parent.parent / "store.py"
    spec = importlib.util.spec_from_file_location("riff_room_store", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


store = _load_store()
B = store.board
router = APIRouter()
logger = logging.getLogger(__name__)


def _json_errors(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except B.BoardError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            logger.exception("riff-room route %s failed", fn.__name__)
            return JSONResponse({"error": f"{fn.__name__} failed: {e}"}, status_code=500)
    return wrapped


def _user_view(board):
    return B.view(board, "user")


@router.get("/health")
@_json_errors
def health():
    return {"ok": True, "plugin": store.PLUGIN_ID}


@router.get("/boards")
@_json_errors
def list_boards(session_id: str | None = None):
    return {"boards": store.boards().list(session_id)}


@router.get("/board/{board_id}")
@_json_errors
def get_board(board_id: str):
    return _user_view(store.boards().get(board_id))


@router.post("/board/{board_id}/round/start")
@_json_errors
def start_round(board_id: str, body: dict | None = None):
    duration = (body or {}).get("duration_s", B.DEFAULT_BURST_S)
    board, _ = store.boards().start_round(board_id, duration)
    return _user_view(board)


@router.post("/board/{board_id}/flip")
@_json_errors
def flip(board_id: str):
    board, flipped = store.boards().flip(board_id)
    return {"flipped_now": flipped, "board": _user_view(board)}


@router.post("/board/{board_id}/announce")
@_json_errors
def announce(board_id: str, body: dict):
    """Claim the one chat message for an event (e.g. {"key": "flip:2"}); only the first caller gets claimed=true."""
    key = str(body.get("key", ""))
    if not key:
        raise B.BoardError("key is required")
    _, claimed = store.boards().claim_announcement(board_id, key)
    return {"claimed": claimed}


@router.post("/board/{board_id}/notes")
@_json_errors
def add_note(board_id: str, body: dict):
    board, added = store.boards().add_notes(board_id, "user", [{"text": body.get("text"),
                                                                "spark_of": body.get("spark_of")}])
    return {"added": added[0], "board": _user_view(board)}


@router.patch("/board/{board_id}/note/{note_id}")
@_json_errors
def edit_note(board_id: str, note_id: str, body: dict):
    board, _ = store.boards().edit_note(board_id, note_id, body.get("text"), actor="user")
    return _user_view(board)


@router.post("/board/{board_id}/star")
@_json_errors
def star(board_id: str, body: dict):
    board, _ = store.boards().star(board_id, body.get("note_id"), body.get("starred", True))
    return _user_view(board)


@router.post("/board/{board_id}/move")
@_json_errors
def move(board_id: str, body: dict):
    board, _ = store.boards().sort(board_id, moves=[{"note_id": body.get("note_id"), "bucket": body.get("bucket")}],
                                   actor="user")
    return _user_view(board)


@router.post("/board/{board_id}/export")
@_json_errors
def export(board_id: str):
    path, md = store.write_export(board_id)
    return {"path": str(path), "markdown": md}
