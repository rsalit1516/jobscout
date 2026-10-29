"""Load and validate searches.toml.

tomllib is in Python's standard library (3.11+), so there's nothing to install.
The frozen dataclasses give the rest of the code typed, read-only settings, much
like binding a config section to an options class in .NET.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[2] / "searches.toml"
DATE_POSTED = {"all", "today", "3days", "week", "month"}


@dataclass(frozen=True)
class Location:
    queries: tuple[str, ...]      # one search per title for each of these places
    variant_query: str            # the (single) place used for title-variant searches
    zip: str
    min_lat: float                # the area we accept, as a bounding box
    max_lat: float
    min_lon: float
    max_lon: float
    nearby_cities: tuple[str, ...]


@dataclass(frozen=True)
class SearchSettings:
    date_posted: str
    thin_threshold: int
    max_calls: int


@dataclass(frozen=True)
class Filters:
    exclude_remote: bool
    title_include: tuple[str, ...]
    title_exclude: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    name: str
    primary: str
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    location: Location
    search: SearchSettings
    filters: Filters
    groups: tuple[Group, ...]


def _require(table: dict, key: str, where: str):
    if key not in table:
        raise ValueError(f"searches.toml: missing '{key}' in [{where}]")
    return table[key]


def parse(data: dict) -> Config:
    """Build a Config from already-parsed TOML, raising ValueError on bad input."""
    loc = _require(data, "location", "root")
    search = _require(data, "search", "root")
    filters = _require(data, "filters", "root")
    groups = data.get("groups") or []
    if not groups:
        raise ValueError("searches.toml: define at least one [[groups]] entry")

    cfg = Config(
        location=Location(
            queries=tuple(_require(loc, "queries", "location")),
            variant_query=_require(loc, "variant_query", "location"),
            zip=str(_require(loc, "zip", "location")),
            min_lat=float(_require(loc, "min_lat", "location")),
            max_lat=float(_require(loc, "max_lat", "location")),
            min_lon=float(_require(loc, "min_lon", "location")),
            max_lon=float(_require(loc, "max_lon", "location")),
            nearby_cities=tuple(loc.get("nearby_cities", [])),
        ),
        search=SearchSettings(
            date_posted=_require(search, "date_posted", "search"),
            thin_threshold=int(_require(search, "thin_threshold", "search")),
            max_calls=int(_require(search, "max_calls", "search")),
        ),
        filters=Filters(
            exclude_remote=bool(filters.get("exclude_remote", True)),
            title_include=tuple(filters.get("title_include", [])),
            title_exclude=tuple(filters.get("title_exclude", [])),
        ),
        groups=tuple(
            Group(
                name=_require(g, "name", "groups"),
                primary=_require(g, "primary", "groups"),
                variants=tuple(g.get("variants", [])),
            )
            for g in groups
        ),
    )

    if cfg.search.date_posted not in DATE_POSTED:
        raise ValueError(f"searches.toml: date_posted must be one of {sorted(DATE_POSTED)}")
    loc_ = cfg.location
    if not loc_.queries:
        raise ValueError("searches.toml: [location] needs at least one entry in 'queries'")
    if loc_.min_lat >= loc_.max_lat or loc_.min_lon >= loc_.max_lon:
        raise ValueError("searches.toml: area box needs min_lat < max_lat and min_lon < max_lon")
    if cfg.search.max_calls < 1:
        raise ValueError("searches.toml: max_calls must be positive")
    for pattern in (*cfg.filters.title_include, *cfg.filters.title_exclude):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"searches.toml: bad title pattern {pattern!r}: {exc}") from exc
    return cfg


def load(path: Path = CONFIG_FILE) -> Config:
    with path.open("rb") as f:          # tomllib wants a binary file
        return parse(tomllib.load(f))
