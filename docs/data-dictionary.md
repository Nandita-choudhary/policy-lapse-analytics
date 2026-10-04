# Data dictionary

Seven tables in a star schema. `fact_payments` is the centre; everything else explains a row
in it. All data is simulated — see the note in the [README](../README.md).

Row counts below are from the default run (50,000 policyholders, October 2024 – September 2026).

---

## fact_payments — 772,747 rows

**Grain: one premium payment attempt.** A payment that failed and was retried twice produces
three rows. That is deliberate: the retries are where the money leaks.

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `payment_id` | bigint | Primary key |
| `policy_id` | int | → `dim_policy` |
| `customer_id` | int | → `dim_customer` |
| `method_id` | int | → `dim_payment_method` |
| `date_id` | date | → `dim_date`. The day the attempt was made |
| `amount` | numeric | Premium being collected |
| `fee` | numeric | $0.28 if it succeeded, $2.95 dishonour fee if it failed |
| `attempt_number` | smallint | 1 = the original attempt, 2 and 3 = retries |
| `payment_status` | varchar | `Success` or `Failed` |
| `decline_id` | smallint | → `dim_decline`. Why the attempt failed, or, on a successful retry, the dishonour it recovered from. Null when the premium went through on the first attempt |

## fact_lapse_events — 9,798 rows

**Grain: one ended policy.** The headline of the whole project lives in `end_type`.

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `policy_id` | int | Primary key, → `dim_policy` |
| `customer_id` | int | → `dim_customer` |
| `method_id` | int | → `dim_payment_method`. The payment method on file when the policy ended. For a lapse, it's the one whose payments kept failing |
| `end_date` | date | → `dim_date` |
| `end_type` | varchar | `Cancelled` = the customer chose to leave. `Lapsed` = nobody chose anything; the payments stopped working |
| `end_reason` | varchar | `Customer request` or `Payment failure` |
| `final_decline_id` | smallint | → `dim_decline`. The dishonour that killed the policy. Null for cancellations |

---

## dim_date — 775 rows

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `date_id` | date | Primary key |
| `year`, `quarter`, `month_number`, `month_name`, `year_month` | — | Standard calendar attributes |
| `day_of_month`, `day_name`, `is_weekend` | — | Standard calendar attributes |
| `is_payday` | bool | True on the 1st and the 15th |
| `days_since_payday` | smallint | Days since the most recent payday (0 on a payday) |
| `is_payday_window` | bool | True on a payday and the two days after — when accounts have money again |

`is_payday_window` is the column that makes finding 4 visible. Mark it as a date table in Power
BI so time-intelligence measures work.

## dim_decline — 8 rows

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `decline_id` | smallint | Primary key |
| `decline_code` | varchar | e.g. `INSUFFICIENT_FUNDS`, `CARD_EXPIRED` |
| `decline_description` | varchar | Plain-English version for the report |
| `decline_category` | varchar | **`Soft`** — a retry can work (not enough money today). **`Hard`** — a retry can never work (the account is gone) |
| `is_retryable` | bool | True for Soft, false for Hard |

The Hard/Soft split is the hinge of finding 3: the system retries both, but only one kind can
ever succeed.

| Code | Category |
| ---- | -------- |
| `INSUFFICIENT_FUNDS` | Soft |
| `LIMIT_EXCEEDED` | Soft |
| `TEMPORARY_HOLD` | Soft |
| `PAYMENT_STOPPED` | Soft |
| `CARD_EXPIRED` | Hard |
| `ACCOUNT_CLOSED` | Hard |
| `CARD_LOST_STOLEN` | Hard |
| `INVALID_ACCOUNT` | Hard |

## dim_customer — 50,000 rows

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `customer_id` | int | Primary key |
| `join_date` | date | When they first took out a policy. 62% joined before the window opened — up to five years earlier |
| `state` | varchar | NSW, VIC, QLD, WA, SA, TAS |
| `acquisition_channel` | varchar | Broker, Direct online, Comparison site, Phone |
| `age_band` | varchar | 18-29, 30-44, 45-59, 60+ |

## dim_policy — 50,000 rows

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `policy_id` | int | Primary key |
| `customer_id` | int | → `dim_customer` |
| `product` | varchar | Motor, Home, Health |
| `billing_frequency` | varchar | Monthly (78%) or Annual (22%) |
| `premium_amount` | numeric | Amount per billing cycle. Annual payers pay 11× the monthly rate — the usual "one month free" discount |
| `start_date` | date | Same as the customer's join date in this simulation (one policy each) |

## dim_payment_method — 50,000 rows

| Column | Type | Meaning |
| ------ | ---- | ------- |
| `method_id` | int | Primary key |
| `customer_id` | int | → `dim_customer` |
| `method_type` | varchar | Direct debit (62%) or Card (38%) |
| `card_scheme` | varchar | Visa, Mastercard, Amex. Null for direct debits |
| `card_type` | varchar | Credit or Debit. Null for direct debits |
| `bank` | varchar | Issuing bank |
| `card_expiry_date` | date | When the stored card expires. **Null for direct debits** |

`card_expiry_date` is what finding 2 is built on: compare a payment's `date_id` against it.

---

## Notes on the simulation

| Setting | Value | Why |
| ------- | ----- | --- |
| Base failure rate | 4.2% per attempt | In line with published card and direct-debit dishonour rates |
| Soft share of dishonours | 72% | Most dishonours are "not enough money", not a dead account |
| Retry policy | next day, up to 3 attempts | The deliberately unhelpful policy the analysis argues against |
| Card updated before expiry | 58% | The other 42% drive the expiry cliff |
| Failure resolved before lapse | 84% | Someone calls in and fixes the details |
| Random seed | 20261003 | Fixed, so the dataset is identical on every run |

Every one of these lives at the top of [`etl/generate_data.py`](../etl/generate_data.py) and
can be changed in one place.
