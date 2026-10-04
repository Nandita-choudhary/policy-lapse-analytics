"""
Generate the simulated insurer's premium-payment history.

THE DATA IS SIMULATED. Real premium and payment records are confidential, so this script
builds a dataset whose rates are calibrated to published industry research and whose shape
matches what a real policy-administration system produces.

It writes seven CSV files into data/ — a star schema:

    fact_payments        one premium payment attempt
    fact_lapse_events    one ended policy
    dim_customer         one policyholder
    dim_policy           one policy
    dim_payment_method   one stored card or direct debit
    dim_decline          one dishonour reason
    dim_date             one calendar day

Four patterns are deliberately built in, because the dashboard's job is to find them:

    1. INVOLUNTARY LAPSE   a large share of ended policies were never cancelled by anyone.
                           The payments failed until the policy died.
    2. THE EXPIRY CLIFF    card-paid premiums fail sharply once the stored card expires,
                           because nobody warns the customer beforehand.
    3. RETRYING THE DEAD   hard dishonours (closed account, dead card) can never succeed,
                           yet the system retries them anyway and pays a fee each time.
    4. THE PAYDAY WINDOW   soft dishonours (not enough money) succeed far more often when the
                           retry lands just after the 1st or 15th. The system retries the next
                           day instead, so whether a retry lands in that window is pure luck.

Run:  python etl/generate_data.py
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# Settings — everything tunable lives here
# --------------------------------------------------------------------------------------

SEED = 20261003  # fixed so the dataset is identical every run

SIM_START = date(2024, 10, 1)
SIM_END = date(2026, 9, 30)

N_CUSTOMERS = 50_000

# Products: share of policies, and the monthly premium range
PRODUCTS = {
    "Motor": {"share": 0.45, "premium": (65, 190)},
    "Home": {"share": 0.30, "premium": (80, 240)},
    "Health": {"share": 0.25, "premium": (95, 310)},
}

STATES = {"NSW": 0.31, "VIC": 0.26, "QLD": 0.20, "WA": 0.11, "SA": 0.07, "TAS": 0.05}
CHANNELS = {"Broker": 0.34, "Direct online": 0.30, "Comparison site": 0.22, "Phone": 0.14}
BANKS = {"CBA": 0.25, "Westpac": 0.21, "NAB": 0.19, "ANZ": 0.18, "Bendigo": 0.09, "Other": 0.08}

P_MONTHLY_BILLING = 0.78  # the rest pay annually
P_CARD = 0.38  # the rest pay by direct debit

# Payment outcomes
BASE_FAILURE_RATE = 0.042  # chance a healthy payment attempt fails
NEW_CUSTOMER_PENALTY = 1.6  # first 3 months fail more often (details still settling)
P_SOFT_GIVEN_FAILURE = 0.72  # most dishonours are "not enough money", not a dead account

# Not every policyholder is equally reliable. Most people's premiums go through every time;
# a minority run their accounts close to empty and dishonour again and again. This spread is
# what makes a policyholder's own payment history worth anything as a predictor — without it,
# every past failure would be pure bad luck and no model could do better than the base rate.
RELIABILITY_SPREAD = 0.95  # lognormal sigma; higher = more variation between customers
MAX_FAILURE_RATE = 0.55  # even the least reliable customer usually pays

# Retries — the system's current (deliberately unhelpful) policy
MAX_ATTEMPTS = 3  # original attempt + 2 retries
RETRY_GAP_DAYS = 1  # it always retries the very next day

# Pattern 4: a soft dishonour retried inside the payday window succeeds far more often
PAYDAY_DAYS = (1, 15)
PAYDAY_WINDOW_DAYS = 2  # "just after payday" = 0-2 days after the 1st or 15th
P_RETRY_SUCCESS_IN_WINDOW = 0.62
P_RETRY_SUCCESS_OUTSIDE = 0.24

# Pattern 2: cards expire, and not everyone updates them in time
CARD_LIFETIME_MONTHS = (6, 48)  # how long after policy start the stored card expires
P_CARD_UPDATED_IN_TIME = 0.58

# After every attempt has failed, someone may still fix it before the policy dies
P_CUSTOMER_RESOLVES = 0.84

# Voluntary cancellation: the customer actually chooses to leave
MONTHLY_CANCEL_HAZARD = 0.0055

# Fees — what each attempt costs the insurer
FEE_SUCCESS = 0.28
FEE_DISHONOUR = 2.95

DECLINE_REASONS = [
    # (code, description, category, share of that category)
    ("INSUFFICIENT_FUNDS", "Not enough money in the account", "Soft", 0.70),
    ("LIMIT_EXCEEDED", "Payment exceeds the account limit", "Soft", 0.16),
    ("TEMPORARY_HOLD", "Bank placed a temporary hold", "Soft", 0.09),
    ("PAYMENT_STOPPED", "Customer stopped the payment", "Soft", 0.05),
    ("CARD_EXPIRED", "Stored card has expired", "Hard", 0.46),
    ("ACCOUNT_CLOSED", "Bank account has been closed", "Hard", 0.31),
    ("CARD_LOST_STOLEN", "Card reported lost or stolen", "Hard", 0.14),
    ("INVALID_ACCOUNT", "Account details are not valid", "Hard", 0.09),
]

OUT_DIR = Path(__file__).resolve().parent.parent / "data"

rng = np.random.default_rng(SEED)


# --------------------------------------------------------------------------------------
# Small date helpers
# --------------------------------------------------------------------------------------


def add_months(d: date, months: int) -> date:
    """Move a date forward by whole months, clamping to the end of a short month."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_since_payday(d: date) -> int:
    """How many days have passed since the most recent payday (0 if today is one)."""
    if d.day >= 15:
        return d.day - 15
    if d.day >= 1:
        return d.day - 1
    return 0


def in_payday_window(d: date) -> bool:
    return days_since_payday(d) <= PAYDAY_WINDOW_DAYS


def pick(options: dict[str, float], size: int) -> np.ndarray:
    """Draw `size` values from a {label: probability} map."""
    labels = list(options.keys())
    weights = np.array(list(options.values()), dtype=float)
    return rng.choice(labels, size=size, p=weights / weights.sum())


# --------------------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------------------


def build_dim_date() -> pd.DataFrame:
    """One row per calendar day, with the payday flags the retry analysis needs."""
    days = pd.date_range(SIM_START, SIM_END + timedelta(days=45), freq="D")
    df = pd.DataFrame({"date_id": days.date})
    df["year"] = days.year
    df["quarter"] = "Q" + days.quarter.astype(str)
    df["month_number"] = days.month
    df["month_name"] = days.strftime("%B")
    df["year_month"] = days.strftime("%Y-%m")
    df["day_of_month"] = days.day
    df["day_name"] = days.strftime("%A")
    df["is_weekend"] = days.dayofweek >= 5
    df["is_payday"] = df["day_of_month"].isin(PAYDAY_DAYS)
    df["days_since_payday"] = [days_since_payday(d) for d in df["date_id"]]
    df["is_payday_window"] = df["days_since_payday"] <= PAYDAY_WINDOW_DAYS
    return df


def build_dim_decline() -> pd.DataFrame:
    """One row per dishonour reason. The Hard/Soft split drives the whole retry story."""
    rows = [
        {
            "decline_id": i + 1,
            "decline_code": code,
            "decline_description": desc,
            "decline_category": category,
            # A hard dishonour can never succeed on a retry. A soft one can.
            "is_retryable": category == "Soft",
        }
        for i, (code, desc, category, _) in enumerate(DECLINE_REASONS)
    ]
    return pd.DataFrame(rows)


def build_customers() -> pd.DataFrame:
    """One row per policyholder.

    Most of the book already existed before the window opens — they joined anywhere from a
    month to five years earlier. That matters for two reasons: their billing days are spread
    right across the month (so a retry landing near payday is genuinely a coincidence), and
    their tenure is real, so they are not all treated as brand-new customers.
    """
    n = N_CUSTOMERS
    window_days = (SIM_END - SIM_START).days

    existing = rng.random(n) < 0.62
    back = rng.integers(30, 5 * 365, n)  # joined this long before the window
    forward = (rng.random(n) ** 0.85 * (window_days - 60)).astype(int)

    join_dates = [
        SIM_START - timedelta(days=int(back[i]))
        if existing[i]
        else SIM_START + timedelta(days=int(forward[i]))
        for i in range(n)
    ]

    return pd.DataFrame(
        {
            "customer_id": np.arange(1, n + 1),
            "join_date": join_dates,
            "state": pick(STATES, n),
            "acquisition_channel": pick(CHANNELS, n),
            "age_band": pick(
                {"18-29": 0.18, "30-44": 0.34, "45-59": 0.28, "60+": 0.20}, n
            ),
            # How reliably this person's premiums go through, as a multiplier on the base
            # failure rate. Centred on 1.0 with a long right tail. It is NOT exported to the
            # warehouse — a real insurer cannot see it either, which is the whole reason the
            # model has to infer it from payment history.
            "_reliability": rng.lognormal(
                -(RELIABILITY_SPREAD**2) / 2, RELIABILITY_SPREAD, n
            ),
        }
    )


def build_policies(customers: pd.DataFrame) -> pd.DataFrame:
    """One policy per customer, with its product, premium and billing frequency."""
    n = len(customers)
    products = pick({k: v["share"] for k, v in PRODUCTS.items()}, n)

    premiums = np.empty(n)
    for name, cfg in PRODUCTS.items():
        mask = products == name
        low, high = cfg["premium"]
        premiums[mask] = np.round(rng.uniform(low, high, mask.sum()), 2)

    monthly = rng.random(n) < P_MONTHLY_BILLING

    return pd.DataFrame(
        {
            "policy_id": np.arange(1, n + 1),
            "customer_id": customers["customer_id"].to_numpy(),
            "product": products,
            "billing_frequency": np.where(monthly, "Monthly", "Annual"),
            # Annual payers pay 11x the monthly rate — the usual "one month free" discount
            "premium_amount": np.where(monthly, premiums, np.round(premiums * 11, 2)),
            "start_date": customers["join_date"].to_numpy(),
            # Carried through the simulation, then dropped — see build_customers().
            "_reliability": customers["_reliability"].to_numpy(),
        }
    )


def build_payment_methods(customers: pd.DataFrame, policies: pd.DataFrame) -> pd.DataFrame:
    """One stored payment method per customer. Cards carry the expiry date behind pattern 2."""
    n = len(customers)
    is_card = rng.random(n) < P_CARD
    low, high = CARD_LIFETIME_MONTHS
    # Expiry dates are spread from the start of the window out to four years later, so roughly
    # half of the stored cards reach their expiry date at some point during the 24 months.
    lifetimes = rng.integers(low, high + 1, n)

    expiry = [
        add_months(SIM_START, int(lifetimes[i])) if is_card[i] else None for i in range(n)
    ]

    return pd.DataFrame(
        {
            "method_id": np.arange(1, n + 1),
            "customer_id": customers["customer_id"].to_numpy(),
            "method_type": np.where(is_card, "Card", "Direct debit"),
            "card_scheme": np.where(
                is_card, pick({"Visa": 0.52, "Mastercard": 0.41, "Amex": 0.07}, n), None
            ),
            "card_type": np.where(is_card, pick({"Credit": 0.56, "Debit": 0.44}, n), None),
            "bank": pick(BANKS, n),
            "card_expiry_date": expiry,
        }
    )


# --------------------------------------------------------------------------------------
# The simulation itself
# --------------------------------------------------------------------------------------


def simulate_payments(
    policies: pd.DataFrame, methods: pd.DataFrame, declines: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk every policy month by month and record each premium payment attempt.

    Returns (fact_payments, fact_lapse_events).
    """
    soft = declines[declines.decline_category == "Soft"]
    hard = declines[declines.decline_category == "Hard"]
    soft_ids = soft.decline_id.to_numpy()
    hard_ids = hard.decline_id.to_numpy()
    soft_w = np.array([r[3] for r in DECLINE_REASONS if r[2] == "Soft"])
    hard_w = np.array([r[3] for r in DECLINE_REASONS if r[2] == "Hard"])
    soft_w = soft_w / soft_w.sum()
    hard_w = hard_w / hard_w.sum()
    card_expired_id = int(
        declines.loc[declines.decline_code == "CARD_EXPIRED", "decline_id"].iloc[0]
    )

    payments: list[tuple] = []
    lapses: list[tuple] = []
    payment_id = 0

    pol = policies.to_dict("records")
    meth = {m["customer_id"]: m for m in methods.to_dict("records")}

    for p in pol:
        policy_id = p["policy_id"]
        customer_id = p["customer_id"]
        monthly = p["billing_frequency"] == "Monthly"
        amount = float(p["premium_amount"])
        method = meth[customer_id]
        method_id = method["method_id"]
        is_card = method["method_type"] == "Card"
        card_expiry = method["card_expiry_date"]
        card_updated = is_card and rng.random() < P_CARD_UPDATED_IN_TIME

        start = p["start_date"]
        step = 1 if monthly else 12

        # Long-standing customers joined before the window opened. Jump straight to their
        # first billing date inside it — history before the window is not ours to record.
        due = start
        if due < SIM_START:
            months_gap = (SIM_START.year - start.year) * 12 + (SIM_START.month - start.month)
            due = add_months(start, (months_gap // step) * step)
            while due < SIM_START:
                due = add_months(due, step)

        ended = False

        while due <= SIM_END and not ended:
            # --- is the stored card dead by now? (pattern 2) -----------------------
            card_dead = (
                is_card
                and card_expiry is not None
                and due > card_expiry
                and not card_updated
            )

            # --- does the first attempt fail? --------------------------------------
            tenure_months = (due.year - p["start_date"].year) * 12 + (
                due.month - p["start_date"].month
            )
            fail_rate = min(
                BASE_FAILURE_RATE
                * (NEW_CUSTOMER_PENALTY if tenure_months < 3 else 1.0)
                * p["_reliability"],
                MAX_FAILURE_RATE,
            )

            if card_dead:
                failed, decline_id = True, card_expired_id
            elif rng.random() < fail_rate:
                failed = True
                if rng.random() < P_SOFT_GIVEN_FAILURE:
                    decline_id = int(rng.choice(soft_ids, p=soft_w))
                else:
                    decline_id = int(rng.choice(hard_ids, p=hard_w))
            else:
                failed, decline_id = False, None

            if not failed:
                payment_id += 1
                payments.append(
                    (payment_id, policy_id, customer_id, method_id, due, amount,
                     FEE_SUCCESS, 1, "Success", None)
                )
            else:
                retryable = bool(declines.loc[declines.decline_id == decline_id,
                                              "is_retryable"].iloc[0])
                attempt_date = due
                resolved = False

                for attempt in range(1, MAX_ATTEMPTS + 1):
                    if attempt > 1:
                        attempt_date = attempt_date + timedelta(days=RETRY_GAP_DAYS)

                        # Pattern 3: a hard dishonour can never succeed, but it is retried
                        # anyway — every one of these rows is a wasted fee.
                        # Pattern 4: a soft dishonour depends on where the retry lands.
                        if retryable:
                            p_success = (
                                P_RETRY_SUCCESS_IN_WINDOW
                                if in_payday_window(attempt_date)
                                else P_RETRY_SUCCESS_OUTSIDE
                            )
                            if rng.random() < p_success:
                                payment_id += 1
                                payments.append(
                                    (payment_id, policy_id, customer_id, method_id,
                                     attempt_date, amount, FEE_SUCCESS, attempt,
                                     "Success", None)
                                )
                                resolved = True
                                break

                    payment_id += 1
                    payments.append(
                        (payment_id, policy_id, customer_id, method_id, attempt_date,
                         amount, FEE_DISHONOUR, attempt, "Failed", decline_id)
                    )

                if not resolved:
                    # Every attempt failed. Someone may still call in and fix the details.
                    if rng.random() < P_CUSTOMER_RESOLVES:
                        pass  # sorted out off-system; the policy carries on
                    else:
                        # Pattern 1: nobody decided anything. The policy just died.
                        lapses.append(
                            (policy_id, customer_id, method_id, attempt_date, "Lapsed",
                             "Payment failure", decline_id)
                        )
                        ended = True
                        break

            # --- the customer may also simply choose to leave -----------------------
            cancel_chance = MONTHLY_CANCEL_HAZARD * (1 if monthly else 12)
            if rng.random() < cancel_chance:
                lapses.append((policy_id, customer_id, method_id, due, "Cancelled",
                               "Customer request", None))
                ended = True
                break

            due = add_months(due, step)

    fact_payments = pd.DataFrame(
        payments,
        columns=["payment_id", "policy_id", "customer_id", "method_id", "date_id",
                 "amount", "fee", "attempt_number", "payment_status", "decline_id"],
    )
    # method_id is the payment method on file when the policy ended. Without it nothing links an
    # ended policy to how it was paid, and the report could not compare cards with direct debits.
    fact_lapse_events = pd.DataFrame(
        lapses,
        columns=["policy_id", "customer_id", "method_id", "end_date", "end_type",
                 "end_reason", "final_decline_id"],
    )
    return fact_payments, fact_lapse_events


# --------------------------------------------------------------------------------------
# Reporting — prove the four patterns actually landed
# --------------------------------------------------------------------------------------


def summarise(payments, lapses, methods, declines, policies) -> None:
    print("\n" + "=" * 70)
    print("GENERATED DATA — CHECK")
    print("=" * 70)
    print(f"Policyholders          {len(policies):,}")
    print(f"Payment attempts       {len(payments):,}")
    print(f"Ended policies         {len(lapses):,}  ({len(lapses)/len(policies):.1%} of book)")

    first = payments[payments.attempt_number == 1]
    print(f"First-attempt failures {(first.payment_status == 'Failed').mean():.1%}")
    print(f"Dishonour fees paid    ${payments.loc[payments.payment_status == 'Failed', 'fee'].sum():,.0f}")

    print("\nPATTERN 1 — the lapse that isn't")
    mix = lapses.end_type.value_counts(normalize=True)
    for k, v in mix.items():
        print(f"  {k:<12} {v:>6.1%}")

    print("\nPATTERN 2 — the expiry cliff  (first attempts only)")
    merged = first.merge(methods[["method_id", "card_expiry_date", "method_type"]],
                         on="method_id", how="left")
    cards = merged[(merged.method_type == "Card") & merged.card_expiry_date.notna()].copy()
    cards["after_expiry"] = cards.date_id > cards.card_expiry_date
    for label, grp in cards.groupby("after_expiry"):
        when = "after card expiry " if label else "before card expiry"
        print(f"  {when}  failure rate {(grp.payment_status == 'Failed').mean():>6.1%}"
              f"   ({len(grp):,} attempts)")

    print("\nPATTERN 3 — retrying the dead")
    f = payments[payments.payment_status == "Failed"].merge(
        declines[["decline_id", "decline_category"]], on="decline_id", how="left")
    wasted = f[(f.decline_category == "Hard") & (f.attempt_number > 1)]
    print(f"  retries of hard dishonours   {len(wasted):,} attempts")
    print(f"  fees burned on them          ${wasted.fee.sum():,.0f} over 24 months"
          f"  (${wasted.fee.sum()/2:,.0f}/yr)")
    print(f"  of those retries that worked 0 — a hard dishonour never can")

    print("\nPATTERN 4 — the payday window  (soft dishonours only)")
    # Walk each retry back to the dishonour that caused it, so hard dishonours — which can
    # never succeed — do not drag the success rates down.
    retries = payments[payments.attempt_number > 1].copy()
    cause = (payments[payments.payment_status == "Failed"]
             .merge(declines[["decline_id", "decline_category"]], on="decline_id")
             .groupby("policy_id").decline_category.last())
    retries["cause"] = retries.policy_id.map(cause)
    soft_retries = retries[retries.cause == "Soft"].copy()
    soft_retries["in_window"] = [in_payday_window(d) for d in soft_retries.date_id]
    for label, grp in soft_retries.groupby("in_window"):
        where = "inside payday window " if label else "outside payday window"
        print(f"  {where}  success rate {(grp.payment_status == 'Success').mean():>6.1%}"
              f"   ({len(grp):,} retries)")
    print("=" * 70 + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "sample").mkdir(exist_ok=True)

    print("Building dimensions…")
    dim_date = build_dim_date()
    dim_decline = build_dim_decline()
    dim_customer = build_customers()
    dim_policy = build_policies(dim_customer)
    dim_payment_method = build_payment_methods(dim_customer, dim_policy)

    print(f"Simulating {N_CUSTOMERS:,} policies over 24 months… (this takes a minute)")
    fact_payments, fact_lapse_events = simulate_payments(
        dim_policy, dim_payment_method, dim_decline
    )

    # The hidden reliability trait never leaves the simulation — a real insurer would not have
    # it in its warehouse, so neither does this one. The model must infer it from history.
    dim_customer = dim_customer.drop(columns=["_reliability"])
    dim_policy = dim_policy.drop(columns=["_reliability"])

    tables = {
        "dim_date": dim_date,
        "dim_decline": dim_decline,
        "dim_customer": dim_customer,
        "dim_policy": dim_policy,
        "dim_payment_method": dim_payment_method,
        "fact_payments": fact_payments,
        "fact_lapse_events": fact_lapse_events,
    }

    print("Writing CSVs…")
    for name, df in tables.items():
        df.to_csv(OUT_DIR / f"{name}.csv", index=False)
        # A small sample of each table is committed so the repo shows its shape
        df.head(200).to_csv(OUT_DIR / "sample" / f"{name}_sample.csv", index=False)
        print(f"  {name:<20} {len(df):>10,} rows")

    summarise(fact_payments, fact_lapse_events, dim_payment_method, dim_decline, dim_policy)


if __name__ == "__main__":
    main()
