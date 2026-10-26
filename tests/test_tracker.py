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


def test_import_jobs_is_idempotent(db, monkeypatch):
    df = store.to_frame(jsearch.load_sample())
    first = tracker.import_jobs(df, db=db)
    assert first == len(df)
    assert tracker.import_jobs(df, db=db) == 0
