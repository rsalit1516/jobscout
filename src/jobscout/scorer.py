"""Score job postings against profile.md using the Claude API.

The prompt (SYSTEM_PROMPT, build_prompt) is the part worth tuning: change it, run
`uv run jobscout-score --rescore`, and compare. parse_response turns Claude's reply
into a Score; tests/test_scorer.py is its spec.
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
# PROMPT (written by Claude for review; tune it, then rerun with --rescore)
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a recruiter screening job postings for ONE specific candidate. You are given the
candidate's profile and a single posting. Judge how well the posting fits this candidate and
return a score.

Scale (use the whole range; most postings are NOT a strong fit):
  9-10  Exceptional. Target role and seniority, strong skills/domain overlap (e.g. MedTech or
        regulated industry, .NET/Azure), location and pay acceptable, no concerns.
  7-8   Good. Right kind of role and level; one minor gap (domain, stack, or a small unknown).
  5-6   Possible. Related role or level but a notable gap, or key facts are missing.
  3-4   Weak. Mostly mismatched domain, level or responsibilities.
  1-2   Poor. Wrong field, wrong level, or an individual-contributor role.

Rules:
  - A dealbreaker listed in the profile (relocation, heavy travel, pure individual-contributor
    coding, pay below the stated minimum) caps the score at 3, however good the rest looks.
  - Judge the actual duties in the description, not just the title: "Project Manager" in
    construction or hospitality is a poor fit for a software-delivery candidate.
  - If something that matters (salary, travel, location, remote policy) is not stated, do not
    guess. Treat it as neutral and mention it in "concerns".
  - Be specific: refer to details of the posting, not generic praise.

Reply with JSON only, no other text, in exactly this shape:
{"score": <integer 1-10>,
 "verdict": "<one sentence>",
 "reasons": ["<why it fits>", ...],
 "concerns": ["<gaps, dealbreakers, unknowns>", ...]}
"""

MAX_DESCRIPTION_CHARS = 6000   # keeps cost down; the key details are near the top


def _salary(job: Job) -> str:
    if job.min_salary and job.max_salary:
        return f"${job.min_salary:,.0f} - ${job.max_salary:,.0f}"
    if job.min_salary or job.max_salary:
        return f"${(job.min_salary or job.max_salary):,.0f}"
    return "not stated"


def build_prompt(profile: str, job: Job) -> str:
    """Return the user message for one job: profile and posting, each in its own tag."""
    where = ", ".join(p for p in (job.city, job.state) if p) or "not stated"
    posted = job.posted_at.date().isoformat() if job.posted_at else "not stated"
    return f"""<profile>
{profile.strip()}
</profile>

<job>
Title: {job.title}
Employer: {job.employer}
Location: {where}
Remote: {"yes" if job.is_remote else "no"}
Salary: {_salary(job)}
Posted: {posted}
Source: {job.publisher or "unknown"}

Description:
{job.description[:MAX_DESCRIPTION_CHARS]}
</job>"""


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
        max_tokens=1000,
        thinking={"type": "disabled"},    # we want the JSON straight away, not reasoning first
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(profile, job)}],
    )
    # The reply is a list of blocks (text, and sometimes thinking); keep only the text.
    text = "".join(block.text for block in message.content if block.type == "text")
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
