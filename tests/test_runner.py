from dataclasses import replace

import pytest

from jobscout import config, filters, runner, tracker
from jobscout.models import Job

# Delray Beach ~ the configured centre. Orlando is ~170 miles away.
NEAR = dict(latitude=26.46, longitude=-80.07, city="Delray Beach")
FAR = dict(latitude=28.54, longitude=-81.38, city="Orlando")


def make(job_id="1", title="Engineering Manager", employer="Acme", remote=False, **kw):
    fields = dict(job_id=job_id, title=title, employer=employer, state="FL", is_remote=remote,
                  posted_at=None, apply_link=None, description="", **NEAR)
    fields.update(kw)
    return Job(**fields)


@pytest.fixture
def cfg():
    return config.load()


@pytest.mark.parametrize("job, reason", [
    (make(), None),
    (make(remote=True), "remote"),
    (make(title="Software Engineer"), "not a management title"),
    (make(title="Junior Engineering Manager"), "entry-level/IC title"),
    (make(title="Associate Engineering Manager"), "entry-level/IC title"),
    (make(title="Associate Director of Engineering"), None),
    (make(**FAR), "outside radius"),
    (make(latitude=None, longitude=None, city="Boca Raton"), None),
    (make(latitude=None, longitude=None, city="Tampa"), "outside radius"),
])
def test_drop_reason(cfg, job, reason):
    assert filters.drop_reason(job, cfg) == reason


def test_distance_is_sane():
    # Delray Beach to Orlando is roughly 170 miles.
    assert 150 < filters.distance_miles(26.46, -80.07, 28.54, -81.38) < 190


def test_dedupe_key_ignores_case_and_punctuation():
    a = make(job_id="1", title="Engineering Manager, Software", employer="Acme, Inc.", city="Delray Beach")
    b = make(job_id="2", title="engineering manager software", employer="ACME Inc", city="delray beach")
    assert runner.dedupe_key(a) == runner.dedupe_key(b)


class FakeSearch:
    """Stands in for jsearch.search and records which queries were made."""

    def __init__(self, by_title):
        self.by_title, self.queries = by_title, []

    def __call__(self, query, **kwargs):
        self.queries.append(query)
        title = query.split(" in ")[0]
        return list(self.by_title.get(title, []))


def test_variants_run_only_when_primary_is_thin(cfg, tmp_path):
    plenty = [make(job_id=str(i), employer=f"Co{i}") for i in range(5)]
    fake = FakeSearch({"Software Engineering Manager": plenty})
    # Only the first group matters here; keep the others from adding noise.
    one_group = replace(cfg, groups=cfg.groups[:1])
    runner.run(one_group, search_fn=fake, db=tmp_path / "t.db", save_csv=False)
    assert len(fake.queries) == 1                      # primary was healthy: no variants

    fake = FakeSearch({})
    summary = runner.run(one_group, search_fn=fake, db=tmp_path / "t.db", save_csv=False)
    assert len(fake.queries) == 1 + len(one_group.groups[0].variants)
    assert summary.calls == len(fake.queries)


def test_call_cap_is_respected(cfg, tmp_path):
    capped = replace(cfg, search=replace(cfg.search, max_calls=4))
    fake = FakeSearch({})
    runner.run(capped, search_fn=fake, db=tmp_path / "t.db", save_csv=False)
    assert len(fake.queries) == 4


def test_run_dedupes_filters_and_imports(cfg, tmp_path):
    db = tmp_path / "t.db"
    jobs = [
        make(job_id="a"),
        make(job_id="b"),                                   # same title/employer/city as "a"
        make(job_id="c", employer="Other", remote=True),    # remote
        make(job_id="d", employer="Third", **FAR),          # too far
        make(job_id="e", employer="Fourth"),
    ]
    fake = FakeSearch({"Software Engineering Manager": jobs})
    one_group = replace(cfg, groups=cfg.groups[:1], search=replace(cfg.search, thin_threshold=1))
    summary = runner.run(one_group, search_fn=fake, db=db, save_csv=False)
    assert summary.fetched == 5
    assert summary.duplicates == 1
    assert summary.dropped == {"remote": 1, "outside radius": 1}
    assert summary.imported == 2
    assert len(tracker.list_all(db=db)) == 2
    # A second run imports nothing new.
    assert runner.run(one_group, search_fn=fake, db=db, save_csv=False).imported == 0


def test_failed_call_is_reported_not_raised(cfg, tmp_path):
    def boom(query, **kwargs):
        raise RuntimeError("quota exceeded")
    one_group = replace(cfg, groups=cfg.groups[:1], search=replace(cfg.search, max_calls=1))
    summary = runner.run(one_group, search_fn=boom, db=tmp_path / "t.db", save_csv=False)
    assert "quota exceeded" in summary.errors[0]
