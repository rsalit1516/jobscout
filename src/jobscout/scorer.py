"""Score job postings against profile.md using the Claude API.

The plumbing (API client, caching, the loop) is done. Two functions are
yours to write, marked TODO:

    build_prompt(profile, job)  -> the message Claude sees
    parse_response(text)        -> turn Claude's reply into a Score

`uv run pytest` tells you when parse_response is right; the tests in
tests/test_scorer.py are the spec.
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from jobscout.models import Job

ROOT = Path(__file__).resolve().parents[2]
PROFILE_FILE = ROOT / "profile.md"
CACHE_FILE = ROOT / "data" / "scores.json"

# Haiku is fast and cheap: right for scoring many postings.
# Try "claude-sonnet-5-5" later and compare the results; that comparison is
# itself a useful exercise.
MODEL = "claude-haiku-5-5"


@dataclass(frozen=True)
class Score:
    job_id: str
    score: int              # 1-10
    verdict: str            # one line
    reasons: list[str]      # why it fits
    concerns: list[str]     # gaps, dealbreakers, red flags


# --------------------------------------------------------------------------
# YOUR CODE
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """\
TODO: Tell Claude its role and how to behave.

Things worth deciding:
  - Who is it? (a recruiter screening for one specific candidate?)
  - What does each score mean? Anchor the scale, e.g. what makes a 9 vs a 5 vs a 2.
    Without anchors, LLMs cluster everything around 6-7.
  - How should dealbreakers affect the score?
  - Exactly what JSON shape to return, and "JSON only, no other text".
"""


def build_prompt(profile: str, job: Job) -> str:
    """Return the user message for one job.

    TODO: Combine the profile and the job into one message. Include whatever
    fields help Claude judge fit (title, employer, location, remote, salary,
    description). Tip: wrapping each part in tags like <profile>...</profile>
    and <job>...</job> helps Claude keep them apart.

    Python tip: triple-quoted f-strings let you write multi-line templates:
        f\"\"\"<job>
        Title: {job.title}
        </job>\"\"\"
    """
    raise NotImplementedError("build_prompt")


def parse_response(job_id: str, text: str) -> Score:
    """Turn Claude's raw reply into a Score.

    Accept a JSON object directly or embedded in prose/code fences.
    """
    decoder = json.JSONDecoder()
    response = text.strip()
    data = None

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        for index, character in enumerate(response):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(response[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                data = candidate
                break

    if not isinstance(data, dict):
        raise ValueError("Response does not contain a JSON object")

    try:
        score = int(data["score"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Response must contain an integer score") from exc

    verdict = data.get("verdict")
    if not isinstance(verdict, str):
        raise ValueError("Response must contain a string verdict")

    reasons = data.get("reasons", [])
    concerns = data.get("concerns", [])
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise ValueError("Response reasons must be a list of strings")
    if not isinstance(concerns, list) or not all(isinstance(item, str) for item in concerns):
        raise ValueError("Response concerns must be a list of strings")

    return Score(
        job_id=job_id,
        score=max(1, min(10, score)),
        verdict=verdict,
        reasons=reasons,
        concerns=concerns,
    )


# --------------------------------------------------------------------------
# PLUMBING (done)
# --------------------------------------------------------------------------

def _client() -> anthropic.Anthropic:
    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
    return anthropic.Anthropic()   # reads the key from the environment


def _load_cache() -> dict[str, dict]:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def score_job(client: anthropic.Anthropic, profile: str, job: Job) -> Score:
    """One API call for one job."""
    message = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(profile, job)}],
    )
    text = message.content[0].text
    return parse_response(job.job_id, text)


def score_jobs(jobs: list[Job], *, rescore: bool = False) -> list[Score]:
    """Score many jobs, skipping any already in data/scores.json.

    The cache matters: you pay per call, and you'll rerun this a lot while
    tweaking. Pass rescore=True after you change the prompt.
    """
    profile = PROFILE_FILE.read_text()
    cache = {} if rescore else _load_cache()
    client = _client()
    results: list[Score] = []

    for i, job in enumerate(jobs, start=1):      # enumerate = index + item
        if job.job_id in cache:
            results.append(Score(**cache[job.job_id]))   # ** unpacks a dict into keyword args
            continue
        print(f"[{i}/{len(jobs)}] scoring {job.title} @ {job.employer}")
        try:
            score = score_job(client, profile, job)
        except Exception as exc:                  # keep going if one job fails
            print(f"    failed: {exc}")
            continue
        cache[job.job_id] = asdict(score)
        _save_cache(cache)                        # save as we go, so a crash loses nothing
        results.append(score)

    return results
