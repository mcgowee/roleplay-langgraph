#!/usr/bin/env python3
"""CLI tests for app.tension_node — run from repo root: python3 scripts/test_tension_node.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import tension_node  # noqa: E402


def _base():
    return {
        "milestones": ["goal a", "goal b"],
        "milestone_progress": 0,
        "tension_turns_since_milestone": 0,
        "tension_mood": "progressing",
        "location": "room",
        "locations": {
            "room": {
                "description": "",
                "items": [],
                "characters": ["npc"],
            }
        },
        "characters": {
            "npc": {
                "stall_threshold": 3,
                "mood": 5,
            }
        },
        "response": "",
    }


def main() -> None:
    # No milestones -> no tracking
    s0 = dict(_base())
    s0["milestones"] = []
    assert tension_node(s0) == {}, "no milestones should return {}"

    # Milestone achieved this turn -> reset
    s1 = dict(_base())
    s1["response"] = "[Milestone achieved: goal a] Next milestone: goal b"
    assert tension_node(s1) == {
        "tension_turns_since_milestone": 0,
        "tension_mood": "progressing",
    }, "milestone achieved should reset counter"

    # Increment toward stalling (threshold 3)
    s2 = dict(_base())
    s2["tension_turns_since_milestone"] = 2
    s2["response"] = "narration only"
    assert tension_node(s2) == {
        "tension_turns_since_milestone": 3,
        "tension_mood": "stalling",
    }, "count 3 >= threshold 3 should stall"

    # Below threshold stays progressing
    s3 = dict(_base())
    s3["tension_turns_since_milestone"] = 1
    s3["response"] = "ok"
    assert tension_node(s3) == {
        "tension_turns_since_milestone": 2,
        "tension_mood": "progressing",
    }, "count 2 < 3 should stay progressing"

    # Lowest threshold among NPCs wins
    s4 = dict(_base())
    s4["characters"] = {
        "a": {"stall_threshold": 5},
        "b": {"stall_threshold": 2},
    }
    s4["locations"]["room"]["characters"] = ["a", "b"]
    s4["tension_turns_since_milestone"] = 1
    s4["response"] = ""
    assert tension_node(s4) == {
        "tension_turns_since_milestone": 2,
        "tension_mood": "stalling",
    }, "lowest non-zero threshold (2) should apply"

    # Skip missing / zero stall_threshold — no thresholds -> always progressing
    s5 = dict(_base())
    s5["characters"] = {"npc": {"stall_threshold": 0}}
    s5["tension_turns_since_milestone"] = 10
    s5["response"] = ""
    assert tension_node(s5) == {
        "tension_turns_since_milestone": 11,
        "tension_mood": "progressing",
    }, "no valid thresholds -> progressing"

    print("tension_node: all assertions passed")


if __name__ == "__main__":
    main()
