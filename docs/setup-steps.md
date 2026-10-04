# Setup steps

The ordered list, from this folder to a loaded database. Everything here runs on the Mac and
costs nothing. Tick them off as you go.

Open this folder in VS Code and run `claude` in the terminal — Claude Code reads `CLAUDE.md`
automatically and will know what the project is.

---

## 1 · Put it on GitHub

- [ ] Go to github.com → **+** (top right) → **New repository**
- [ ] Name: `policy-lapse-analytics` · **Public** · do **not** tick "Add a README" (there is one here already)
- [ ] **Create repository**
- [ ] In this folder, in the terminal:

```bash
git init
git add .
git commit -m "Data generator, star schema and loader for the policy-lapse project"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/policy-lapse-analytics.git
git push -u origin main
```

Replace `YOUR-USERNAME`. If git asks who you are, set it once:

```bash
git config --global user.name "Nandita Choudhary"
git config --global user.email "your@email.com"
```

- [ ] Refresh the repo page — the README should be rendering

## 2 · Install the Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `.venv` folder is gitignored. Run `source .venv/bin/activate` at the start of every session.

## 3 · Generate the data

```bash
python etl/generate_data.py
```

Takes about 15 seconds and writes seven CSVs into `data/`. It prints a check of the four
findings at the end — confirm they are all there:

| Finding | Expected |
| ------- | -------- |
| Involuntary share of exits | ~47% |
| Failure rate before / after card expiry | ~4% → ~30% |
| Hard-dishonour retries that succeeded | 0 |
| Retry success inside / outside payday window | ~53% / ~21% |

The big CSVs are gitignored; `data/sample/` has a 200-row sample of each table and **is**
committed, so the repo shows the data's shape without carrying 43MB.

- [ ] `git add data/sample && git commit -m "Add sample rows" && git push`

## 4 · Create the database

- [ ] Go to supabase.com → sign in → **New project**
- [ ] Name it `policy-lapse-analytics`, region **Sydney**, and **write the database password down** — it is shown once
- [ ] Wait for it to finish starting (a minute or two)
- [ ] Project Settings → Database → Connection string → **URI** → copy it
- [ ] In this folder:

```bash
cp .env.example .env
```

- [ ] Open `.env` and paste your URI in, replacing `[YOUR-PASSWORD]` with the real password

`.env` is gitignored. Check it never appears in `git status` before you commit — that string is
a password to a live database.

## 5 · Create the tables

```bash
psql "$(grep DATABASE_URL .env | cut -d= -f2-)" -f sql/schema.sql
```

If `psql` is not installed: `brew install libpq && brew link --force libpq`.

If brew is not installed either, the fallback needs no tools at all — open the Supabase
dashboard → **SQL Editor** → paste the contents of `sql/schema.sql` → **Run**.

## 6 · Load the data

```bash
python etl/load_to_postgres.py
```

It prints a row count per table as it goes. `fact_payments` should land around 770,000.

- [ ] In Supabase → Table Editor, check the tables have rows

## 7 · Run the model

```bash
python model/predict_failures.py
```

It trains on the first 18 months, tests on the last 6, prints how well it did, scores every
active policy and writes `fact_risk_scores` back to the database.

Expect ROC AUC around 0.77, and a line saying contacting the riskiest 5% of policies catches
roughly 39% of the coming failures. **Read the "What the model learned" list before you move
on** — those eight lines are what an interviewer will ask you to explain.

- [ ] `git add -A && git commit -m "Add payment-failure prediction model" && git push`

---

## Then: the dashboard

Everything above is free and on the Mac. Phase 4 needs Power BI Desktop, which is
Windows-only — that is what the rented machine is for, and it bills by the hour.

→ **[`powerbi-build-guide.md`](powerbi-build-guide.md)** has the whole build written out:
connection settings, every relationship, every measure's DAX, and a visual-by-visual layout for
all four pages. Work through it on the Mac first so the Windows time is only clicking.

**Before switching that machine on, the four things in §0 of the guide must be done.** Starting
it with an empty database is paying rent to look at a blank screen.
