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
- [ ] The Supabase **Session pooler** host and user, the database name and the password are
      written down somewhere you can reach from the Windows machine (not committed to the repo)
- [ ] The repo is pushed to GitHub, so you can `git clone` it on the Windows side

## 1. Session routine — every single time

**Start:** AWS → EC2 → Instances → your machine → Instance state → Start instance → wait 2 min
→ copy the **new** Public IPv4 address → paste into the remote desktop app → connect.

**Finish:** `git push` → close the remote desktop → AWS → Instance state → **Stop instance**.

The public IP changes on every restart. If it will not connect, that is almost always why: in
Windows App, error **0x704** means the saved PC still has the old IP. Add the PC again with the
new one, and tick **Clipboard** under Devices & Audio as you add it, so you can paste. On the
Windows side, paste with **Ctrl+V**.

---

## 2. Connect Power BI to the database

**First, once per machine: trust Supabase's certificate.** Supabase encrypts connections with a
certificate signed by its own authority, which Windows does not know. Power BI therefore refuses
the connection ("the remote certificate is invalid").

1. In the Supabase dashboard: Project Settings → Database → **SSL Configuration** →
   **Download certificate**.
2. Copy the downloaded `prod-ca-2021.crt` to the Windows machine. Open PowerShell **as
   administrator** in that folder and run `certutil -addstore Root prod-ca-2021.crt`.

That adds it to the **Local Machine** store. Installing it for the Current User only is not
enough: Power BI still says "the remote certificate is invalid".

Then Home → Get data → **PostgreSQL database**

| Field | Value |
| ----- | ----- |
| Server | `aws-0-<region>.pooler.supabase.com:5432`: the **Session pooler** host from the Connect panel in Supabase |
| Database | `postgres` |
| Data Connectivity mode | **Import** |

Sign in with **Database** credentials: user `postgres.<project-ref>` (the Session pooler's user
name, shown in the same panel) and your database password.

Use the Session pooler, not the direct `db.<project-ref>.supabase.co` address. The direct
address has only an IPv6 address, which most networks cannot reach, a default EC2 machine
included.

Select all eight tables: `dim_date`, `dim_decline`, `dim_customer`, `dim_policy`,
`dim_payment_method`, `fact_payments`, `fact_lapse_events`, `fact_risk_scores` → **Load**.

Power BI names them `public dim_date` and so on. Rename all eight to drop the `public `
prefix (double-click each name in the Data pane): every measure below uses the plain names.

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
| `fact_lapse_events[customer_id]` | `dim_customer[customer_id]` |
| `fact_lapse_events[method_id]` | `dim_payment_method[method_id]` |
| `fact_lapse_events[end_date]` | `dim_date[date_id]` |
| `fact_lapse_events[final_decline_id]` | `dim_decline[decline_id]` |
| `fact_risk_scores[policy_id]` | `dim_policy[policy_id]` |
| `fact_risk_scores[customer_id]` | `dim_customer[customer_id]` |

Every fact table links to every dimension it holds a key for. Page 2 depends on the
`fact_lapse_events` links. Without them, "lapses by decline reason" shows the same number on
every bar, and the page 2 heatmap cannot split lapses by payment method at all.

**Fix the two one-to-one relationships.** `fact_lapse_events` and `fact_risk_scores` hold one
row per policy, so Power BI finds unique values on both sides of their `policy_id` links and
sets them to **one-to-one**. A one-to-one relationship always filters in both directions, which
would let a filter on ended policies reach `fact_payments` through `dim_policy`. Double-click
each of the two lines, set Cardinality to **Many to one (\*:1)** and Cross filter direction to
**Single**.

**Delete any relationship Power BI auto-created between two dimensions** — in particular
`dim_policy[customer_id] → dim_customer` and `dim_payment_method[customer_id] → dim_customer`.

This is the thing to be ready to explain in an interview. In a star schema the facts connect
to the dimensions and the dimensions do not connect to each other. If `dim_policy` also joins
`dim_customer`, there are two routes from `fact_payments` to `dim_customer` — directly, and the
long way round through `dim_policy`. Power BI cannot tell which one you meant, so it refuses or
quietly deactivates one, and the numbers stop being trustworthy. Keeping the dimensions
separate keeps exactly one path to every table.

**Power BI also builds relationships by itself** from the database's foreign keys when it loads
the tables, and some are wrong. Open Manage relationships, delete any that join two
dimensions, and set the rest to many-to-one, single direction and active, until the list
matches the table above.

**Then mark the date table:** select `dim_date` → Table tools → **Mark as date table** → date
column `date_id`. Without this, every time-intelligence measure below returns wrong answers.
Then turn off **Auto date/time** (File → Options and settings → Options → Current File → Data
Load), so Power BI stops adding a hidden date table for every date column.

**Hide from report view** (right-click → Hide) the columns that only link tables: every key
column in the three fact tables (including `fact_payments[payment_id]` and
`fact_lapse_events[end_date]`), the dimensions' `customer_id`, `method_id` and `decline_id`,
and `fact_risk_scores[premium_amount]` (it duplicates `dim_policy[premium_amount]`). Keep
`dim_date[date_id]`, which is the date itself, and `dim_policy[policy_id]`, which page 4 lists.

---

## 4. Apply the theme

Design → **Import theme** → `powerbi/theme.json` from the repo. (In older versions of Power BI
Desktop: View → Themes → Browse for themes.)

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

More columns help the axes, one sort and page 4's call list:

- `dim_date[Month Label]`: the month as people say it, `"Oct 24"`.
- `dim_date[Month Axis Label]`: the monthly charts' axis. It labels the first month of each
  quarter, so the labels fit without rotating.
- `fact_risk_scores[risk_band_order]`: sorts the risk bands Low → Very high. It is built in
  **Power Query**, not DAX. A DAX column can't be the sort-by column of the column it is built
  from: Power BI refuses to open the project and reports a circular dependency.
- `fact_risk_scores[Card Expiry]`: the stored card's expiry date, looked up by customer.
- `fact_risk_scores[Card Expires Before Next Premium]`: TRUE when the card still works at the
  end of the data but expires before the next premium is due. Page 4's call list filters on it.

---

## 6. The measures

Every measure lives in one table, **`_Measures`**, so they sort to the top of the field list
and none of them pretends to belong to a real table. It is a one-row DAX table,
`_Measures = ROW ( "Placeholder", 0 )`, with the placeholder column hidden. Display folders
group the measures as below.

The DAX here is copied from the project file
`powerbi/LapseThatIsnt.SemanticModel/definition/tables/_Measures.tmdl`, which is the source of
truth. Three lessons from building it are in the comments:

- Failure rates count first attempts only, `attempt_number = 1`, wrapped in KEEPFILTERS so a
  chart's own filter on attempt number still applies.
- Change measures return blank when there is nothing to compare, instead of the rate itself or
  −100%.
- A success rate is 0, not blank, when nothing worked, so the bar sits at zero rather than
  vanishing.

### Income and volume

```dax
Premium Collected =
CALCULATE ( SUM ( fact_payments[amount] ), fact_payments[payment_status] = "Success" )

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

```dax
First Attempts =
-- KEEPFILTERS so a chart split by attempt_number still splits. A plain filter here
-- would replace the chart's own attempt_number filter and every bar would match.
CALCULATE ( COUNTROWS ( fact_payments ), KEEPFILTERS ( fact_payments[attempt_number] = 1 ) )

Failed First Attempts =
CALCULATE (
    COUNTROWS ( fact_payments ),
    KEEPFILTERS ( fact_payments[attempt_number] = 1 ),
    fact_payments[payment_status] = "Failed"
)

Failure Rate =
DIVIDE ( [Failed First Attempts], [First Attempts] )

Dishonour Fees =
CALCULATE ( SUM ( fact_payments[fee] ), fact_payments[payment_status] = "Failed" )
```

### The headline

```dax
Policies Ended =
COUNTROWS ( fact_lapse_events )

Policies Lapsed =
CALCULATE ( [Policies Ended], fact_lapse_events[end_type] = "Lapsed" )

Policies Cancelled =
CALCULATE ( [Policies Ended], fact_lapse_events[end_type] = "Cancelled" )

Involuntary Share =
DIVIDE ( [Policies Lapsed], [Policies Ended] )

Involuntary Share All Customers =
-- The dashed line on page 2's by-state chart: the share across every customer,
-- the same on every bar, so each state can be compared with the whole book.
CALCULATE ( [Involuntary Share], REMOVEFILTERS ( dim_customer ) )

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
CALCULATE ( COUNTROWS ( fact_payments ), KEEPFILTERS ( fact_payments[attempt_number] > 1 ) )

Retry Successes =
CALCULATE (
    COUNTROWS ( fact_payments ),
    KEEPFILTERS ( fact_payments[attempt_number] > 1 ),
    fact_payments[payment_status] = "Success"
)

Retry Success Rate =
-- Zero, not blank, when retries happened and none worked, so the Hard bars show at 0%
DIVIDE ( COALESCE ( [Retry Successes], 0 ), [Retry Attempts] )

Soft Retry Success Rate =
CALCULATE ( [Retry Success Rate], dim_decline[decline_category] = "Soft" )

Soft Retry Rate Other Days =
-- The payday chart's dashed line: the soft-retry success rate on days outside the
-- payday window. It ignores which day a bar is for, so it is the same on every bar.
CALCULATE ( [Soft Retry Success Rate], REMOVEFILTERS ( dim_date ), dim_date[is_payday_window] = FALSE )

Wasted Retries =
CALCULATE (
    COUNTROWS ( fact_payments ),
    KEEPFILTERS ( fact_payments[attempt_number] > 1 ),
    fact_payments[payment_status] = "Failed",
    dim_decline[decline_category] = "Hard"
)

Wasted Retry Fees =
CALCULATE (
    SUM ( fact_payments[fee] ),
    KEEPFILTERS ( fact_payments[attempt_number] > 1 ),
    fact_payments[payment_status] = "Failed",
    dim_decline[decline_category] = "Hard"
)

Recoverable Payments =
VAR InWindow =
    CALCULATE ( [Soft Retry Success Rate], dim_date[is_payday_window] = TRUE )
VAR Outside =
    CALCULATE ( [Soft Retry Success Rate], dim_date[is_payday_window] = FALSE )
VAR SoftRetriesOutside =
    CALCULATE (
        [Retry Attempts],
        dim_decline[decline_category] = "Soft",
        dim_date[is_payday_window] = FALSE
    )
RETURN
    ( InWindow - Outside ) * SoftRetriesOutside

Soft Retry Rate Payday Bars =
-- The payday chart's blue bars: the soft-retry success rate, only on days in the payday
-- window. Two bar series with fixed colours, because a per-bar colour rule didn't show
-- in this combo chart.
IF ( SELECTEDVALUE ( dim_date[is_payday_window] ), [Soft Retry Success Rate] )

Soft Retry Rate Other Day Bars =
-- The payday chart's grey bars: the same rate on every other day of the month.
IF (
    HASONEVALUE ( dim_date[is_payday_window] )
        && NOT SELECTEDVALUE ( dim_date[is_payday_window] ),
    [Soft Retry Success Rate]
)
```

### Risk

```dax
Premium at Risk =
SUM ( fact_risk_scores[premium_at_risk] )

Policies Scored =
COUNTROWS ( fact_risk_scores )

Policies at High Risk =
CALCULATE (
    COUNTROWS ( fact_risk_scores ),
    fact_risk_scores[risk_band] IN { "High", "Very high" }
)

Chance of Failing =
-- The risk table's score column. Scores this close to 1 all round to 100.0%, which
-- overstates the certainty, so they read 99%+
VAR Score = SUM ( fact_risk_scores[risk_score] )
RETURN
    IF ( NOT ISBLANK ( Score ), IF ( Score >= 0.99, "99%+", FORMAT ( Score, "0.0%" ) ) )

Why At Risk =
-- The risk table's plain-words reason, from the policy's own payment history: whether its
-- stored card had expired by the scoring date, and how many premiums have failed so far
VAR Customer = SELECTEDVALUE ( fact_risk_scores[customer_id] )
VAR ScoredFor = SELECTEDVALUE ( fact_risk_scores[scored_for_date] )
VAR Expiry = LOOKUPVALUE ( dim_payment_method[card_expiry_date], dim_payment_method[customer_id], Customer )
VAR CardExpired = NOT ISBLANK ( Expiry ) && Expiry < ScoredFor
VAR Failed = COALESCE ( [Failed First Attempts], 0 )
VAR FailedText = IF ( Failed > 0, Failed & IF ( Failed = 1, " failed payment", " failed payments" ) )
RETURN
    IF (
        NOT ISBLANK ( Customer ),
        CONCATENATEX (
            FILTER ( { IF ( CardExpired, "Card expired" ), FailedText }, [Value] <> "" ),
            [Value],
            " " & UNICHAR ( 183 ) & " "
        )
    )
```

### Change over time

```dax
Premium Collected MoM % =
VAR ThisMonth = [Premium Collected]
VAR LastMonth = CALCULATE ( [Premium Collected], DATEADD ( dim_date[date_id], -1, MONTH ) )
RETURN
    -- A month with no payments has nothing to compare: blank, not a fall of 100%
    IF ( NOT ISEMPTY ( fact_payments ), DIVIDE ( ThisMonth - LastMonth, LastMonth ) )

Failure Rate YoY pp =
VAR ThisYear = [Failure Rate]
VAR LastYear = CALCULATE ( [Failure Rate], DATEADD ( dim_date[date_id], -12, MONTH ) )
RETURN
    -- Blank unless both years have payments. Otherwise the first 12 months show the
    -- rate itself (rate minus nothing) and the months past the data show minus last year
    IF ( NOT ISBLANK ( ThisYear ) && NOT ISBLANK ( LastYear ), ThisYear - LastYear )
```

### Per year

```dax
Years of Data =
-- How many years the payment history covers, first scheduled premium to last. Money
-- figures are divided by it so the report states every amount per year.
VAR FirstDue = CALCULATE ( MIN ( fact_payments[date_id] ), REMOVEFILTERS ( dim_date ), fact_payments[attempt_number] = 1 )
VAR LastDue = CALCULATE ( MAX ( fact_payments[date_id] ), REMOVEFILTERS ( dim_date ), fact_payments[attempt_number] = 1 )
RETURN
    DIVIDE ( DATEDIFF ( FirstDue, LastDue, MONTH ) + 1, 12 )

Premium Collected a Year =
DIVIDE ( [Premium Collected], [Years of Data] )

Dishonour Fees a Year =
DIVIDE ( [Dishonour Fees], [Years of Data] )

Wasted Retry Fees a Year =
-- Zero rather than blank wherever retries happened, so the format shows a dash for
-- soft declines (whose retries can work) instead of an empty cell
IF ( NOT ISBLANK ( [Retry Attempts] ), DIVIDE ( COALESCE ( [Wasted Retry Fees], 0 ), [Years of Data] ) )

Annual Premium at Risk =
-- Each active policy's premium for a year, weighted by its chance of failing at the
-- next payment: the premium a year expected to be lost if nothing changes
SUMX (
    fact_risk_scores,
    VAR Premium = RELATED ( dim_policy[premium_amount] )
    VAR Frequency = RELATED ( dim_policy[billing_frequency] )
    RETURN fact_risk_scores[risk_score] * Premium * IF ( Frequency = "Monthly", 12, 1 )
)

Annual Premium =
-- Each active policy's premium for a year, unweighted: page 4's call list
SUMX (
    fact_risk_scores,
    VAR Premium = RELATED ( dim_policy[premium_amount] )
    VAR Frequency = RELATED ( dim_policy[billing_frequency] )
    RETURN Premium * IF ( Frequency = "Monthly", 12, 1 )
)
```

## 7. The four pages

Page size: 16:9, 1280 × 720. Every page has the same dark header band: the page title and its
question on the left, a page navigator and "Simulated data · Oct 2024–Sep 2026" on the right.
Below it sits a row of KPI cards, then the charts.

Each chart title states its finding in plain words, using the README's numbers. One accent
colour marks the thing that matters and everything else is grey: orange for the problem, blue
for what works. Field names are renamed per visual into plain English. Every visual has alt
text, and every card has a tooltip defining its number.

The tables below list what is on each page, top to bottom.

### Page 1 · Overview: *"How healthy is premium income, really?"*

| Visual | Title or label | Shows |
| ------ | -------------- | ----- |
| Card | Premium collected a year |  |
| Card | Active policies |  |
| Card | Premiums that fail on the first try |  |
| Card | Ended policies nobody cancelled |  |
| Line chart | Premium collected grew over the two years | Month, Premium collected, Month name |
| Line chart | ...but more premiums now fail on the first try | Month, First-attempt failure rate, Month name |
| Stacked column chart | Nearly half the policies that end each month were never cancelled | Month, Policies ended, How it ended, Month name |

### Page 2 · The lapse that isn't: *"Who chose to go, and whose payment just died?"*

| Visual | Title or label | Shows |
| ------ | -------------- | ----- |
| Card | of ended policies were never cancelled |  |
| Card | annual premium of policies that lapsed, Oct 2024–Sep 2026 |  |
| Column chart | Once a card expires, first-attempt failures jump from 4.2% to 30.3% | Months from card expiry, First-attempt failure rate |
| Bar chart | Expired cards are behind 49% of all lapses | Decline reason, Policies lapsed |
| Column chart + line | Who they are barely matters: every state sits near 47.5% | State, Share that lapsed, All customers |
| Matrix (heatmap) | Card + monthly: 65.5% of ended policies lapsed, against 6.3% for direct debit + annual | Payment method, Billing frequency, Share that lapsed |

### Page 3 · Wasted retries: *"What do failed premiums actually cost?"*

| Visual | Title or label | Shows |
| ------ | -------------- | ----- |
| Card | Dishonour fees a year |  |
| Card | Fees a year on retries that can never work |  |
| Card | Retries that collected the premium |  |
| Stacked bar chart | Hard dishonours were retried 36,770 times and never succeeded | Type of dishonour, Outcome, Retries |
| Column chart + line | Soft retries succeed 62.5% in the payday window, 23.7% on other days | Day of month, Payday window, Other days, Other-days average |
| Table | Stopping hard-dishonour retries saves $54k a year | Decline reason, Hard or soft, Retries, Success rate, Wasted fees a year |

### Page 4 · At risk next: *"Which premiums will fail next month, and what do we do?"*

| Visual | Title or label | Shows |
| ------ | -------------- | ----- |
| Card | Policies at high or very high risk |  |
| Card | Premium at risk a year |  |
| Bar chart | Most active policies are low risk | Risk band, Policies |
| Bar chart | High-risk policies hold most of the premium at risk | Risk band, Premium at risk a year |
| Table | Call these 443 policies before their card expires | Policy, Product, Card expires, Next premium due, Premium a year |

Text boxes complete two pages. Page 1 has a headline: **4,623 policies** ended without anyone
cancelling them. Page 4 ends with the three recommendations, each sized honestly: $54,000 a
year in fees; a trial on half the soft retries, since about 5,700 more payments a year assumes
the payday effect holds; and up to $4.2M of annual premium lost to expired cards, since a
reminder won't save every policy. A footnote gives the risk model: logistic regression, AUC
0.77, the riskiest 5% catch 39% of failures.

Two build notes:

- The payday chart's bars are two measures with fixed colours, blue and grey. A per-bar colour
  rule was ignored by this combo chart, and every bar came out blue.
- KPI cards need small top and bottom padding (4px); at 10px the label under the number is
  cut off.

---

## 8. The AI visuals: tried, then replaced

The first build used four of Power BI's AI features. Three were replaced, because a reader got the
answer faster from a plain chart:

- **Key influencers** (page 2) found what was expected, card payment and monthly billing. But it
  re-runs its analysis every time the page opens, and its bubbles need explaining. A heatmap of
  lapse share by payment method × billing frequency replaced it: card + monthly 65.5%, against
  6.3% for direct debit + annual.
- **Decomposition tree** (page 2) showed nothing until clicked, and repeated the decline-reason
  chart beside it. It became lapse share by state, flat at about 47%: who customers are barely
  matters next to how they pay.
- **Q&A** (page 1) is being retired by Microsoft in February 2027 and showed a warning. A
  headline text box replaced it.
- **Anomaly detection** is still worth adding to page 1's failure-rate line: select it →
  Analytics pane → **Find anomalies** → Add. It is not in the saved report yet.

That trade-off, AI features out where plain charts read faster, is worth explaining in an
interview.

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

## 10. Export, screenshot and publish

**PDF.** File → Export → **Export to PDF**. This version of Power BI Desktop has no Print option,
and the export asks for no file name: Power BI builds the file and opens it in Edge from its temp
folder, `%TEMP%\2\Power BI Desktop\print-job-…\LapseThatIsnt.pdf`. Copy it from there to
`docs/lapse-that-isnt.pdf`.

**README images.** Don't screenshot the remote desktop, which scales the screen and blurs the
text. Render the PDF's pages instead: the PDF holds real text, so the images stay sharp. On the
Mac this was done with PDFKit, 1800 px wide, into `docs/img/`:

| File | What |
| ---- | ---- |
| `01-overview.png` | Page 1 |
| `02-lapse.png` | Page 2, the hero image at the top of the README |
| `03-retries.png` | Page 3 |
| `04-risk.png` | Page 4 |

For LinkedIn, post the PDF itself as a document: it shows as a swipeable carousel.

**Publishing** is optional. It needs a work or school email; a Gmail address is rejected. You own
datavalix.com, so create an address on that domain and sign up to Power BI with it. Then Home →
**Publish** → My workspace, and in the Power BI service: the report → File → **Embed report** →
*Publish to web (public)*. Put the link in the README.

---

## If something does not work

| Symptom | Cause |
| ------- | ----- |
| "Can't determine relationships" / an auto-relationship is dotted | A dimension-to-dimension relationship snuck in. Delete it — see §3 |
| A page 2 visual shows the same value on every bar | `fact_lapse_events` is missing one of its relationships — see §3 |
| Time-intelligence measures return blank | `dim_date` was never marked as a date table |
| Failure rate looks like 11% not 5% | A measure is counting retries. Add `attempt_number = 1` |
| The payday chart is sorted by value | Click the visual's "…" → Sort axis → `day_of_month`, ascending |
| The payday chart never rises above about 30% | It is using `Retry Success Rate`, which includes hard retries. Use `Soft Retry Success Rate` |
| Remote desktop will not connect | The public IP changed when the machine restarted. Copy the new one |
| "The remote certificate is invalid" | Supabase's certificate is not trusted on this machine yet. Install it — see §2 |
| Power BI cannot find the server | The direct `db.….supabase.co` address is IPv6-only. Use the Session pooler host — see §2 |
| Nothing connects after a quiet week | Free Supabase projects pause after a week without use. Supabase dashboard → **Restore project** |
| "A circular dependency was detected" when the project opens | A DAX column is the sort-by column of the column it is built from. Build the sort column in Power Query instead — see §5 |
| Windows App error 0x704 | The saved PC has an old IP. Add the PC again with the instance's new public IP |
| Copy and paste don't work in the remote desktop | Paste with Ctrl+V. If that fails, add the PC again with **Clipboard** ticked under Devices & Audio |
| Export to PDF seems to do nothing | It opens the file in Edge from Power BI's temp folder — see §10 |
| A card's label is cut off under the number | Lower the card's top and bottom padding to 4px |
| A chart ignores a per-bar colour rule | Split the bars into two measures with fixed colours — see §7 |
