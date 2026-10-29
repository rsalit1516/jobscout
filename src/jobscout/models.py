"""The Job record.

C# analogy: a `record` with an init-only constructor. `@dataclass` generates
__init__, __repr__ (ToString) and __eq__ (Equals) for you. `frozen=True`
makes it immutable, like a C# record.
"""

from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass(frozen=True)
class Job:
    job_id: str
    title: str
    employer: str
    city: str | None          # `str | None` is Python's `string?`
    state: str | None
    is_remote: bool
    posted_at: datetime | None
    apply_link: str | None
    description: str
    min_salary: float | None = None   # defaults must come after non-defaults
    max_salary: float | None = None
    latitude: float | None = None     # used for the distance filter
    longitude: float | None = None
    publisher: str | None = None      # where the posting was found (LinkedIn, Indeed, ...)

    @classmethod
    def from_jsearch(cls, raw: dict) -> "Job":
        """Build a Job from one item in JSearch's `data` array.

        Like a static factory method in C#. `cls` is the class itself, so this
        also works correctly for subclasses.

        `raw.get("key")` returns None when the key is missing instead of
        throwing, like TryGetValue without the out parameter.
        """
        posted = raw.get("job_posted_at_datetime_utc")
        return cls(
            job_id=raw["job_id"],
            title=raw.get("job_title") or "",
            employer=raw.get("employer_name") or "",
            city=raw.get("job_city"),
            state=raw.get("job_state"),
            is_remote=bool(raw.get("job_is_remote")),
            # Conditional expression: Python's version of `cond ? a : b`
            posted_at=datetime.fromisoformat(posted.replace("Z", "+00:00")) if posted else None,
            apply_link=raw.get("job_apply_link"),
            description=raw.get("job_description") or "",
            min_salary=raw.get("job_min_salary"),
            max_salary=raw.get("job_max_salary"),
            latitude=raw.get("job_latitude"),
            longitude=raw.get("job_longitude"),
            publisher=raw.get("job_publisher"),
        )

    def to_row(self) -> dict:
        """Flatten to a plain dict, ready for a pandas DataFrame."""
        return asdict(self)
