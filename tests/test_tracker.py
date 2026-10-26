from datetime import date

import pytest

from jobscout import jsearch, store, tracker


@pytest.fixture
def db(tmp_path):
    """pytest gives each test its own temp folder, so tests never touch real data."""
    return tmp_path / "t.db"


def test_add_update_list(db):
    app_id = tracker.add("TPM", "Acme", status="applied", db=db)
    tracker.update(app_id, status="interview", notes="phone screen Tue", db=db)
    df = tracker.list_all(db=db)
    assert df.loc[0, "status"] == "interview"
    assert df.loc[0, "notes"] == "phone screen Tue"


def test_rejects_bad_status_and_unknown_field(db):
    with pytest.raises(ValueError):
        tracker.add("TPM", "Acme", status="ghosted", db=db)
    app_id = tracker.add("TPM", "Acme", db=db)
    with pytest.raises(ValueError):
        tracker.update(app_id, bogus="x", db=db)


def test_due_skips_closed_and_future(db):
    tracker.add("A", "X", status="applied", follow_up_date="2026-10-01", db=db)
    tracker.add("B", "X", status="rejected", follow_up_date="2026-10-01", db=db)
    tracker.add("C", "X", status="applied", follow_up_date="2026-12-01", db=db)
    due = tracker.due(today=date(2026, 10, 26), db=db)
    assert list(due["title"]) == ["A"]


def test_import_jobs_is_idempotent(db):
    df = store.to_frame(jsearch.load_sample())
    first = tracker.import_jobs(df, db=db)
    assert first == len(df)
    assert tracker.import_jobs(df, db=db) == 0


def test_import_sets_posted_and_retrieved_dates(db):
    tracker.import_jobs(store.to_frame(jsearch.load_sample()), db=db)
    row = tracker.list_all(db=db).sort_values("job_id").iloc[0]
    assert row["posted_at"] == "2026-10-02"          # sample-000's posting date
    assert row["retrieved_at"] == date.today().isoformat()


def test_manual_add_defaults_retrieved_today(db):
    tracker.add("TPM", "Acme", db=db)
    assert tracker.list_all(db=db).loc[0, "retrieved_at"] == date.today().isoformat()


def test_old_database_is_migrated(db):
    """A database created before these columns existed keeps its rows."""
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE, "
                 "title TEXT NOT NULL, employer TEXT NOT NULL, location TEXT, url TEXT, "
                 "status TEXT NOT NULL DEFAULT 'saved', applied_date TEXT, contact TEXT, "
                 "follow_up_date TEXT, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO applications (title, employer, created_at) VALUES ('Old', 'Co', '2026-09-01 10:00:00')")
    conn.commit()
    conn.close()
    df = tracker.list_all(db=db)
    assert df.loc[0, "title"] == "Old"
    assert df.loc[0, "retrieved_at"] == "2026-09-01"
