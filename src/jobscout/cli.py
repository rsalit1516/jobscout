"""Command-line entry point.

    uv run jobscout "technical program manager" --remote
    uv run jobscout --sample            # no API key needed
"""

import argparse

from jobscout import jsearch, store


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch job postings from JSearch.")
    parser.add_argument("query", nargs="?", default="technical program manager in Florida")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--since", default="week", choices=["all", "today", "3days", "week", "month"])
    parser.add_argument("--remote", action="store_true", help="remote jobs only")
    parser.add_argument("--sample", action="store_true", help="use offline sample data")
    args = parser.parse_args()

    if args.sample:
        jobs = jsearch.load_sample()
    else:
        jobs = jsearch.search(args.query, pages=args.pages, date_posted=args.since, remote_only=args.remote)

    path = store.save(jobs)
    print(f"Fetched {len(jobs)} jobs -> {path}")   # f-strings = C# $"..." interpolation
    for job in jobs[:10]:                          # slicing: first 10, like .Take(10)
        where = "Remote" if job.is_remote else f"{job.city}, {job.state}"
        print(f"  {job.title} | {job.employer} | {where}")


def score_main() -> None:
    """uv run jobscout-score [--limit 5] [--rescore]"""
    import pandas as pd
    from jobscout import scorer
    from jobscout.models import Job

    parser = argparse.ArgumentParser(description="Score saved jobs with Claude.")
    parser.add_argument("--limit", type=int, default=5, help="score at most N jobs (start small!)")
    parser.add_argument("--rescore", action="store_true", help="ignore cached scores")
    args = parser.parse_args()

    df = store.load()
    # Rebuild Job objects from the CSV rows. NaN (pandas' "missing") becomes None.
    rows = df.astype(object).where(pd.notna(df), None).to_dict("records")
    jobs = [Job(**row) for row in rows][: args.limit]

    scores = scorer.score_jobs(jobs, rescore=args.rescore)
    titles = {j.job_id: f"{j.title} @ {j.employer}" for j in jobs}   # dict comprehension
    for s in sorted(scores, key=lambda s: s.score, reverse=True):     # lambda = C# s => s.Score
        print(f"{s.score:>2}  {titles.get(s.job_id, s.job_id)}")
        print(f"    {s.verdict}")


# Runs only when executed directly (python -m jobscout.cli), not when imported.
# There's no Main() convention in Python; this idiom is the equivalent.
if __name__ == "__main__":
    main()
