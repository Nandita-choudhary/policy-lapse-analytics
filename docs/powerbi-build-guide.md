# Power BI build guide

Everything needed to build the report, written down **before** the Windows machine is
switched on. That machine bills by the hour; thinking is free on the Mac. Work through this
top to bottom and the session is mostly copy, paste and click.

---

## 0. Before you start the machine

- [ ] `python etl/generate_data.py` has run
- [ ] Supabase project exists, `sql/schema.sql` has been run against it
- [ ] `python etl/load_to_postgres.py` has run — all seven tables have rows
- [ ] `python model/predict_failures.py` has run — `fact_risk_scores` has rows
- [ ] The Supabase host, database name, user and password are written down somewhere you can
      reach from the Windows machine (not committed to the repo)
- [ ] The repo is pushed to GitHub, so you can `git clone` it on the Windows side

## 1. Session routine — every single time

**Start:** AWS → EC2 → Instances → your machine → Instance state → Start instance → wait 2 min
→ copy the **new** Public IPv4 address → paste into the remote desktop app → connect.

**Finish:** `git push` → close the remote desktop → AWS → Instance state → **Stop instance**.

The public IP changes on every restart. If it will not connect, that is almost always why.

---

## 2. Connect Power BI to the database

Home → Get data → **PostgreSQL database**

| Field | Value |
| ----- | ----- |
| Server | `db.xxxxxxxxxxxx.supabase.co:5432` (your project's host, with the port) |
| Database | `postgres` |
| Data Connectivity mode | **Import** |

Sign in with **Database** credentials: user `postgres`, and your project password. On the
encryption warning, continue — Supabase requires SSL and the connector handles it.

Select all eight tables: `dim_date`, `dim_decline`, `dim_customer`, `dim_policy`,
`dim_payment_method`, `fact_payments`, `fact_lapse_events`, `fact_risk_scores` → **Load**.

> Import mode pulls the ~770,000 payment rows into the file. That is the right choice here:
> the data never changes, the report stays fast, and it still works if the database is asleep.

---

## 3. Build the model — and avoid the classic trap

Model view. Create these relationships, all **many-to-one, single direction**:

| From | To |
| ---- | -- |
| `fact_payments[date_id]` | `dim_date[date_id]` |
| `fact_payments[policy_id]` | `dim_policy[policy_id]` |
| `fact_payments[customer_id]` | `dim_customer[customer_id]` |
| `fact_payments[method_id]` | `dim_payment_method[method_id]` |
| `fact_payments[decline_id]` | `dim_decline[decline_id]` |
| `fact_lapse_events[policy_id]` | `dim_policy[policy_id]` |
| `fact_lapse_events[end_date]` | `dim_date[date_id]` |
| `fact_risk_scores[policy_id]` | `dim_policy[policy_id]` |

**Delete any relationship Power BI auto-created between two dimensions** — in particular
`dim_policy[customer_id] → dim_customer` and `dim_payment_method[customer_id] → dim_customer`.

This is the thing to be ready to explain in an interview. In a star schema the facts connect
to the dimensions and the dimensions do not connect to each other. If `dim_policy` also joins
`dim_customer`, there are two routes from `fact_payments` to `dim_customer` — directly, and the
long way round through `dim_policy`. Power BI cannot tell which one you meant, so it refuses or
quietly deactivates one, and the numbers stop being trustworthy. Keeping the dimensions
separate keeps exactly one path to every table.

**Then mark the date table:** select `dim_date` → Table tools → **Mark as date table** → date
column `date_id`. Without this, every time-intelligence measure below returns wrong answers.

**Hide from report view** (right-click → Hide): every `*_id` column except the ones used in
slicers, and `fact_risk_scores[premium_amount]` (it duplicates `dim_policy[premium_amount]`).

---

## 4. Apply the theme

View → Themes → **Browse for themes** → `powerbi/theme.json` from the repo.

It sets the eight chart colours, the status colours, fonts and gridlines in one go, so nothing
is picked by hand per visual. The palette is colourblind-safe (validated: worst adjacent-pair
separation ΔE 9.1 under protanopia, 19.6 for normal vision).

Three of the eight colours — aqua, yellow and magenta, slots 3 to 5 — sit below 3:1 contrast
against the light background, so **any chart that uses them must carry visible data labels**.
Charts with two or three series never reach them, which is most of this report.

---

## 5. Two calculated columns

Both go on `fact_payments` (Table tools → New column). These exist because the expiry story
needs each payment positioned relative to its own card's expiry date, which no column holds yet.

```dax
Months Since Card Expiry =
VAR Expiry = RELATED ( dim_payment_method[card_expiry_date] )
RETURN
    IF (
        ISBLANK ( Expiry ),
        BLANK (),                                  -- direct debits have no expiry date
        DATEDIFF ( Expiry, fact_payments[date_id], MONTH )
    )
```

Negative is before the card expired, 0 is the month it expired, positive is after.

```dax
Card Status =
VAR Expiry = RELATED ( dim_payment_method[card_expiry_date] )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Expiry ), "Direct debit",
        fact_payments[date_id] > Expiry, "Card expired",
        "Card valid"
    )
```

---

## 6. The measures

Create a blank table called **`_Measures`** first (Home → Enter data → name it `_Measures` →
Load), then build every measure inside it. They all sort to the top of the field list and none
of them pretend to belong to a real table.

### Income and volume

```dax
Premium Collected =
CALCULATE ( SUM ( fact_payments[amount] ), fact_payments[payment_status] = "Success" )
```

```dax
Active Policies =
VAR AsOf = MAX ( dim_date[date_id] )
VAR Started =
    CALCULATE (
        COUNTROWS ( dim_policy ),
        REMOVEFILTERS ( dim_date ),
        dim_policy[start_date] <= AsOf
    )
VAR Ended =
    CALCULATE (
        COUNTROWS ( fact_lapse_events ),
        REMOVEFILTERS ( dim_date ),
        fact_lapse_events[end_date] <= AsOf
    )
RETURN
    Started - Ended
```

### Payment health

Note the `attempt_number = 1` filter. A "failure rate" that counts retries is not a failure
rate — retries are mostly failures by definition, so including them inflates it two to three
times over. Every rate measure here counts scheduled payments only.

```dax
First Attempts =
CALCULATE ( COUNTROWS ( fact_payments ), fact_payments[attempt_number] = 1 )
```

```dax
Failed First Attempts =
CALCULATE (
    COUNTROWS ( fact_payments ),
    fact_payments[attempt_number] = 1,
    fact_payments[payment_status] = "Failed"
)
```

```dax
Failure Rate = DIVIDE ( [Failed First Attempts], [First Attempts] )
```

```dax
Dishonour Fees =
CALCULATE ( SUM ( fact_payments[fee] ), fact_payments[payment_status] = "Failed" )
```

### The headline

```dax
Policies Ended = COUNTROWS ( fact_lapse_events )
```

```dax
Policies Lapsed = CALCULATE ( [Policies Ended], fact_lapse_events[end_type] = "Lapsed" )
```

```dax
Policies Cancelled = CALCULATE ( [Policies Ended], fact_lapse_events[end_type] = "Cancelled" )
```

```dax
Involuntary Share = DIVIDE ( [Policies Lapsed], [Policies Ended] )
```

```dax
Annual Premium Lost =
SUMX (
    FILTER ( fact_lapse_events, fact_lapse_events[end_type] = "Lapsed" ),
    VAR Premium = RELATED ( dim_policy[premium_amount] )
    VAR Frequency = RELATED ( dim_policy[billing_frequency] )
    RETURN Premium * IF ( Frequency = "Monthly", 12, 1 )
)
```

### Retries

```dax
Retry Attempts =
CALCULATE ( COUNTROWS ( fact_payments ), fact_payments[attempt_number] > 1 )
```

```dax
Retry Successes =
CALCULATE (
    COUNTROWS ( fact_payments ),
    fact_payments[attempt_number] > 1,
    fact_payments[payment_status] = "Success"
)
```

```dax
Retry Success Rate = DIVIDE ( [Retry Successes], [Retry Attempts] )
```

```dax
Wasted Retries =
CALCULATE (
    COUNTROWS ( fact_payments ),
    fact_payments[attempt_number] > 1,
    fact_payments[payment_status] = "Failed",
    dim_decline[decline_category] = "Hard"
)
```

```dax
Wasted Retry Fees =
CALCULATE (
    SUM ( fact_payments[fee] ),
    fact_payments[attempt_number] > 1,
    fact_payments[payment_status] = "Failed",
    dim_decline[decline_category] = "Hard"
)
```

```dax
Recoverable Retries =
VAR InWindow =
    CALCULATE (
        [Retry Success Rate],
        REMOVEFILTERS ( dim_date[is_payday_window] ),
        dim_date[is_payday_window] = TRUE
    )
VAR Outside =
    CALCULATE (
        [Retry Success Rate],
        REMOVEFILTERS ( dim_date[is_payday_window] ),
        dim_date[is_payday_window] = FALSE
    )
VAR RetriesOutside =
    CALCULATE (
        [Retry Attempts],
        REMOVEFILTERS ( dim_date[is_payday_window] ),
        dim_date[is_payday_window] = FALSE
    )
RETURN
    ( InWindow - Outside ) * RetriesOutside
```

### Risk

```dax
Premium at Risk = SUM ( fact_risk_scores[premium_at_risk] )
```

```dax
Policies at High Risk =
CALCULATE (
    COUNTROWS ( fact_risk_scores ),
    fact_risk_scores[risk_band] IN { "High", "Very high" }
)
```

### Change over time

```dax
Premium Collected MoM % =
VAR Prior = CALCULATE ( [Premium Collected], DATEADD ( dim_date[date_id], -1, MONTH ) )
RETURN
    DIVIDE ( [Premium Collected] - Prior, Prior )
```

```dax
Failure Rate YoY pp =
VAR Prior = CALCULATE ( [Failure Rate], DATEADD ( dim_date[date_id], -12, MONTH ) )
RETURN
    [Failure Rate] - Prior
```

**Set the formats now, not later:** currency with 0 decimals for the dollar measures,
percentage with 1 decimal for the rates, whole number for the counts.

---

## 7. The four pages

Page size: 16:9, 1280 × 720. Leave a 24px margin, and give every page the same title bar at the
top left so they read as one report.

Each page answers one question, and the answer is the first thing the eye lands on.

### Page 1 · Overview — *"How healthy is premium income, really?"*

| Position | Visual | Fields |
| -------- | ------ | ------ |
| Top row, 4 cards | Card | `Premium Collected` · `Active Policies` · `Failure Rate` · `Involuntary Share` |
| Left, half width | Line chart | Axis `dim_date[year_month]`, Y `Premium Collected` |
| Right, half width | Line chart | Axis `dim_date[year_month]`, Y `Failure Rate` |
| Bottom, full width | **Stacked** column chart | Axis `dim_date[year_month]`, Y `Policies Ended`, Legend `fact_lapse_events[end_type]` |

Stacked is right for the bottom chart and only because Cancelled plus Lapsed *is* every exit —
the segments sum to a meaningful whole. Anywhere the parts do not sum to the total, use
side-by-side columns instead.

Single-series line charts need no legend; the title names the series.

### Page 2 · The lapse that isn't — *"Who chose to go, and whose payment just died?"*

| Position | Visual | Fields |
| -------- | ------ | ------ |
| Top left | Card, large | `Involuntary Share` — the headline number of the whole project |
| Top right | Card | `Annual Premium Lost` |
| Middle left | **Line chart** | Axis `fact_payments[Months Since Card Expiry]` filtered to −6…+6, Y `Failure Rate` |
| Middle right | Key influencers | Analyse `fact_lapse_events[end_type]`, Explain by product, state, channel, age band, `dim_payment_method[method_type]`, `bank` |
| Bottom left | Bar chart | Axis `dim_decline[decline_description]`, Y `Policies Lapsed` |
| Bottom right | Decomposition tree | Analyse `Policies Lapsed`, Explain by `end_reason`, `decline_category`, `decline_description`, `bank` |

The middle-left line chart is the expiry cliff and it is the most persuasive visual in the
report. A line is right because the x-axis is a continuous run of months and the shape — flat,
then a wall at month 0 — *is* the finding. Add a reference line at x = 0 labelled "card
expires".

### Page 3 · Wasted retries — *"What do failed premiums actually cost?"*

| Position | Visual | Fields |
| -------- | ------ | ------ |
| Top row, 3 cards | Card | `Dishonour Fees` · `Wasted Retry Fees` · `Retry Success Rate` |
| Middle left | **Clustered** column chart | Axis `fact_payments[attempt_number]` (2 and 3 only), Y `Retry Success Rate`, Legend `dim_decline[decline_category]` |
| Middle right | **Column chart** | Axis `dim_date[day_of_month]`, Y `Retry Success Rate` |
| Bottom | Table | `dim_decline[decline_description]`, `decline_category`, `Retry Attempts`, `Retry Success Rate`, `Wasted Retry Fees` |

Middle left is clustered, not stacked: Hard and Soft success rates are two separate rates, and
stacking rates on top of each other would mean nothing.

Middle right is the payday finding. Sort by day of month, not by value — the whole point is
*where* in the month the good days fall. Use conditional formatting on the bars so days in the
payday window are the brand blue and the rest are grey. Add a text box: "retries landing in the
two days after the 1st or the 15th succeed 2.6× as often."

### Page 4 · At risk next — *"Which premiums will fail next month, and what do we do?"*

| Position | Visual | Fields |
| -------- | ------ | ------ |
| Top row, 2 cards | Card | `Policies at High Risk` · `Premium at Risk` |
| Left | Bar chart | Axis `fact_risk_scores[risk_band]`, Y count of policies. Sort Low → Very high manually |
| Middle | Bar chart | Axis `risk_band`, Y `Premium at Risk` |
| Right | Table, top 50 | `policy_id`, `product`, `risk_score`, `premium_at_risk`, sorted descending |
| Bottom, full width | Text box | The three recommendations, each with its number |

The bottom text box is what turns the project from a dashboard into analysis. Write it plainly:

> **1. Stop retrying hard dishonours.** They were retried 36,770 times in 24 months and
> succeeded zero times. Saving: **$54,000 a year** in dishonour fees.
>
> **2. Move soft-dishonour retries into the payday window.** Retries in the two days after the
> 1st or 15th succeed 52.6% of the time against 20.5% on other days. Recovers roughly
> **5,300 more payments a year**.
>
> **3. Warn customers before their card expires.** Once a stored card passes its expiry date the
> failure rate goes from 4.2% to 30.3%, and expired cards are behind **47% of all lapses**.

Risk bands are an ordered category, so they are bars in order, not a donut. A donut is only for
three or four parts of a genuine whole, read at a glance.

---

## 8. The AI visuals

All free in Power BI Desktop; no Fabric capacity needed.

- **Key influencers** (page 2) — already in the table above. Set it to analyse `end_type` and
  watch it find the payment method and the bank.
- **Decomposition tree** (page 2) — let it drill `Policies Lapsed` down to the decline reason.
- **Anomaly detection** — on the page 1 failure-rate line chart: select it → Analytics pane →
  **Find anomalies** → Add.
- **Q&A visual** — put one on page 1. Then teach it the vocabulary an insurer would use:
  Modelling → Q&A setup → **Field synonyms**, and add *lapse*, *lapsed policy*, *involuntary
  exit* for `end_type`, and *dishonour*, *bounce*, *failed premium* for `payment_status`. Five
  minutes of synonyms is the difference between a demo that works and one that shrugs.

---

## 9. Save it as code

File → Options and settings → Options → **Preview features** → tick **Power BI Project (.pbip)
save option** → restart Power BI Desktop.

Then File → **Save as** → navigate into the cloned repo's `powerbi/` folder → save as
`LapseThatIsnt`.

That writes a folder of plain-text files — the model definition, every measure, every page's
layout — instead of one opaque binary. Commit it:

```
git add powerbi/
git commit -m "Add Power BI report: model, measures and four pages"
git push
```

Now a recruiter can read your DAX on GitHub without installing anything, and Claude Code can
edit those files like any other source file.

> `.gitignore` already excludes `.pbi/localSettings.json` and `cache.abf` — machine-specific
> files that would otherwise churn on every commit.

## 10. Publish and screenshot

**Publishing** needs a work or school email; a Gmail address is rejected. You own
datavalix.com, so create an address on that domain and sign up to Power BI with it. Then
Home → **Publish** → My workspace, and in the Power BI service: the report → File → **Embed
report** → *Publish to web (public)*. Copy the link into the README.

If that fails for any reason, plan B is just as good for a portfolio: screenshots plus a short
screen-recording GIF in the README. Do not lose a day to it.

**Screenshots for the README** — take these four, save them into `docs/img/`:

| File | What |
| ---- | ---- |
| `01-overview.png` | Page 1, whole page |
| `02-lapse.png` | Page 2, whole page — the hero image, leads the README |
| `03-expiry-cliff.png` | Just the expiry-cliff line chart, cropped |
| `04-risk.png` | Page 4, whole page |

Then update the README: swap the commented-out image lines for real ones, and paste the
published link into the "Open the live dashboard" line.

---

## If something does not work

| Symptom | Cause |
| ------- | ----- |
| "Can't determine relationships" / an auto-relationship is dotted | A dimension-to-dimension relationship snuck in. Delete it — see §3 |
| Time-intelligence measures return blank | `dim_date` was never marked as a date table |
| Failure rate looks like 11% not 5% | A measure is counting retries. Add `attempt_number = 1` |
| The payday chart is sorted by value | Click the visual's "…" → Sort axis → `day_of_month`, ascending |
| Remote desktop will not connect | The public IP changed when the machine restarted. Copy the new one |
