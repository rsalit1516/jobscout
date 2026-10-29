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
    scored: int = 0
    errors: list[str] = field(default_factory=list)


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# Words that differ between sources without changing which job it is.
_NOISE = {"hiring", "is", "in", "at", "us", "fl", "florida", "the", "a", "and"}


def signature(title: str, employer: str, city: str | None) -> tuple[str, str, frozenset[str]]:
    """(employer, city, title words) with location words and noise removed from the title."""
    skip = _NOISE | set(_norm(city).split()) | set(_norm(employer).split())   # sites often add these
    words = frozenset(w for w in _norm(title).split() if w not in skip)
    return _norm(employer), _norm(city), words


def same_posting(a: tuple, b: tuple, threshold: float = 0.6) -> bool:
    """Same employer and city, and mostly the same title words (Jaccard similarity).

    "Senior Construction Project Manager (Delray Beach)" and
    "Senior Construction Project Manager - Delray Beach, Florida, US" are one job
    that different sites title slightly differently.
    """
    if a[0] != b[0] or a[1] != b[1]:
        return False
    union = a[2] | b[2]
    return not union or len(a[2] & b[2]) / len(union) >= threshold


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


ScoreFn = Callable[[list[Job]], list]      # e.g. scorer.score_jobs


def run(cfg: Config | None = None, *, search_fn: SearchFn = jsearch.search,
        score_fn: ScoreFn | None = None,
        db: Path = tracker.DB_PATH, save_csv: bool = True) -> Summary:
    cfg = cfg or config_mod.load()
    summary = Summary()
    raw = fetch(cfg, summary, search_fn)
    summary.fetched = len(raw)

    kept, summary.dropped = filters.apply(raw, cfg)

    # Start from what's already in the tracker, so yesterday's jobs re-posted by another
    # site today don't come back as new.
    existing = tracker.list_all(db=db)
    seen_ids = set(existing["job_id"].dropna())
    seen_sigs = [signature(r.title, r.employer, (r.location or "").split(",")[0])
                 for r in existing.itertuples()]
    unique: list[Job] = []
    for job in kept:
        sig = signature(job.title, job.employer, job.city)
        if job.job_id in seen_ids or any(same_posting(sig, s) for s in seen_sigs):
            summary.duplicates += 1
            continue
        seen_ids.add(job.job_id)
        seen_sigs.append(sig)
        unique.append(job)
    summary.kept = unique

    if unique:
        if save_csv:
            store.save(unique)
        summary.imported = tracker.import_jobs(store.to_frame(unique), db=db)
        if score_fn:
            _score(unique, score_fn, summary, db)
    return summary


def _score(jobs: list[Job], score_fn: ScoreFn, summary: Summary, db: Path) -> None:
    """Score jobs the tracker has no score for yet. A scoring failure never loses the import."""
    pending = tracker.unscored_job_ids(db=db)
    try:
        scores = score_fn([j for j in jobs if j.job_id in pending])
    except Exception as exc:
        summary.errors.append(f"scoring: {exc}")
        return
    for s in scores:
        tracker.save_score(s.job_id, s.score, s.verdict, s.reasons, s.concerns, db=db)
    summary.scored = len(scores)


def report(summary: Summary) -> str:
    dropped = ", ".join(f"{n} {why}" for why, n in sorted(summary.dropped.items())) or "none"
    lines = [
        f"API calls: {summary.calls} | fetched: {summary.fetched} | duplicates: {summary.duplicates}",
        f"Dropped: {dropped}",
        f"Kept {len(summary.kept)} -> {summary.imported} new in the tracker, {summary.scored} scored",
    ]
    lines += [f"ERROR {e}" for e in summary.errors]
    return "\n".join(lines)
