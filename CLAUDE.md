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
4. **The payday window** — soft-dishonour retries succeed 62.5% on the 1st or 15th or the two days after, vs 23.7% on other days

`etl/generate_data.py` prints a check of all four every time it runs, including every number the
README quotes. Run it after any change to the generator and confirm the numbers still hold.

## Architecture

```
etl/generate_data.py      →  data/*.csv
etl/load_to_postgres.py   →  Supabase PostgreSQL (star schema, sql/schema.sql)
model/predict_failures.py →  risk scores written back to the database
powerbi/                  →  Power BI report, saved as .pbip (plain text, version controlled)
```

Three fact tables share five dimensions. `fact_payments` (grain = one premium payment attempt) is
the centre; `fact_lapse_events` has one row per ended policy and `fact_risk_scores` one row per
scored active policy. Full definitions in `docs/data-dictionary.md`.

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

Nandita's phase plan, updated 4 October 2026. Keep the Status column current as work finishes.

| # | Phase | Where | Status | How to tackle |
| - | ----- | ----- | ------ | ------------- |
| 0 | GitHub repo + folder structure + README | Mac | Git started 4 Oct (`main` + `fix-pass`); GitHub repo not created yet | Follow `docs/setup-steps.md` §1 |
| 1 | Data generator, four planted patterns | Mac | Fix pass under way on `fix-pass`; all four patterns verified 4 Oct | Re-run after any change and check the printed numbers; quick plots optional |
| 2 | ETL → Supabase, star schema, data dictionary | Mac | Code done; loader tested against a stand-in database; needs a Supabase project and a run | Verify row counts after the load |
| 3 | Failure model, scores → Postgres | Mac | Code done; runs from the CSVs (AUC 0.769); writing to the database waits for phase 2 | Document every feature in plain words |
| 4 | Power BI: model, DAX, 4 pages, .pbip | EC2 | Fully specified in `docs/powerbi-build-guide.md`; build pending | 5–7 days. Start the machine each session, STOP it after; commit .pbip each time |
| 5 | Publish + README screenshots + citations | Both | Not started | 2 days. Needs a work-style email: create one @datavalix.com |
| 6 | Resume bullets + LinkedIn post + interview practice | — | Not started | 1 day. Explain the schema, one measure and the finding out loud |

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
- **The 84% who pay after a failed premium pay by phone; the expired card stays on file.** That
  is deliberate: it is why an expired card fails month after month (2.3 months on average) until
  the policy lapses. Do not "fix" it by updating the card when they pay. That was tested on
  3 October 2026: the involuntary share fell from 47.5% to 40.3%, the expiry cliff from 30.3% to
  9.9%, and the model's AUC from 0.77 to 0.66.
