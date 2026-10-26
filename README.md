# jobscout

A small job-search agent, built as a Python learning project.

**Step 1 (this version):** fetch postings from JSearch, store them as CSV, explore them in a notebook.
**Step 2:** score each posting against my background with the Claude API.
**Step 3:** schedule it and send a daily digest.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) (manages Python versions and virtual environments):
   - Windows (PowerShell): `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`
   - macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. From this folder:
   ```
   uv sync
   ```
   This creates `.venv/` and installs everything in `pyproject.toml`. It's the equivalent of `dotnet restore`.
3. Copy `.env.example` to `.env` and add your RapidAPI key for JSearch.

## Run

```
uv run jobscout --sample                                   # offline, no key needed
uv run jobscout "technical program manager in Florida"
uv run jobscout "engineering manager" --remote --since 3days
uv run pytest                                              # run the tests
```

Results accumulate in `data/jobs.csv` (duplicates removed by job ID).

## Scoring with Claude (step 2)

1. Write `profile.md` in the project root (git-ignored).
2. Add `ANTHROPIC_API_KEY` to `.env`.
3. Fill in the two TODOs in `src/jobscout/scorer.py`. `uv run pytest tests/test_scorer.py -v` tells you when `parse_response` is right.
4. Score a handful of jobs, then compare in `notebooks/02_compare_scores.ipynb`:
   ```
   uv run jobscout-score --limit 5
   uv run jobscout-score --limit 5 --rescore    # after changing the prompt
   ```
Scores are cached in `data/scores.json` by job ID, so reruns don't cost anything.

## Tracker (Streamlit page)

```
uv run streamlit run src/jobscout/app.py
```

Add applications by hand or import fetched jobs, edit status/notes/follow-up dates in the grid,
and see what follow-ups are due. Data lives in `data/tracker.db` (SQLite, git-ignored).
Storage code is in `src/jobscout/tracker.py`; the page is `src/jobscout/app.py`.

## Notebook

Open `notebooks/01_explore.ipynb` in VS Code. When it asks for a kernel, pick the
interpreter in this project's `.venv` folder.

## Layout

```
pyproject.toml          project file and dependencies (like a .csproj)
.env                    secrets, never committed
src/jobscout/
    models.py           Job dataclass
    jsearch.py          API client
    store.py            CSV persistence via pandas
    cli.py              command-line entry point
notebooks/              exploration
data/                   output, plus sample_jobs.json for offline practice
tests/
```
