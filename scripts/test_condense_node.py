#!/usr/bin/env python3
"""CLI tests for app.condense_node — run from repo root: python3 scripts/test_condense_node.py"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import condense_node  # noqa: E402


def _minimal_state(**kwargs):
    base = {
        "message": "Hello",
        "response": "Narrator says hi.",
        "history": [],
        "memory_summary": "",
        "narrator": {"model": "default", "prompt": "x"},
    }
    base.update(kwargs)
    return base


def main() -> None:
    # Empty history — nothing to condense
    s0 = _minimal_state(history=[], message="a", response="b")
    assert condense_node(s0) == {}, "empty history should return {}"

    # Successful LLM call
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock(return_value="  Alex met Sam at the cafe.  ")

    fake_state = _minimal_state(
        history=[
            "Player: old\nOld response",
            "Player: prev\nPrevious response",
        ],
        message="Hi Sam",
        response="Sam smiled.",
        memory_summary="Earlier summary.",
    )

    with patch("app.get_llm", return_value=mock_llm):
        out = condense_node(fake_state)

    assert out == {"memory_summary": "Alex met Sam at the cafe."}, out
    mock_llm.invoke.assert_called_once()
    called_prompt = mock_llm.invoke.call_args[0][0]
    assert "Earlier summary." in called_prompt
    assert "Player: Hi Sam" in called_prompt
    assert "Sam smiled." in called_prompt
    assert "Previous response" in called_prompt

    # LLM failure — return {}
    mock_bad = MagicMock()
    mock_bad.invoke = MagicMock(side_effect=RuntimeError("boom"))

    with patch("app.get_llm", return_value=mock_bad):
        out2 = condense_node(fake_state)
    assert out2 == {}, "LLM error should return {}"

    print("condense_node: all assertions passed")


if __name__ == "__main__":
    main()
