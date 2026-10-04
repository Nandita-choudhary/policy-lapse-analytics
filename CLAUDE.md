# Project context for Claude Code

Read this before changing anything in this repo.

## What this is

A portfolio project for data / reporting analyst roles in Australia. It is **not** a product and
has no users. Its only job is to prove skill to a recruiter or an interviewer, so the quality
bar is: *would a hiring manager at an insurer be impressed, and could Nandita explain every line
of it out loud in an interview?*

**The headline:** "Why are policyholders leaving?" → They're not. Their payments are.

A simulated Australian insurer discovers that **47.5% of its ended policies were never cancelled
by anyone** — the premium payments quietly failed until the policy died.

## The four findings the dashboard must show

These are deliberately built into the generated data. If a change to `etl/generate_data.py`
makes any of them disappear, the change is wrong.

1. **The lapse that isn't** — 47.5% of policy exits are involuntary (payment failure, not a decision)
2. **The expiry cliff** — first-attempt failure rate goes 4.2% → 30.3% once a stored card expires
3. **Retrying the dead** — hard dishonours retried 36,770 times, succeeded 0 times, $54k/yr in fees
4. **The payday window** — retries succeed 53% vs 21% inside/outside the 2 days after the 1st and 15th

`etl/generate_data.py` prints a check of all four every time it runs. Run it after any change to
the generator and confirm the numbers still hold.

## Architecture

```
etl/generate_data.py      →  data/*.csv
etl/load_to_postgres.py   →  Supabase PostgreSQL (star schema, sql/schema.sql)
model/predict_failures.py →  risk scores written back to the database
powerbi/                  →  Power BI report, saved as .pbip (plain text, version controlled)
```

One fact table (`fact_payments`, grain = one premium payment attempt) with six dimensions around
it. Full definitions in `docs/data-dictionary.md`.

## Conventions

- **Plain language in comments.** Explain *why*, not *what*. The code is read by interviewers.
- **Tunable constants live at the top of the file**, never buried in the logic.
- **Fixed random seed** (`SEED` in the generator) so the dataset is identical on every run.
- Table and column names are `snake_case`; dimensions are `dim_*`, facts are `fact_*`.
- Python: standard library + pandas/numpy/sklearn. No heavy frameworks.

## Hard rules

- **Never commit secrets.** `.env` is gitignored and must stay that way. The Supabase connection
  string must never appear in any committed file, including notebooks and markdown.
- **Never commit the generated CSVs** — `data/*.csv` is gitignored. `data/sample/` holds a
  200-row sample of each table, and that *is* committed, so the repo shows the data's shape.
- **Always say the data is simulated.** The README states it up front. Findings are framed as
  "what the dashboard reveals in this scenario", never as claims about real insurers.
- **Keep the scope small.** No AI chat, no extra data sources, no fifth dashboard page. New ideas
  go in the README's "Future work" list, not the build.

## Where things stand

| Phase | What | Status |
| ----- | ---- | ------ |
| 0 | Repo scaffold, README, data dictionary | Done |
| 1 | Data generator, four patterns verified | Done |
| 2 | SQL schema + Postgres loader written | Code done — needs a Supabase project and a run |
| 3 | Payment-failure prediction model | Code done — needs the database loaded first |
| 4 | Power BI: model, DAX, 4 pages, save as .pbip | Fully specified in `docs/powerbi-build-guide.md` — every relationship, measure and visual. Build pending |
| 5 | Publish report, README screenshots | Pending |
| 6 | Resume bullets, interview practice | Pending |

**Still undecided:** the insurer's name. The repo name does not depend on it. Candidates:
Renewly, CoverKeep, TrueCover. Once chosen, use it consistently in the README and the dashboard.

## Things that are easy to get wrong

- **Phase 4 runs on a rented Windows machine** (Power BI Desktop is Windows-only). It bills by the
  hour, so all thinking happens on the Mac first — see `docs/powerbi-build-guide.md`. Stop the
  machine after every session.
- **The payday finding is fragile.** It only works because customers' billing days are spread
  across the month. If a change makes everyone bill on the same day, the finding becomes an
  artefact. (This bug existed in the first version and was fixed.)
- **`attempt_number`** — row counts and failure rates mean different things for first attempts vs
  retries. Most "failure rate" measures should filter to `attempt_number = 1`.
