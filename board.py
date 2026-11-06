"""Board model and store: the single source of truth for tools, routes and the hook.

Self-contained on purpose: dashboard/plugin_api.py loads this file by path, so it
uses no relative imports and no Hermes imports. Two copies of it can be live at
once, which is why writes are serialised with a file lock, not a module lock.

One JSON file per board under <root>/boards/. Every write bumps `version`.
The round timer is server-authoritative (`ends_at`); any load after `ends_at`
flips the round, so the pane, a read or a tool call can each trigger the flip and
the first one wins.
"""

import contextlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: no flock; single-writer assumption
    fcntl = None

NOTE_MAX = 140
TOPIC_MAX = 200
BUCKET_NAME_MAX = 40
MAX_BUCKETS = 8
MAX_BATCH = 12
MAX_NOTES = 300
DEFAULT_BURST_S = 180
MIN_ROUND_S, MAX_ROUND_S = 30, 1800
TRICKLE_FRACTION = 0.7  # agent card backs land across the first 70% of a burst
AUTHORS = ("user", "agent")

_BOARD_ID = re.compile(r"^b_[0-9a-f]{8}$")


class BoardError(ValueError):
    """A request the board refuses; the message is safe to show the caller."""


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _utcnow():
    return datetime.now(timezone.utc)


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class BoardStore:
    def __init__(self, root, on_change=None, now=_utcnow):
        self.dir = Path(root) / "boards"
        self.on_change = on_change  # fn(board_id, version, origin)
        self.now = now

    # ── storage ──────────────────────────────────────────────────────────

    def _path(self, board_id):
        if not isinstance(board_id, str) or not _BOARD_ID.match(board_id):
            raise BoardError(f"invalid board id: {board_id!r}")
        return self.dir / f"{board_id}.json"

    @contextlib.contextmanager
    def _locked(self, board_id):
        path = self._path(board_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / f".{board_id}.lock", "a") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield path
            finally:
                if fcntl:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise BoardError(f"no such board: {path.stem}") from None

    def _write(self, path, board):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(board, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _commit(self, path, board, origin):
        board["version"] += 1
        self._write(path, board)
        if self.on_change:
            self.on_change(board["id"], board["version"], origin)

    def _flip_due(self, board, now):
        """Flip a running round whose time is up. Returns True when it flipped one."""
        r = current_round(board)
        if r and r["state"] == "running" and now >= _parse(r["ends_at"]):
            _flip(board, r, now)
            return True
        return False

    def mutate(self, board_id, fn, origin):
        """Lock, load, lazy-flip, apply fn(board, now) and save. Returns (board, fn's result)."""
        with self._locked(board_id) as path:
            board = self._read(path)
            now = self.now()
            self._flip_due(board, now)
            result = fn(board, now)
            self._commit(path, board, origin)
            return board, result

    def get(self, board_id, origin="read"):
        """Load a board; flips (and saves) a round whose time is up."""
        with self._locked(board_id) as path:
            board = self._read(path)
            if self._flip_due(board, self.now()):
                self._commit(path, board, origin)
            return board

    def list(self, session_id=None):
        if not self.dir.exists():
            return []
        out = []
        for p in self.dir.glob("b_*.json"):
            try:
                b = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if session_id is None or b.get("session_id") == session_id:
                out.append({k: b.get(k) for k in ("id", "topic", "session_id", "created", "version")})
        return sorted(out, key=lambda b: b["created"] or "", reverse=True)

    # ── operations ───────────────────────────────────────────────────────

    def create(self, topic, buckets=None, session_id=None, origin="agent"):
        topic = _clip(topic, TOPIC_MAX)
        if not topic:
            raise BoardError("topic is required")
        board_id = "b_" + secrets.token_hex(4)
        board = {
            "id": board_id, "version": 0, "topic": topic, "session_id": session_id,
            "created": _iso(self.now()), "buckets": [], "rounds": [], "notes": [],
            "announced": [], "reel": None,
        }
        _add_buckets(board, buckets or [])
        with self._locked(board_id) as path:
            self._commit(path, board, origin)
        return board

    def start_round(self, board_id, duration_s=DEFAULT_BURST_S, kind="burst", origin="user"):
        def fn(board, now):
            r = current_round(board)
            if r and r["state"] == "running":
                raise BoardError(f"round {r['n']} is still running")
            d = int(duration_s)
            if not MIN_ROUND_S <= d <= MAX_ROUND_S:
                raise BoardError(f"duration_s must be {MIN_ROUND_S}–{MAX_ROUND_S}")
            r = {"n": len(board["rounds"]) + 1, "kind": kind, "duration_s": d,
                 "started_at": _iso(now), "ends_at": _iso(now + timedelta(seconds=d)),
                 "state": "running", "flipped_at": None}
            board["rounds"].append(r)
            return r
        return self.mutate(board_id, fn, origin)

    def flip(self, board_id, origin="user"):
        """End the running round now. Idempotent: result is True only for the call that flipped."""
        with self._locked(board_id) as path:
            board = self._read(path)
            now = self.now()
            flipped = self._flip_due(board, now)
            r = current_round(board)
            if not flipped and r and r["state"] == "running":
                _flip(board, r, now)
                flipped = True
            if flipped:
                self._commit(path, board, origin)
            return board, flipped

    def claim_announcement(self, board_id, key, origin="user"):
        """First caller for `key` (e.g. "flip:2") gets True; everyone after gets False."""
        def fn(board, now):
            if key in board["announced"]:
                return False
            board["announced"].append(key)
            return True
        return self.mutate(board_id, fn, origin)

    def add_notes(self, board_id, author, notes, origin=None):
        if author not in AUTHORS:
            raise BoardError(f"author must be one of {AUTHORS}")
        if not isinstance(notes, list) or not notes:
            raise BoardError("notes must be a non-empty list")
        if len(notes) > MAX_BATCH:
            raise BoardError(f"at most {MAX_BATCH} notes per call")

        def fn(board, now):
            if len(board["notes"]) + len(notes) > MAX_NOTES:
                raise BoardError(f"board is full ({MAX_NOTES} notes)")
            r = current_round(board)
            running = bool(r and r["state"] == "running")
            visible = {n["id"] for n in board["notes"] if can_see_text(n, author)}
            reveals = _trickle(r, now, len(notes)) if running and author == "agent" else [now] * len(notes)
            added = []
            for item, reveal in zip(notes, reveals):
                item = item if isinstance(item, dict) else {"text": item}
                text = _clip(item.get("text"), NOTE_MAX)
                if not text:
                    raise BoardError("note text is empty")
                spark = item.get("spark_of")
                if spark is not None and spark not in visible:
                    raise BoardError(f"spark_of {spark!r} is not a note you can see")
                note = {"id": f"n{len(board['notes']) + 1}", "text": text, "author": author,
                        "round": r["n"] if r else 0, "bucket": None, "face_down": running,
                        "reveal_at": _iso(reveal) if running else None, "starred": False,
                        "spark_of": spark, "dimmed": False}
                board["notes"].append(note)
                added.append(note)
            return added
        return self.mutate(board_id, fn, origin or author)

    def edit_note(self, board_id, note_id, text, actor="user"):
        def fn(board, now):
            note = _note(board, note_id)
            if note["author"] != actor:
                raise BoardError("you can only edit your own notes")
            note["text"] = _clip(text, NOTE_MAX) or note["text"]
            return note
        return self.mutate(board_id, fn, actor)

    def sort(self, board_id, moves=(), new_buckets=(), dim=(), actor="agent"):
        def fn(board, now):
            created = _add_buckets(board, new_buckets or [])
            for m in moves or []:
                note = _note(board, m.get("note_id"))
                if not can_see_text(note, actor):
                    raise BoardError(f"{note['id']} is face-down; sort after the flip")
                note["bucket"] = _bucket_id(board, m.get("bucket"))
            for nid in dim or []:
                _note(board, nid)["dimmed"] = True
            return created
        return self.mutate(board_id, fn, actor)

    def star(self, board_id, note_id, starred=True):
        """Stars are the user's; only the pane calls this."""
        def fn(board, now):
            note = _note(board, note_id)
            if not can_see_text(note, "user"):
                raise BoardError("can't star a face-down card")
            note["starred"] = bool(starred)
            return note
        return self.mutate(board_id, fn, "user")

    def export_markdown(self, board_id, origin="read"):
        """Markdown of the whole board. Refused mid-round: it would expose face-down text."""
        board = self.get(board_id, origin)
        r = current_round(board)
        if r and r["state"] == "running":
            raise BoardError("a round is still running; export after the flip")
        return board, to_markdown(board)

    def reel_in(self, board_id, clusters, heat_note_ids, next_step, actor="agent"):
        def fn(board, now):
            r = current_round(board)
            if r and r["state"] == "running":
                raise BoardError("a round is still running; end it before reeling in")
            if not str(next_step or "").strip():
                raise BoardError("next_step is required")
            out = []
            for c in clusters or []:
                ids = [_note(board, nid)["id"] for nid in c.get("note_ids", [])]
                out.append({"name": _clip(c.get("name"), BUCKET_NAME_MAX) or "Cluster", "note_ids": ids})
            if not out:
                raise BoardError("at least one cluster is required")
            heat = [_note(board, nid)["id"] for nid in heat_note_ids or []]
            board["reel"] = {"clusters": out, "heat_note_ids": heat,
                             "next_step": _clip(next_step, 280), "at": _iso(now)}
            return board["reel"]
        return self.mutate(board_id, fn, actor)


# ── board helpers (pure) ─────────────────────────────────────────────────

def current_round(board):
    return board["rounds"][-1] if board["rounds"] else None


def _flip(board, r, now):
    r["state"] = "flipped"
    r["flipped_at"] = _iso(now)
    for n in board["notes"]:
        if n["round"] == r["n"]:
            n["face_down"] = False


def _trickle(r, now, k):
    """Reveal times for k agent notes: spread from now to 70% of the round."""
    start = _parse(r["started_at"])
    window_end = start + timedelta(seconds=r["duration_s"] * TRICKLE_FRACTION)
    span = max((window_end - now).total_seconds(), 0.0)
    if k == 1 or span == 0:
        return [now] * k
    return [now + timedelta(seconds=span * i / (k - 1)) for i in range(k)]


def _note(board, note_id):
    for n in board["notes"]:
        if n["id"] == note_id:
            return n
    raise BoardError(f"no such note: {note_id!r}")


def _add_buckets(board, names):
    created = []
    for name in names:
        name = _clip(name, BUCKET_NAME_MAX)
        if not name or any(b["name"].lower() == name.lower() for b in board["buckets"]):
            continue
        if len(board["buckets"]) >= MAX_BUCKETS:
            raise BoardError(f"at most {MAX_BUCKETS} buckets")
        b = {"id": f"k{len(board['buckets']) + 1}", "name": name}
        board["buckets"].append(b)
        created.append(b)
    return created


def _bucket_id(board, ref):
    """Bucket by id or (case-insensitive) name; None/"" means the unsorted tray."""
    if ref in (None, "", "unsorted"):
        return None
    for b in board["buckets"]:
        if ref == b["id"] or str(ref).lower() == b["name"].lower():
            return b["id"]
    raise BoardError(f"no such bucket: {ref!r}")


# ── views: the no-anchoring rule lives here ──────────────────────────────

def can_see_text(note, viewer):
    """Face-down notes are readable only by their author until the flip."""
    return not note["face_down"] or note["author"] == viewer


def view(board, viewer, now=None):
    """The board as `viewer` may see it. Routes and tools must never return a raw board.

    Face-down notes by the other author lose their text. For the user, agent notes
    whose reveal_at is still ahead are left out entirely (their card back has not
    landed yet).
    """
    now = now or _utcnow()
    notes = []
    for n in board["notes"]:
        if viewer == "user" and n["author"] == "agent" and n["face_down"] \
                and n["reveal_at"] and _parse(n["reveal_at"]) > now:
            continue
        n = dict(n)
        if not can_see_text(n, viewer):
            n["text"] = None
            n["spark_of"] = None
        notes.append(n)
    return {**board, "notes": notes, "server_now": _iso(now)}


def time_left_s(board, now=None):
    r = current_round(board)
    if not r or r["state"] != "running":
        return None
    return max(0, int((_parse(r["ends_at"]) - (now or _utcnow())).total_seconds()))


def summary(board, viewer="agent", now=None, limit=2000):
    """Compact text for the model, under `limit` characters."""
    now = now or _utcnow()
    v = view(board, viewer, now)
    r = current_round(board)
    if not r:
        round_line = "No rounds yet (the user starts a burst from the pane)."
    elif r["state"] == "running":
        left = time_left_s(board, now)
        round_line = f"Round {r['n']} · {r['kind']} · running · {left // 60}:{left % 60:02d} left"
    else:
        round_line = f"Round {r['n']} · {r['kind']} · flipped"
    lines = [f"Board {board['id']} · \"{board['topic']}\"", round_line]
    if board["buckets"]:
        lines.append("Buckets: " + ", ".join(f"{b['id']} {b['name']}" for b in board["buckets"]))

    hidden = [n for n in v["notes"] if n["text"] is None]
    shown = [n for n in v["notes"] if n["text"] is not None]

    def fmt(n):
        mark = " ★" if n["starred"] else ""
        spark = f" ←{n['spark_of']}" if n["spark_of"] else ""
        down = " (face-down)" if n["face_down"] else ""
        return f"  {n['id']} [{n['author']}]{mark}{down}{spark} {n['text']}"

    groups = [("Unsorted", None)] + [(f"{b['id']} {b['name']}", b["id"]) for b in board["buckets"]]
    for title, bid in groups:
        rows = [fmt(n) for n in shown if n["bucket"] == bid and not n["dimmed"]]
        if rows:
            lines.append(f"{title}:")
            lines.extend(rows)
    parked = [fmt(n) for n in shown if n["dimmed"]]
    if parked:
        lines.append("Parked (dimmed):")
        lines.extend(parked)
    if hidden:
        lines.append(f"Face-down from the other side: {len(hidden)} note(s), hidden until the flip.")
    if board["reel"]:
        lines.append("Reeled in. Next step: " + board["reel"]["next_step"])

    out = "\n".join(lines)
    if len(out) > limit:
        cut = out[: limit - 60].rsplit("\n", 1)[0]
        out = cut + f"\n… truncated ({len(out) - len(cut)} chars); use view=\"full\"."
    return out


def to_markdown(board):
    """Export: topic, buckets with notes (★), Parked, and the reel-in map + next step."""
    notes = [n for n in board["notes"]]
    by_id = {n["id"]: n for n in notes}

    def item(n):
        star = "★ " if n["starred"] else ""
        who = "Hermes" if n["author"] == "agent" else "you"
        spark = f" *(sparked by {n['spark_of']})*" if n["spark_of"] else ""
        return f"- {star}{n['text']} — {who} `{n['id']}`{spark}"

    out = [f"# {board['topic']}", "", f"*riff-room board `{board['id']}` · {board['created'][:10]} · "
           f"{len(board['rounds'])} round(s) · {len(notes)} notes*", ""]
    groups = [(b["name"], b["id"]) for b in board["buckets"]] + [("Unsorted", None)]
    for name, bid in groups:
        rows = [item(n) for n in notes if n["bucket"] == bid and not n["dimmed"]]
        if rows:
            out += [f"## {name}", "", *rows, ""]
    parked = [item(n) for n in notes if n["dimmed"]]
    if parked:
        out += ["## Parked", "", *parked, ""]
    reel = board["reel"]
    if reel:
        out += ["## Reel-in map", ""]
        for c in reel["clusters"]:
            out.append(f"**{c['name']}**")
            out += [f"- {by_id[i]['text']}" for i in c["note_ids"] if i in by_id]
            out.append("")
        heat = [by_id[i]["text"] for i in reel["heat_note_ids"] if i in by_id]
        if heat:
            out += ["**Heat:** " + " · ".join(heat), ""]
        out += [f"**Next step:** {reel['next_step']}", ""]
    return "\n".join(out)
