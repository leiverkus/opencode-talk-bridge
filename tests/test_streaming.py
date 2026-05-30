from __future__ import annotations

from opencode_talk_bridge.streaming import StreamState


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _state(throttle=1.5):
    edits = []
    clock = Clock()
    s = StreamState(
        "tok", 7, lambda token, mid, text: edits.append((mid, text)), throttle=throttle, clock=clock
    )
    return s, edits, clock


def test_first_update_edits_immediately():
    s, edits, clock = _state()
    s.update_part("msg1", "p1", "Hello")
    assert edits == [(7, "Hello")]


def test_throttle_suppresses_then_allows():
    s, edits, clock = _state(throttle=1.5)
    s.update_part("msg1", "p1", "a")  # edits at t=0
    clock.t = 0.5
    s.update_part("msg1", "p1", "ab")  # within throttle -> no edit
    assert edits == [(7, "a")]
    clock.t = 2.0
    s.update_part("msg1", "p1", "abc")  # past throttle -> edit
    assert edits[-1] == (7, "abc")


def test_finalize_forces_edit():
    s, edits, clock = _state()
    s.update_part("msg1", "p1", "partial")
    clock.t = 0.1
    s.finalize("FINAL")
    assert edits[-1] == (7, "FINAL")


def test_render_joins_parts_in_order():
    s, edits, clock = _state(throttle=0)
    s.update_part("msg1", "p1", "one")
    s.update_part("msg1", "p2", "two")
    assert edits[-1] == (7, "one\ntwo")


def test_no_edit_when_text_unchanged():
    s, edits, clock = _state(throttle=0)
    s.update_part("msg1", "p1", "same")
    n = len(edits)
    s.finalize("same")  # identical -> no new edit
    assert len(edits) == n


def test_failed_edit_is_swallowed():
    def boom(token, mid, text):
        raise RuntimeError("edit failed")

    s = StreamState("tok", 7, boom)
    s.update_part("msg1", "p1", "x")  # must not raise
    s.finalize("y")
