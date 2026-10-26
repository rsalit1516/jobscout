"""The spec for parse_response. Make these pass one at a time.

Run just this file:  uv run pytest tests/test_scorer.py -v
Run one test:        uv run pytest tests/test_scorer.py -v -k clean
"""

import pytest

from jobscout.scorer import Score, parse_response

CLEAN = """{
  "score": 8,
  "verdict": "Strong fit: MedTech TPM role close to home.",
  "reasons": ["FDA-regulated domain", "Azure stack"],
  "concerns": ["Some travel"]
}"""


def test_clean_json():
    s = parse_response("j1", CLEAN)
    assert s == Score(
        job_id="j1",
        score=8,
        verdict="Strong fit: MedTech TPM role close to home.",
        reasons=["FDA-regulated domain", "Azure stack"],
        concerns=["Some travel"],
    )


def test_json_inside_code_fence():
    # Models sometimes wrap JSON in ```json ... ``` even when told not to.
    s = parse_response("j2", "```json\n" + CLEAN + "\n```")
    assert s.score == 8


def test_json_with_chatter_around_it():
    s = parse_response("j3", "Here is my assessment:\n" + CLEAN + "\nHope that helps!")
    assert s.score == 8


def test_missing_lists_default_to_empty():
    s = parse_response("j4", '{"score": 5, "verdict": "Maybe."}')
    assert s.reasons == []
    assert s.concerns == []


def test_score_is_clamped_to_1_through_10():
    assert parse_response("j5", '{"score": 14, "verdict": "x"}').score == 10
    assert parse_response("j6", '{"score": 0, "verdict": "x"}').score == 1


def test_score_given_as_string_is_converted():
    assert parse_response("j7", '{"score": "7", "verdict": "x"}').score == 7


def test_garbage_raises_value_error():
    with pytest.raises(ValueError):
        parse_response("j8", "I cannot score this job.")
