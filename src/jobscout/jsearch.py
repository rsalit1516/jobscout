"""Thin client for the JSearch API on RapidAPI.

Notice there's no class here. In C# you'd write a JSearchClient class; in
Python a module of functions is often enough. A module is already a
singleton namespace, so reach for a class only when you need state.
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from jobscout.models import Job

BASE_URL = "https://jsearch.p.rapidapi.com"
HOST = "jsearch.p.rapidapi.com"
SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "sample_jobs.json"


def _api_key() -> str:
    # Leading underscore = "private by convention". Python has no access
    # modifiers; it trusts you.
    load_dotenv()  # reads .env from the current directory (or a parent)
    key = os.getenv("RAPIDAPI_KEY")
    if not key or key == "your-key-here":
        raise RuntimeError("RAPIDAPI_KEY is not set. Copy .env.example to .env and add your key.")
    return key


def search_raw(
    query: str,
    *,                       # everything after * must be passed by name
    pages: int = 1,
    date_posted: str = "week",  # all | today | 3days | week | month
    remote_only: bool = False,
) -> list[dict]:
    """Call /search and return the raw `data` list."""
    # Parameter names match JSearch v5 (see the RapidAPI endpoint docs).
    params = {
        "query": query,
        "num_pages": pages,
        "date_posted": date_posted,
        "country": "us",
    }
    if remote_only:
        params["work_from_home"] = "true"

    headers = {"X-RapidAPI-Key": _api_key(), "X-RapidAPI-Host": HOST}

    # `with` = C#'s `using`: the client is disposed when the block ends.
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30) as client:
        response = client.get("/search-v2", params=params)
        response.raise_for_status()   # throws on 4xx/5xx, like EnsureSuccessStatusCode()
        # search-v2 nests the list: {"data": {"jobs": [...], "cursor": ...}}
        return response.json().get("data", {}).get("jobs", [])


def search(query: str, **kwargs) -> list[Job]:
    """Search and convert results to Job objects.

    `**kwargs` collects any extra keyword arguments into a dict and passes
    them straight through to search_raw.
    """
    # A list comprehension: LINQ's .Select(...).ToList() in one line.
    return [Job.from_jsearch(item) for item in search_raw(query, **kwargs)]


def load_sample() -> list[Job]:
    """Offline sample data, so you can practice without spending API calls."""
    raw = json.loads(SAMPLE_FILE.read_text())
    return [Job.from_jsearch(item) for item in raw]
