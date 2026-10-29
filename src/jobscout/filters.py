"""Decide whether a fetched posting is worth keeping.

Each check returns a reason string when the job should be DROPPED, or None
when it passes. Keeping the reason (instead of just True/False) lets the
runner report why things were dropped.
"""

import math
import re

from jobscout.config import Config
from jobscout.models import Job

EARTH_RADIUS_MILES = 3958.8


def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine formula)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def drop_reason(job: Job, cfg: Config) -> str | None:
    """Why this job should be dropped, or None to keep it."""
    if cfg.filters.exclude_remote and job.is_remote:
        return "remote"

    title = job.title.lower()
    if any(re.search(p, title) for p in cfg.filters.title_exclude):
        return "entry-level/IC title"
    if cfg.filters.title_include and not any(re.search(p, title) for p in cfg.filters.title_include):
        return "not a management title"

    loc = cfg.location
    if job.latitude is not None and job.longitude is not None:
        if not (loc.min_lat <= job.latitude <= loc.max_lat and loc.min_lon <= job.longitude <= loc.max_lon):
            return "outside area"
    elif (job.city or "").lower() not in {c.lower() for c in loc.nearby_cities}:
        return "outside area"            # no coordinates: fall back to the city list
    return None


def apply(jobs: list[Job], cfg: Config) -> tuple[list[Job], dict[str, int]]:
    """Return (kept jobs, {reason: count of dropped})."""
    kept: list[Job] = []
    dropped: dict[str, int] = {}
    for job in jobs:
        reason = drop_reason(job, cfg)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
        else:
            kept.append(job)
    return kept, dropped
