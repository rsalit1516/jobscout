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
    """The shipped config, narrowed to one place so call counts in tests are easy to reason about."""
    shipped = config.load()
    return replace(shipped, location=replace(shipped.location, queries=shipped.location.queries[:1]))


def test_each_title_is_searched_in_every_place_and_variants_use_the_wide_query(cfg, tmp_path):
    places = ("Fort Lauderdale, FL", "Boca Raton, FL")
    multi = replace(cfg, groups=cfg.groups[:1], location=replace(cfg.location, queries=places))
    fake = FakeSearch({})                       # nothing found: variants will be tried
    runner.run(multi, search_fn=fake, db=tmp_path / "t.db", save_csv=False)
    primary = [q for q in fake.queries if q.startswith("Software Engineering Manager in ")]
    assert [q.split(" in ")[1] for q in primary] == list(places)
    variants = [q for q in fake.queries if not q.startswith("Software Engineering Manager in ")]
    assert variants and all(q.endswith(cfg.location.variant_query) for q in variants)


@pytest.mark.parametrize("job, reason", [
    (make(), None),
    (make(remote=True), "remote"),
    (make(title="Software Engineer"), "not a management title"),
    (make(title="Junior Engineering Manager"), "entry-level/IC title"),
    (make(title="Associate Engineering Manager"), "entry-level/IC title"),
    (make(title="Associate Director of Engineering"), None),
    (make(title="Senior Construction Project Manager"), "entry-level/IC title"),   # non-software field
    (make(title="Hotel Engineering Manager"), "entry-level/IC title"),
    (make(**FAR), "outside area"),
    (make(latitude=None, longitude=None, city="Boca Raton"), None),
    (make(latitude=None, longitude=None, city="Tampa"), "outside area"),
])
def test_drop_reason(cfg, job, reason):
    assert filters.drop_reason(job, cfg) == reason


def test_distance_is_sane():
    # Delray Beach to Orlando is roughly 170 miles.
    assert 150 < filters.distance_miles(26.46, -80.07, 28.54, -81.38) < 190


def sig(title, employer="Suncap", city="Delray Beach"):
    return runner.signature(title, employer, city)


def test_same_posting_ignores_case_punctuation_and_location_words():
    assert runner.same_posting(sig("Engineering Manager, Software", "Acme, Inc."),
                               sig("engineering manager software", "ACME Inc", "delray beach"))
    assert runner.same_posting(sig("Senior Project Manager (Delray Beach)"),
                               sig("Senior Project Manager - Delray Beach, Florida, US"))
    assert runner.same_posting(sig("Suncap is hiring: Project Manager in Delray Beach"),
                               sig("Project Manager"))


def test_different_jobs_are_not_merged():
    assert not runner.same_posting(sig("Engineering Manager"), sig("Director of Engineering"))
    assert not runner.same_posting(sig("Engineering Manager"), sig("Engineering Manager", city="Boca Raton"))
    assert not runner.same_posting(sig("Engineering Manager"), sig("Engineering Manager", employer="Other"))


def test_rerun_with_retitled_repost_is_not_new(cfg, tmp_path):
    db = tmp_path / "t.db"
    one_group = replace(cfg, groups=cfg.groups[:1], search=replace(cfg.search, max_calls=1))
    first = FakeSearch({"Software Engineering Manager": [make(job_id="a", title="Engineering Manager")]})
    assert runner.run(one_group, search_fn=first, db=db, save_csv=False).imported == 1
    repost = FakeSearch({"Software Engineering Manager": [
        make(job_id="zzz", title="Engineering Manager - Delray Beach, Florida", city="Delray Beach")]})
    # The first job's city is None in make(); give both a city so the signatures can match.
    tracker.update(1, location="Delray Beach, FL", db=db)
    again = runner.run(one_group, search_fn=repost, db=db, save_csv=False)
    assert again.imported == 0 and again.duplicates == 1


def test_scores_are_saved_for_new_jobs_only(cfg, tmp_path):
    from jobscout.scorer import Score
    db = tmp_path / "t.db"
    asked = []

    def fake_score(jobs):
        asked.extend(j.job_id for j in jobs)
        return [Score(j.job_id, 8, "Good fit", ["MedTech"], ["Travel unknown"]) for j in jobs]

    one_group = replace(cfg, groups=cfg.groups[:1], search=replace(cfg.search, max_calls=1))
    search = FakeSearch({"Software Engineering Manager": [make(job_id="a")]})
    summary = runner.run(one_group, search_fn=search, score_fn=fake_score, db=db, save_csv=False)
    assert summary.scored == 1 and asked == ["a"]
    row = tracker.list_all(db=db).iloc[0]
    assert row["score"] == 8 and row["verdict"] == "Good fit"
    assert tracker.unscored_job_ids(db=db) == set()
    runner.run(one_group, search_fn=search, score_fn=fake_score, db=db, save_csv=False)
    assert asked == ["a"]                     # second run: nothing new, nothing re-scored


def test_scoring_failure_keeps_the_import(cfg, tmp_path):
    def broken(jobs):
        raise RuntimeError("no API key")
    one_group = replace(cfg, groups=cfg.groups[:1], search=replace(cfg.search, max_calls=1))
    search = FakeSearch({"Software Engineering Manager": [make(job_id="a")]})
    summary = runner.run(one_group, search_fn=search, score_fn=broken, db=tmp_path / "t.db", save_csv=False)
    assert summary.imported == 1
    assert "no API key" in summary.errors[0]


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
    assert summary.dropped == {"remote": 1, "outside area": 1}
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
