"""Tools and routes against a temp data dir. Needs Hermes's runtime (FastAPI):

    hermes --run-module unittest discover -s tests

Skipped under a bare python3 that lacks FastAPI.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # bare python3
    FastAPI = None


def _load(name, path, package_dir=None):
    kw = {"submodule_search_locations": [str(package_dir)]} if package_dir else {}
    spec = importlib.util.spec_from_file_location(name, path, **kw)
    mod = importlib.util.module_from_spec(spec)
    if package_dir:
        sys.modules[name] = mod  # so `from . import store` resolves inside the package
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(FastAPI is None, "needs Hermes runtime (FastAPI)")
class TestToolsAndRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = []
        self.pkg = _load("riffroom_test_pkg", ROOT / "__init__.py", package_dir=ROOT)
        self.api = _load("riffroom_test_api", ROOT / "dashboard" / "plugin_api.py")
        for store in (self.pkg.tools.store, self.api.store):  # two live copies, one data dir
            store.data_dir = lambda: Path(self.tmp.name)
            store.broadcast = lambda event, payload: self.events.append((event, payload))
        app = FastAPI()
        app.include_router(self.api.router, prefix="/api/plugins/riff-room")
        self.client = TestClient(app)

    def tearDown(self):
        sys.modules.pop("riffroom_test_pkg", None)
        self.tmp.cleanup()

    def tool(self, name, args, **kw):
        return json.loads(getattr(self.pkg.tools, name)(args, **kw))

    def http(self, method, path, **kw):
        return self.client.request(method, f"/api/plugins/riff-room{path}", **kw)

    def test_agent_and_pane_share_a_board(self):
        made = self.tool("riff_new_board", {"topic": "skills", "buckets": ["combat"]}, session_id="local-s1")
        bid = made["board_id"]

        listed = self.http("GET", "/boards", params={"session_id": "local-s1"}).json()
        self.assertEqual([b["id"] for b in listed["boards"]], [bid])

        self.assertEqual(self.http("POST", f"/board/{bid}/round/start", json={"duration_s": 60}).status_code, 200)
        self.http("POST", f"/board/{bid}/notes", json={"text": "USER SECRET"})
        self.tool("riff_add_notes", {"board_id": bid, "notes": [{"text": "AGENT SECRET"}]})

        self.assertNotIn("USER SECRET", json.dumps(self.tool("riff_get_board", {"board_id": bid})))
        self.assertNotIn("USER SECRET", json.dumps(self.tool("riff_get_board", {"board_id": bid, "view": "full"})))
        self.assertNotIn("AGENT SECRET", self.http("GET", f"/board/{bid}").text)

        flip = self.http("POST", f"/board/{bid}/flip").json()
        self.assertTrue(flip["flipped_now"])
        self.assertFalse(self.http("POST", f"/board/{bid}/flip").json()["flipped_now"])
        claims = [self.http("POST", f"/board/{bid}/announce", json={"key": "flip:1"}).json()["claimed"] for _ in range(2)]
        self.assertEqual(claims, [True, False])
        self.assertIn("AGENT SECRET", self.http("GET", f"/board/{bid}").text)

        self.http("POST", f"/board/{bid}/star", json={"note_id": "n1"})
        self.http("POST", f"/board/{bid}/move", json={"note_id": "n2", "bucket": "combat"})
        self.assertIn("★", self.tool("riff_get_board", {"board_id": bid})["summary"])

        reel = self.tool("riff_reel_in", {"board_id": bid, "clusters": [{"name": "c", "note_ids": ["n1", "n2"]}],
                                          "heat_note_ids": ["n1"], "next_step": "build it"})
        self.assertTrue(reel["ok"])
        out = self.tool("riff_export", {"board_id": bid})
        path = Path(out["path"])
        self.assertTrue(path.is_relative_to(self.tmp.name), "writes only under the data dir")
        self.assertIn("**Next step:** build it", path.read_text())

        changed = [p for e, p in self.events if e == "board.changed"]
        self.assertTrue(changed and all(p["board_id"] == bid for p in changed))
        self.assertEqual([p["version"] for p in changed], sorted({p["version"] for p in changed}))

    def test_flip_hook_tells_the_agent_once(self):
        hook = self.pkg.tools.on_pre_llm_call
        bid = self.tool("riff_new_board", {"topic": "hooks"}, session_id="local-s1")["board_id"]
        self.assertIsNone(hook(session_id="local-s1"), "no round yet")
        self.http("POST", f"/board/{bid}/round/start", json={"duration_s": 60})
        self.http("POST", f"/board/{bid}/notes", json={"text": "USER IDEA"})
        self.assertIsNone(hook(session_id="local-s1"), "running round: nothing to tell")
        self.http("POST", f"/board/{bid}/flip")

        self.assertIsNone(hook(session_id="local-other"), "other sessions hear nothing")
        ctx = hook(session_id="local-s1")["context"]
        self.assertIn(f"Round 1 on board {bid} flipped", ctx)
        self.assertIn("USER IDEA", ctx, "the face-up board comes with it")
        self.assertIsNone(hook(session_id="local-s1"), "told once")
        self.assertIsNone(hook(), "no session id")

        self.http("POST", f"/board/{bid}/round/start", json={"duration_s": 60})
        self.http("POST", f"/board/{bid}/notes", json={"text": "SECOND SECRET"})
        self.assertIsNone(hook(session_id="local-s1"))
        self.http("POST", f"/board/{bid}/flip")
        self.assertIn("Round 2", hook(session_id="local-s1")["context"])

    def test_pane_note_is_one_user_note(self):
        bid = self.tool("riff_new_board", {"topic": "entry"}, session_id="local-s1")["board_id"]
        self.http("POST", f"/board/{bid}/round/start", json={"duration_s": 60})
        res = self.http("POST", f"/board/{bid}/notes", json={"text": "mine"}).json()
        self.assertEqual(res["added"]["author"], "user")
        self.assertEqual([(n["author"], n["text"]) for n in res["board"]["notes"]], [("user", "mine")])
        self.assertTrue(res["board"]["notes"][0]["face_down"])
        self.assertEqual(self.http("POST", f"/board/{bid}/notes", json={"text": "  "}).status_code, 400)

    def test_errors_are_json_never_raised(self):
        self.assertIn("error", self.tool("riff_get_board", {"board_id": "../../etc/passwd"}))
        self.assertIn("error", self.tool("riff_add_notes", {"board_id": "b_00000000", "notes": [{"text": "x"}]}))
        self.assertIn("error", self.tool("riff_new_board", {}))
        self.assertIn("error", self.tool("riff_sort", None))
        r = self.http("GET", "/board/b_00000000")
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())
        self.assertEqual(self.http("POST", "/board/b_00000000/announce", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
