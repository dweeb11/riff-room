"""Board model tests. Stdlib only; run: python3 -m unittest discover -s tests"""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("riff_room_board_t", ROOT / "board.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

T0 = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += timedelta(seconds=s)


class BoardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.events = []
        self.store = B.BoardStore(self.tmp.name, on_change=lambda *e: self.events.append(e), now=self.clock)
        self.board = self.store.create("skills system", ["combat", "exploration"], session_id="local-abc")
        self.bid = self.board["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def versions(self):
        return [v for _, v, _ in self.events]


class TestLifecycle(BoardTestCase):
    """Acceptance 2: create → notes → round → lazy flip (idempotent) → sort → reel → export."""

    def test_full_lifecycle(self):
        s, bid, clock = self.store, self.bid, self.clock
        self.assertEqual([b["name"] for b in self.board["buckets"]], ["combat", "exploration"])

        s.start_round(bid, 180)
        s.add_notes(bid, "user", [{"text": "parry chains"}])
        s.add_notes(bid, "agent", [{"text": "skills decay unless used"}, {"text": "steal a skill from a boss"}])

        clock.advance(181)
        board = s.get(bid)  # a plain read after ends_at flips
        self.assertEqual(board["rounds"][0]["state"], "flipped")
        self.assertTrue(all(not n["face_down"] for n in board["notes"]))
        v_after_flip = board["version"]

        _, flipped_again = s.flip(bid)  # the pane's /flip arrives late: no-op
        self.assertFalse(flipped_again)
        self.assertEqual(s.get(bid)["version"], v_after_flip)

        s.sort(bid, moves=[{"note_id": "n1", "bucket": "combat"}, {"note_id": "n3", "bucket": "k2"}],
               new_buckets=["social"], dim=["n2"])
        s.star(bid, "n1")
        s.add_notes(bid, "agent", [{"text": "parry into a counter-skill", "spark_of": "n1"}])
        s.reel_in(bid, [{"name": "Combat feel", "note_ids": ["n1", "n4"]}], ["n1"], "Prototype parry chains")

        board, md = s.export_markdown(bid)
        self.assertIn("# skills system", md)
        self.assertIn("## combat", md)
        self.assertIn("- ★ parry chains", md)
        self.assertIn("## Parked", md)
        self.assertIn("skills decay unless used", md.split("## Parked")[1])
        self.assertIn("## Reel-in map", md)
        self.assertIn("**Next step:** Prototype parry chains", md)
        self.assertIn("sparked by n1", md)

        on_disk = json.loads((Path(self.tmp.name) / "boards" / f"{bid}.json").read_text())
        self.assertEqual(on_disk, json.loads(json.dumps(board)))  # JSON round-trips
        vs = self.versions()
        self.assertEqual(vs, sorted(set(vs)), "versions only ever go up")
        self.assertEqual(vs[-1], on_disk["version"])

    def test_flip_call_flips_once(self):
        self.store.start_round(self.bid, 60)
        _, first = self.store.flip(self.bid)
        _, second = self.store.flip(self.bid)
        self.assertEqual((first, second), (True, False))

    def test_announcement_claimed_once(self):
        """Acceptance 5: exactly one Time's up message, however many windows ask."""
        _, a = self.store.claim_announcement(self.bid, "flip:1")
        _, b = self.store.claim_announcement(self.bid, "flip:1")
        self.assertEqual((a, b), (True, False))

    def test_cannot_start_while_running(self):
        self.store.start_round(self.bid, 60)
        with self.assertRaises(B.BoardError):
            self.store.start_round(self.bid, 60)
        self.clock.advance(61)
        _, r = self.store.start_round(self.bid, 60)  # lazy flip frees the slot
        self.assertEqual(r["n"], 2)

    def test_notes_outside_a_round_are_face_up(self):
        _, added = self.store.add_notes(self.bid, "agent", [{"text": "idea"}])
        self.assertFalse(added[0]["face_down"])
        self.assertIsNone(added[0]["reveal_at"])


class TestTrickle(BoardTestCase):
    """Acceptance 3: 5 agent notes in a 3-min burst land over ~2 minutes, not at once."""

    def test_reveal_spacing(self):
        self.store.start_round(self.bid, 180)
        self.clock.advance(5)
        _, added = self.store.add_notes(self.bid, "agent", [{"text": f"idea {i}"} for i in range(5)])
        offsets = [(B._parse(n["reveal_at"]) - T0).total_seconds() for n in added]
        self.assertEqual(offsets[0], 5)
        self.assertAlmostEqual(offsets[-1], 126)  # 70% of 180 s
        gaps = [b - a for a, b in zip(offsets, offsets[1:])]
        self.assertTrue(all(abs(g - gaps[0]) < 1e-6 and g > 20 for g in gaps))

        board = self.store.get(self.bid)
        seen = [len(B.view(board, "user", T0 + timedelta(seconds=t))["notes"]) for t in (5, 40, 70, 100, 126)]
        self.assertEqual(seen, [1, 2, 3, 4, 5])

    def test_late_batch_lands_immediately(self):
        self.store.start_round(self.bid, 100)
        self.clock.advance(90)  # past the 70% window
        _, added = self.store.add_notes(self.bid, "agent", [{"text": "a"}, {"text": "b"}])
        self.assertTrue(all(B._parse(n["reveal_at"]) == self.clock.t for n in added))


class TestNoAnchoring(BoardTestCase):
    """Acceptance 4: each side's face-down text is hidden from the other until the flip."""

    def setUp(self):
        super().setUp()
        self.store.start_round(self.bid, 180)
        self.store.add_notes(self.bid, "user", [{"text": "USER SECRET"}])
        self.store.add_notes(self.bid, "agent", [{"text": "AGENT SECRET"}])

    def test_agent_cannot_read_user_face_down(self):
        board = self.store.get(self.bid)
        agent_view = json.dumps(B.view(board, "agent"))
        self.assertNotIn("USER SECRET", agent_view)
        self.assertIn("AGENT SECRET", agent_view)
        text = B.summary(board, "agent")
        self.assertNotIn("USER SECRET", text)
        self.assertIn("1 note(s), hidden until the flip", text)

    def test_user_cannot_read_agent_face_down(self):
        board = self.store.get(self.bid)
        user_view = B.view(board, "user", self.clock.t)
        self.assertNotIn("AGENT SECRET", json.dumps(user_view))
        back = next(n for n in user_view["notes"] if n["author"] == "agent")
        self.assertIsNone(back["text"])
        self.assertTrue(back["face_down"])

    def test_both_visible_after_flip(self):
        self.clock.advance(200)
        board = self.store.get(self.bid)
        for viewer in ("agent", "user"):
            dumped = json.dumps(B.view(board, viewer, self.clock.t))
            self.assertIn("USER SECRET", dumped)
            self.assertIn("AGENT SECRET", dumped)

    def test_hidden_notes_cannot_be_sparked_sorted_or_starred(self):
        with self.assertRaises(B.BoardError):
            self.store.add_notes(self.bid, "agent", [{"text": "x", "spark_of": "n1"}])
        with self.assertRaises(B.BoardError):
            self.store.sort(self.bid, moves=[{"note_id": "n1", "bucket": "combat"}], actor="agent")
        with self.assertRaises(B.BoardError):
            self.store.star(self.bid, "n2")

    def test_export_refused_mid_round(self):
        with self.assertRaises(B.BoardError):
            self.store.export_markdown(self.bid)


class TestGuards(BoardTestCase):
    def test_rejects_path_like_board_ids(self):
        for bad in ("../x", "b_../../etc", "b_1234", "", None):
            with self.assertRaises(B.BoardError):
                self.store.get(bad)

    def test_note_text_clipped_to_140(self):
        _, added = self.store.add_notes(self.bid, "user", [{"text": "x" * 500}])
        self.assertEqual(len(added[0]["text"]), 140)

    def test_only_author_edits(self):
        self.store.add_notes(self.bid, "agent", [{"text": "mine"}])
        with self.assertRaises(B.BoardError):
            self.store.edit_note(self.bid, "n1", "hijack", actor="user")

    def test_summary_stays_short(self):
        for i in range(25):
            self.store.add_notes(self.bid, "agent", [{"text": f"{i} " + "y" * 130}] * 10)
        self.assertLessEqual(len(B.summary(self.store.get(self.bid), "agent")), 2000)

    def test_list_filters_by_session(self):
        self.store.create("other", session_id="local-zzz")
        self.assertEqual([b["id"] for b in self.store.list("local-abc")], [self.bid])
        self.assertEqual(len(self.store.list()), 2)


if __name__ == "__main__":
    unittest.main()
