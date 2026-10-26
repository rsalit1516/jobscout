"""Track your applications in SQLite.

sqlite3 ships with Python, so there's nothing to install. The database is one
file (data/tracker.db). C# analogy: Microsoft.Data.Sqlite with hand-written SQL,
no Entity Framework.

Every function takes an optional `db` path so tests can point at a temp file.
"""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "tracker.db"

STATUSES = ["saved", "applied", "screen", "interview", "offer", "rejected", "withdrawn"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT UNIQUE,          -- from JSearch; NULL for manual entries
    title          TEXT NOT NULL,
    employer       TEXT NOT NULL,
    location       TEXT,
    url            TEXT,
    status         TEXT NOT NULL DEFAULT 'saved',
    applied_date   TEXT,                 -- ISO dates (YYYY-MM-DD) sort correctly as text
    contact        TEXT,
    follow_up_date TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

# Columns the UI is allowed to change. Also guards update() against SQL injection,
# since column names can't be passed as ? parameters.
EDITABLE = {"title", "employer", "location", "url", "status",
            "applied_date", "contact", "follow_up_date", "notes"}


def _connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row      # rows behave like dicts
    conn.execute(SCHEMA)
    return conn


def add(title: str, employer: str, *, db: Path = DB_PATH, **fields) -> int:
    """Insert an application and return its id. Extra fields: see EDITABLE, plus job_id."""
    unknown = set(fields) - EDITABLE - {"job_id"}
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    if fields.get("status", "saved") not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    columns = ["title", "employer", *fields]
    values = [title, employer, *fields.values()]
    sql = f"INSERT INTO applications ({', '.join(columns)}) VALUES ({', '.join('?' * len(values))})"
    # closing() closes the connection; `with conn` alone only commits/rolls back.
    with closing(_connect(db)) as conn, conn:
        return conn.execute(sql, values).lastrowid


def update(app_id: int, *, db: Path = DB_PATH, **fields) -> None:
    unknown = set(fields) - EDITABLE
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if not fields:
        return
    assignments = ", ".join(f"{col} = ?" for col in fields)
    with closing(_connect(db)) as conn, conn:
        conn.execute(f"UPDATE applications SET {assignments} WHERE id = ?", [*fields.values(), app_id])


def delete(app_id: int, *, db: Path = DB_PATH) -> None:
    with closing(_connect(db)) as conn, conn:
        conn.execute("DELETE FROM applications WHERE id = ?", [app_id])


def list_all(*, db: Path = DB_PATH) -> pd.DataFrame:
    with closing(_connect(db)) as conn:
        return pd.read_sql_query("SELECT * FROM applications ORDER BY id DESC", conn)


def due(*, today: date | None = None, db: Path = DB_PATH) -> pd.DataFrame:
    """Open applications whose follow-up date is today or earlier."""
    today = today or date.today()
    sql = """SELECT * FROM applications
             WHERE follow_up_date IS NOT NULL AND follow_up_date <= ?
               AND status NOT IN ('rejected', 'withdrawn', 'offer')
             ORDER BY follow_up_date"""
    with closing(_connect(db)) as conn:
        return pd.read_sql_query(sql, conn, params=[today.isoformat()])


def import_jobs(jobs_df: pd.DataFrame, *, db: Path = DB_PATH) -> int:
    """Add fetched jobs (the data/jobs.csv frame) as 'saved'. Returns how many were new."""
    added = 0
    with closing(_connect(db)) as conn, conn:
        for row in jobs_df.itertuples():
            where = "Remote" if row.is_remote else ", ".join(
                str(p) for p in (row.city, row.state) if pd.notna(p))
            cur = conn.execute(
                "INSERT OR IGNORE INTO applications (job_id, title, employer, location, url) "
                "VALUES (?, ?, ?, ?, ?)",
                [row.job_id, row.title, row.employer, where,
                 row.apply_link if pd.notna(row.apply_link) else None],
            )
            added += cur.rowcount        # 0 when the job_id already existed
    return added
