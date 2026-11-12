"""Tool handlers (each returns a JSON string and never raises) and the pre_llm_call hook."""

import functools
import json
import logging

from . import store

logger = logging.getLogger(__name__)


def _handler(fn):
    @functools.wraps(fn)
    def wrapped(args, **kwargs):
        try:
            return json.dumps(fn(args or {}, **kwargs), ensure_ascii=False)
        except store.board.BoardError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("riff-room: %s failed", fn.__name__)
            return json.dumps({"error": f"{fn.__name__} failed: {e}"})
    return wrapped


@_handler
def riff_new_board(args, session_id=None, **_):
    b = store.boards().create(args.get("topic"), args.get("buckets"), session_id=session_id)
    return {"board_id": b["id"], "topic": b["topic"], "buckets": b["buckets"],
            "next": ("Tell the user the board is in the riff-room pane; they press Start there to begin a "
                     "timed burst. Their ideas go in the pane's note field, which opens during a burst "
                     "(Enter adds one), not in chat; chat is for talking it over.")}


@_handler
def riff_add_notes(args, **_):
    b, added = store.boards().add_notes(args.get("board_id"), "agent", args.get("notes"))
    r = store.board.current_round(b)
    return {"added": [{"id": n["id"], "face_down": n["face_down"]} for n in added],
            "round": r and {"n": r["n"], "state": r["state"]},
            "time_left_s": store.board.time_left_s(b)}


@_handler
def riff_get_board(args, **_):
    b = store.boards().get(args.get("board_id"))
    if args.get("view") == "full":
        return store.board.view(b, "agent")
    return {"summary": store.board.summary(b, "agent")}


@_handler
def riff_sort(args, **_):
    b, created = store.boards().sort(args.get("board_id"), args.get("moves"), args.get("new_buckets"),
                                     args.get("dim"), actor="agent")
    return {"ok": True, "created_buckets": created, "version": b["version"]}


@_handler
def riff_reel_in(args, **_):
    b, reel = store.boards().reel_in(args.get("board_id"), args.get("clusters"),
                                     args.get("heat_note_ids"), args.get("next_step"))
    return {"ok": True, "reel": reel}


@_handler
def riff_export(args, **_):
    path, md = store.write_export(args.get("board_id"))
    return {"path": str(path), "chars": len(md)}


def on_pre_llm_call(session_id=None, **_):
    """Before each agent turn: one note per round that flipped since the agent was last told.

    A hook can't start a turn, so this lands on the agent's next turn, whoever starts it. Each flip
    is told once (claimed as "agent:flip:<n>", apart from the pane's own "flip:<n>" chat message).
    Reading the board lazy-flips a round whose time ran out with no pane open. Never raises.
    """
    try:
        if not session_id:
            return None
        s = store.boards()
        parts = []
        for meta in s.list(session_id):
            b = s.get(meta["id"])
            r = store.board.current_round(b)
            key = r and f"agent:flip:{r['n']}"
            if not r or r["state"] != "flipped" or key in b["announced"]:
                continue
            b, claimed = s.claim_announcement(b["id"], key, origin="hook")
            if claimed:
                parts.append(
                    f"[riff-room] Round {r['n']} on board {b['id']} flipped: every note is face-up now. "
                    "The user stars and drag-sorts in the pane and presses Reel it in when ready. "
                    "Riff on what flipped.\n" + store.board.summary(b, "agent"))
        return {"context": "\n\n".join(parts)} if parts else None
    except Exception:
        logger.warning("riff-room: pre_llm_call hook failed", exc_info=True)
        return None
