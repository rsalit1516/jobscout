"""Run every configured search, filter, de-duplicate and import into the tracker.

    uv run jobscout-run --dry-run     # show the plan, make no API calls
    uv run jobscout-run               # fetch and import
"""

import re
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path
from typing import Callable

from jobscout import config as config_mod
from jobscout import filters, jsearch, store, tracker
from jobscout.config import Config, Group
from jobscout.models import Job


@dataclass
class Summary:
    calls: int = 0
    fetched: int = 0
    duplicates: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    kept: list[Job] = field(default_factory=list)
    imported: int = 0
    errors: list[str] = field(default_factory=list)


def dedupe_key(job: Job) -> str:
    """Same title + employer + city means the same posting, even under a different job_id."""
    def norm(text: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
    return f"{norm(job.title)}|{norm(job.employer)}|{norm(job.city)}"


def _query(title: str, cfg: Config) -> str:
    return f"{title} in {cfg.location.query}"


def plan(cfg: Config) -> list[str]:
    """Human-readable plan: primaries always run; variants only if the primary is thin."""
    lines = []
    for g in cfg.groups:
        lines.append(f"{g.name}: '{_query(g.primary, cfg)}'")
        lines.append(f"    + up to {len(g.variants)} variants if fewer than {cfg.search.thin_threshold} results")
    lines.append(f"API call cap per run: {cfg.search.max_calls}")
    return lines


SearchFn = Callable[..., list[Job]]


def fetch(cfg: Config, summary: Summary, search_fn: SearchFn = jsearch.search) -> list[Job]:
    """Run primaries, then variants for thin groups, within the call cap. Returns raw (unfiltered) jobs."""
    found: dict[str, list[Job]] = {g.name: [] for g in cfg.groups}

    def run(group: Group, title: str) -> None:
        if summary.calls >= cfg.search.max_calls:
            return
        summary.calls += 1
        try:
            jobs = search_fn(_query(title, cfg), date_posted=cfg.search.date_posted)
        except Exception as exc:      # one failed call shouldn't sink the run
            summary.errors.append(f"{title}: {exc}")
            return
        found[group.name].extend(jobs)

    for g in cfg.groups:
        run(g, g.primary)

    # Round-robin the variants across groups so one group can't use the whole budget.
    # A group's "thin" check uses the filtered count, since that's what we'd actually keep.
    def thin(g: Group) -> bool:
        kept, _ = filters.apply(found[g.name], cfg)
        return len(kept) < cfg.search.thin_threshold

    for round_ in zip_longest(*(g.variants for g in cfg.groups)):
        for g, variant in zip(cfg.groups, round_):
            if variant and thin(g):
                run(g, variant)

    return [job for jobs in found.values() for job in jobs]


def run(cfg: Config | None = None, *, search_fn: SearchFn = jsearch.search,
        db: Path = tracker.DB_PATH, save_csv: bool = True) -> Summary:
    cfg = cfg or config_mod.load()
    summary = Summary()
    raw = fetch(cfg, summary, search_fn)
    summary.fetched = len(raw)

    kept, summary.dropped = filters.apply(raw, cfg)

    seen: set[str] = set()
    unique: list[Job] = []
    for job in kept:
        keys = {job.job_id, dedupe_key(job)}
        if keys & seen:
            summary.duplicates += 1
            continue
        seen |= keys
        unique.append(job)
    summary.kept = unique

    if unique:
        if save_csv:
            store.save(unique)
        summary.imported = tracker.import_jobs(store.to_frame(unique), db=db)
    return summary


def report(summary: Summary) -> str:
    dropped = ", ".join(f"{n} {why}" for why, n in sorted(summary.dropped.items())) or "none"
    lines = [
        f"API calls: {summary.calls} | fetched: {summary.fetched} | duplicates: {summary.duplicates}",
        f"Dropped: {dropped}",
        f"Kept {len(summary.kept)} -> {summary.imported} new in the tracker",
    ]
    lines += [f"ERROR {e}" for e in summary.errors]
    return "\n".join(lines)
