"""pytest finds any function named test_* and runs it. Plain `assert` is all you need."""

from jobscout import jsearch
from jobscout.models import Job


def test_from_jsearch_handles_missing_fields():
    job = Job.from_jsearch({"job_id": "x1"})
    assert job.title == ""
    assert job.posted_at is None
    assert job.is_remote is False


def test_sample_loads():
    jobs = jsearch.load_sample()
    assert len(jobs) > 0
    assert all(isinstance(j, Job) for j in jobs)
