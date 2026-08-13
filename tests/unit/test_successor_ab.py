from __future__ import annotations

import json
from pathlib import Path

from scripts.run_successor_ab import parse_events, score_response, summarize_trials


def test_parse_events_extracts_usage_tools_and_structured_answer(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            (
                json.dumps(
                    {"type": "item.completed", "item": {"type": "command_execution"}}
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps({"objective": "Continue safely"}),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 25,
                            "output_tokens": 10,
                        },
                    }
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    response, usage, tools = parse_events(path)

    assert response == {"objective": "Continue safely"}
    assert usage == {"input_tokens": 100, "cached_input_tokens": 25, "output_tokens": 10}
    assert tools == 1


def test_score_response_counts_exact_and_unsupported_fields() -> None:
    score = score_response(
        {"objective": "right", "next_action": "wrong", "constraint": "UNKNOWN"},
        {"objective": "right", "next_action": "next", "constraint": "safe"},
    )

    assert score == {
        "correct_fields": 1,
        "total_fields": 3,
        "correctness": 0.3333,
        "unsupported_fields": 1,
    }


def test_score_response_accepts_punctuation_and_cited_path_details() -> None:
    score = score_response(
        {
            "objective": "Continue safely.",
            "entry_point": "src.normalizer.normalize (src/normalizer.py:1)",
            "test_file": "tests/test_parser.py:4 — test_parser",
        },
        {
            "objective": "Continue safely",
            "entry_point": "src/normalizer.py",
            "test_file": "tests/test_parser.py",
        },
    )

    assert score["correctness"] == 1.0
    assert score["unsupported_fields"] == 0


def test_summarize_trials_reports_directional_paired_change() -> None:
    trials = [
        {
            "condition": "repository_only",
            "duration_seconds": 10.0,
            "tool_events": 4,
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "score": {"correctness": 1.0, "unsupported_fields": 0},
        },
        {
            "condition": "threadline",
            "duration_seconds": 4.0,
            "tool_events": 1,
            "usage": {"input_tokens": 40, "output_tokens": 10},
            "score": {"correctness": 1.0, "unsupported_fields": 0},
        },
    ]

    summary = summarize_trials(trials)

    assert summary["scope"].startswith("directional private pilot")
    assert summary["conditions"]["threadline"]["mean_correctness"] == 1.0
    assert summary["threadline_change"] == {
        "duration_seconds_reduction": 0.6,
        "input_tokens_reduction": 0.6,
        "output_tokens_reduction": 0.5,
        "tool_events_reduction": 0.75,
    }
