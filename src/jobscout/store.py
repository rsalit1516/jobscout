"""Save and load jobs as CSV via pandas."""

from pathlib import Path

import pandas as pd

from jobscout.models import Job

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def to_frame(jobs: list[Job]) -> pd.DataFrame:
    return pd.DataFrame([job.to_row() for job in jobs])


def save(jobs: list[Job], name: str = "jobs.csv") -> Path:
    """Merge new jobs into the CSV, dropping duplicates by job_id."""
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / name          # `/` joins paths, like Path.Combine
    new = to_frame(jobs)
    if path.exists():
        combined = pd.concat([pd.read_csv(path), new], ignore_index=True)
    else:
        combined = new
    combined = combined.drop_duplicates(subset="job_id", keep="last")
    combined.to_csv(path, index=False)
    return path


def load(name: str = "jobs.csv") -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, parse_dates=["posted_at"])
