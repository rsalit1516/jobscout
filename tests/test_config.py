import copy
import tomllib

import pytest

from jobscout import config


def test_shipped_config_loads():
    cfg = config.load()
    assert [g.name for g in cfg.groups][:3] == [
        "Software Engineering Manager", "Technical Project Manager", "Director of Software Engineering"]
    assert cfg.location.zip == "33446"
    assert cfg.location.min_lat < cfg.location.max_lat
    assert len(cfg.location.queries) >= 1


@pytest.fixture
def raw():
    with config.CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def test_missing_section_is_reported(raw):
    del raw["location"]
    with pytest.raises(ValueError, match="location"):
        config.parse(raw)


def test_no_groups_is_rejected(raw):
    raw["groups"] = []
    with pytest.raises(ValueError, match="groups"):
        config.parse(raw)


def test_bad_date_posted_and_bad_regex(raw):
    bad = copy.deepcopy(raw)
    bad["search"]["date_posted"] = "yesterday"
    with pytest.raises(ValueError, match="date_posted"):
        config.parse(bad)
    bad = copy.deepcopy(raw)
    bad["filters"]["title_include"] = ["(unclosed"]
    with pytest.raises(ValueError, match="pattern"):
        config.parse(bad)
