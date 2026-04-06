#!/usr/bin/env python3
"""CLI tests for app._get_tension_description — run from repo root."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _get_tension_description  # noqa: E402


def main() -> None:
    state = {
        "milestone_progress": 1,
        "tension_mood": "stalling",
        "characters": {
            "npc": {
                "tension_stages": [
                    {"progressing": "early prog", "stalling": "early stall"},
                    {
                        "progressing": "mid prog",
                        "stalling": "EXPECTED_STALL_STAGE_1",
                    },
                ],
            }
        },
    }
    got = _get_tension_description(state, "npc")
    assert got == "EXPECTED_STALL_STAGE_1", f"got {got!r}"

    # Index past end -> last stage
    state2 = {
        "milestone_progress": 99,
        "tension_mood": "progressing",
        "characters": {
            "x": {
                "tension_stages": [
                    {"progressing": "a", "stalling": "x"},
                    {"progressing": "LAST", "stalling": "y"},
                ],
            }
        },
    }
    assert _get_tension_description(state2, "x") == "LAST"

    # Missing / empty tension_stages
    assert _get_tension_description({"characters": {"n": {}}}, "n") == ""
    assert _get_tension_description({"characters": {"n": {"tension_stages": []}}}, "n") == ""

    print("_get_tension_description: all assertions passed")


if __name__ == "__main__":
    main()
