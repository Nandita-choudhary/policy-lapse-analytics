# The Lapse That Isn't

**"Why are policyholders leaving?" → They're not. Their payments are.**

An end-to-end analytics project on a simulated Australian insurer: Python generates 24 months of
premium-payment history, PostgreSQL holds it as a star schema, and a Power BI dashboard shows that
**47.5% of ended policies were never cancelled by anyone** — the premium payments silently
failed until the policy died, taking **$8.7M of annual premium** with them over two years.

> ⚠️ **The data is simulated.** No real insurer's data is used here — premium and payment records are
> confidential. The generator is calibrated to published industry research (see
> [Sources](#sources)), and the pipeline, schema and measures would run unchanged on real data.

<!-- SCREENSHOTS: add 2-3 dashboard images here once the report is built -->
<!-- ![Overview page](docs/img/01-overview.png) -->

**[→ Open the live dashboard]()** · *(link added after publishing)*

---

## The findings

| # | Finding | So what |
| - | ------- | ------- |
| 1 | **47.5% of policy exits are involuntary** — the payments failed; the customer never chose to leave | Retention spend is aimed at the wrong half of the problem |
| 2 | **The expiry cliff** — once a stored card passes its expiry date, the failure rate goes from 4.2% to 30.3%. Expired cards cause **49% of all lapses** | A reminder before the expiry date prevents the lapse before it starts |
| 3 | **Retrying the dead** — hard dishonours were retried 36,770 times in 24 months and succeeded **zero** times | **$54k/yr** of dishonour fees paid for attempts that can never work |
| 4 | **The payday window** — a soft-dishonour retry landing on the 1st or 15th, or the two days after, succeeds **62.5%** of the time, against **23.7%** on any other day | Re-timing retries recovers roughly **5,700 more payments a year** |

**Recommendations:** stop retrying hard dishonours · move soft-dishonour retries into the payday
window · warn customers before their card expires.

*(Findings 2 and 4 overlap — both prevent lapses — so their values are stated separately rather
than summed.)*

---

## How it is built

```
Python generator  →  PostgreSQL (Supabase)  →  Power BI
  simulated data       star schema              4-page report
                            ↑
                  Python risk model writes
                  failure scores back
```

| Layer | What it does | Where |
| ----- | ------------ | ----- |
| `etl/generate_data.py` | Builds the simulated insurer: 7 tables, 24 months | Python |
| `etl/load_to_postgres.py` | Loads the star schema into Supabase | Python + SQL |
| `sql/schema.sql` | Table definitions, keys and indexes | PostgreSQL |
| `model/predict_failures.py` | Logistic regression scoring next month's payment-failure risk | Python |
| `powerbi/` | The report, saved as a Power BI Project (`.pbip`) — model and DAX in plain text | Power BI |

### The data model

A star schema: `fact_payments`, one row per premium payment attempt, sits at the centre. Two
smaller fact tables, for ended policies and risk scores, share the same five dimensions.

| Table | One row is | Why it exists |
| ----- | ---------- | ------------- |
| `fact_payments` | one premium payment attempt | the heart — every finding comes from here |
| `fact_lapse_events` | one ended policy | splits cancelled from lapsed |
| `fact_risk_scores` | one active policy, scored for its next premium | the risk model's output — page 4's list of who to contact |
| `dim_customer` | one policyholder | segments and cohorts |
| `dim_policy` | one policy | product mix and premium value |
| `dim_payment_method` | one stored card or direct debit | powers the expiry cliff |
| `dim_decline` | one dishonour reason | hard vs soft — powers the retry analysis |
| `dim_date` | one calendar day | time intelligence and the payday flag |

Full column definitions: [`docs/data-dictionary.md`](docs/data-dictionary.md)

---

### Predicting the next failure

A logistic regression scores every active policy for its next premium payment. It is trained on
the first 18 months and tested on the last 6 — a time-based split, not a random one, so the
model is never allowed to learn from a policy's future.

| | |
| - | - |
| Hold-out ROC AUC | **0.77** |
| Contacting the riskiest 5% of policies | catches **39%** of the coming failures |
| Strongest signal | an expired card multiplies the odds of failure by **11.7** |
| Next strongest | each past failure multiplies them by **1.6**; paying by direct debit rather than card divides them by **2.2** |

Logistic regression was chosen over something heavier on purpose: every coefficient can be read
out loud, which is what the people acting on the list would need.

---

## Running it yourself

```bash
pip install -r requirements.txt
python etl/generate_data.py            # writes CSVs into data/ (~15 seconds)
python etl/load_to_postgres.py         # needs a .env with your database URL
python model/predict_failures.py       # writes risk scores back to the database
```

Step-by-step, including the GitHub and Supabase setup: [`docs/setup-steps.md`](docs/setup-steps.md).
Building the report: [`docs/powerbi-build-guide.md`](docs/powerbi-build-guide.md).

---

## Sources

The simulation's failure rates and lapse mix are calibrated to:

- LexisNexis Risk Solutions — [*True Impact of Failed Payments*](https://risk.lexisnexis.com/global/en/insights-resources/research/true-impact-of-failed-payments)
- Harvard Business Review — [*Only 3% of Companies' Data Meets Basic Quality Standards*](https://hbr.org/2017/09/only-3-of-companies-data-meets-basic-quality-standards)

<!-- Add any further sources used when calibrating -->

---

## Future work

- A grounded AI chat over the results — already built and live in my other project,
  [DataValix](https://www.datavalix.com)
- A downloadable `.pbit` template so others can point this report at their own data

---

Built by Nandita Choudhary · [LinkedIn]() · [DataValix](https://www.datavalix.com)
