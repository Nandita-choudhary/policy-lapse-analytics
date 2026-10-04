"""
Predict which premium payments are about to fail.

The dashboard's first three pages explain what already went wrong. This script is what makes
page 4 possible: it learns from 24 months of payment history which policies are heading for a
failed payment, and writes a risk score for every active policy back into the database so the
report can show who to contact *before* the payment is attempted.

The model is a logistic regression. That is a deliberate choice over something fancier:

  - every coefficient can be read out loud ("an expired card multiplies the odds of failure by
    N"), which is what an insurer's own analysts would want and what an interviewer will ask for;
  - the relationships here are close to linear in the log-odds, so a heavier model would buy
    very little accuracy at the cost of all that explainability.

It is trained and tested with a TIME-BASED split — the last six months are held out — rather
than a random split. A random split would let the model learn from a policy's future to predict
its past, which flatters the score and would never hold up in production.

Run:  python model/predict_failures.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

HOLDOUT_MONTHS = 6  # the last six months are never used for training

NUMERIC_FEATURES = [
    "days_to_card_expiry",
    "prior_failed_attempts",
    "prior_payment_count",
    "months_since_join",
    "billing_day",
    "premium_amount",
]
CATEGORICAL_FEATURES = [
    "method_type",
    "product",
    "billing_frequency",
    "bank",
    "state",
    "age_band",
    "acquisition_channel",
]
FLAG_FEATURES = ["card_already_expired", "in_payday_window"]

# A card expiry date only exists for cards. Direct debits get this stand-in value, and the
# card_already_expired flag keeps the two groups distinguishable to the model.
NO_CARD_SENTINEL = 3650


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def load_tables() -> dict[str, pd.DataFrame]:
    """Read the star schema from PostgreSQL, falling back to the generated CSVs."""
    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    names = [
        "fact_payments", "fact_lapse_events", "dim_customer",
        "dim_policy", "dim_payment_method", "dim_decline", "dim_date",
    ]

    if url:
        try:
            from sqlalchemy import create_engine

            engine = create_engine(url)
            print("Reading from PostgreSQL…")
            return {n: pd.read_sql(f"SELECT * FROM {n}", engine) for n in names}
        except Exception as exc:  # noqa: BLE001 — any connection problem falls back
            print(f"Could not read from the database ({exc}). Using the local CSVs instead.")

    missing = [n for n in names if not (DATA_DIR / f"{n}.csv").exists()]
    if missing:
        sys.exit(f"No database and no CSVs ({', '.join(missing)}). Run etl/generate_data.py.")

    print("Reading from the local CSVs…")
    return {n: pd.read_csv(DATA_DIR / f"{n}.csv") for n in names}


# --------------------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------------------


def build_features(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per scheduled premium payment, described only by what was knowable beforehand.

    Retries are excluded: the question is whether the payment the insurer is about to attempt
    will go through, not whether a retry of an already-failed payment will.
    """
    pay = t["fact_payments"].copy()
    pay["date_id"] = pd.to_datetime(pay["date_id"])
    pay = pay[pay.attempt_number == 1].sort_values(["policy_id", "date_id"])

    # --- history, strictly before the payment in question (no peeking at the future) ---
    failed = (pay.payment_status == "Failed").astype(int)
    grp = pay.groupby("policy_id", sort=False)
    pay["prior_failed_attempts"] = grp["payment_status"].transform(
        lambda s: (s == "Failed").cumsum().shift(1).fillna(0)
    )
    pay["prior_payment_count"] = grp.cumcount()

    # --- the payment method, and how close it is to expiring ---
    methods = t["dim_payment_method"].copy()
    methods["card_expiry_date"] = pd.to_datetime(methods["card_expiry_date"])
    pay = pay.merge(
        methods[["method_id", "method_type", "bank", "card_expiry_date"]],
        on="method_id", how="left",
    )
    gap = (pay["card_expiry_date"] - pay["date_id"]).dt.days
    pay["days_to_card_expiry"] = gap.fillna(NO_CARD_SENTINEL)
    pay["card_already_expired"] = (gap < 0).fillna(False).astype(int)

    # --- the policy and the customer ---
    policies = t["dim_policy"][
        ["policy_id", "product", "billing_frequency", "premium_amount", "start_date"]
    ].copy()
    policies["start_date"] = pd.to_datetime(policies["start_date"])
    pay = pay.merge(policies, on="policy_id", how="left")

    customers = t["dim_customer"][
        ["customer_id", "join_date", "state", "age_band", "acquisition_channel"]
    ].copy()
    customers["join_date"] = pd.to_datetime(customers["join_date"])
    pay = pay.merge(customers, on="customer_id", how="left")

    pay["months_since_join"] = (
        (pay["date_id"] - pay["join_date"]).dt.days / 30.44
    ).clip(lower=0)

    # --- the calendar ---
    pay["billing_day"] = pay["date_id"].dt.day
    days_since_payday = np.where(
        pay["billing_day"] >= 15, pay["billing_day"] - 15, pay["billing_day"] - 1
    )
    pay["in_payday_window"] = (days_since_payday <= 2).astype(int)

    pay["target"] = failed.to_numpy()
    return pay


def make_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "prep",
                ColumnTransformer(
                    [
                        ("num", StandardScaler(), NUMERIC_FEATURES),
                        (
                            "cat",
                            OneHotEncoder(handle_unknown="ignore", drop="first"),
                            CATEGORICAL_FEATURES,
                        ),
                        ("flag", "passthrough", FLAG_FEATURES),
                    ]
                ),
            ),
            (
                "model",
                # The classes are left unweighted on purpose. Re-weighting them would improve
                # nothing about the ranking but would inflate every probability, and these
                # probabilities are used as probabilities: premium x risk only means
                # "premium at risk" if a score of 0.3 really is a 30% chance of failing.
                LogisticRegression(max_iter=1000, random_state=42),
            ),
        ]
    )


# --------------------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------------------


def train_and_test(feat: pd.DataFrame) -> tuple[Pipeline, pd.Timestamp]:
    cutoff = feat["date_id"].max() - pd.DateOffset(months=HOLDOUT_MONTHS)
    train = feat[feat.date_id <= cutoff]
    test = feat[feat.date_id > cutoff]

    print(f"\nTraining on payments up to {cutoff.date()}  ({len(train):,} rows)")
    print(f"Testing on the {HOLDOUT_MONTHS} months after    ({len(test):,} rows)")
    print(f"Failure rate — train {train.target.mean():.2%}, test {test.target.mean():.2%}")

    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + FLAG_FEATURES
    pipe = make_pipeline()
    pipe.fit(train[cols], train.target)

    probs = pipe.predict_proba(test[cols])[:, 1]
    print(f"\nHold-out ROC AUC            {roc_auc_score(test.target, probs):.3f}")
    print(f"Hold-out average precision  {average_precision_score(test.target, probs):.3f}"
          f"   (a coin flip would score {test.target.mean():.3f})")

    # What the business actually cares about: if we only contact the riskiest slice, how many
    # of the coming failures do we catch?
    order = np.argsort(-probs)
    y = test.target.to_numpy()[order]
    print("\n  Contact the riskiest…   catches this share of the failures")
    for pct in (0.05, 0.10, 0.20):
        n = int(len(y) * pct)
        print(f"    {pct:>4.0%} of policies          {y[:n].sum() / y.sum():>6.1%}")

    explain(pipe)
    return pipe, cutoff


def explain(pipe: Pipeline) -> None:
    """Print the model in plain English. These are the lines to be ready for in an interview."""
    prep = pipe.named_steps["prep"]
    names = list(prep.get_feature_names_out())
    coefs = pipe.named_steps["model"].coef_[0]
    order = np.argsort(-np.abs(coefs))[:8]

    print("\nWhat the model learned — the eight strongest signals:")
    for i in order:
        label = names[i].split("__", 1)[-1]
        direction = "raises" if coefs[i] > 0 else "lowers"
        print(f"    {label:<42} {direction} the odds of failure "
              f"(×{np.exp(coefs[i]):.2f} per unit)")


# --------------------------------------------------------------------------------------
# Scoring the live book
# --------------------------------------------------------------------------------------


def score_active_policies(t: dict[str, pd.DataFrame], feat: pd.DataFrame,
                          pipe: Pipeline) -> pd.DataFrame:
    """Score every policy that is still active, for its next scheduled premium payment."""
    ended = set(t["fact_lapse_events"].policy_id)
    latest = (
        feat[~feat.policy_id.isin(ended)]
        .sort_values("date_id")
        .groupby("policy_id", as_index=False)
        .last()
    )

    # Roll each policy's situation forward to its next billing date.
    step = np.where(latest.billing_frequency == "Monthly", 1, 12)
    latest["scored_for_date"] = [
        d + pd.DateOffset(months=int(m)) for d, m in zip(latest.date_id, step)
    ]
    latest["days_to_card_expiry"] = np.where(
        latest.days_to_card_expiry == NO_CARD_SENTINEL,
        NO_CARD_SENTINEL,
        latest.days_to_card_expiry - (latest.scored_for_date - latest.date_id).dt.days,
    )
    latest["card_already_expired"] = (
        (latest.days_to_card_expiry < 0) & (latest.method_type == "Card")
    ).astype(int)
    latest["prior_payment_count"] += 1
    latest["prior_failed_attempts"] += (latest.payment_status == "Failed").astype(int)
    latest["months_since_join"] = (
        (latest.scored_for_date - latest.join_date).dt.days / 30.44
    )

    cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES + FLAG_FEATURES
    latest["risk_score"] = pipe.predict_proba(latest[cols])[:, 1]

    out = latest[["policy_id", "customer_id", "scored_for_date", "risk_score",
                  "premium_amount"]].copy()
    # Bands are set against the book's own failure rate of roughly 5%: "Medium" is about
    # average, "Very high" is several times worse than average.
    out["risk_band"] = pd.cut(
        out.risk_score, [-0.01, 0.05, 0.15, 0.35, 1.01],
        labels=["Low", "Medium", "High", "Very high"],
    ).astype(str)
    out["premium_at_risk"] = (out.risk_score * out.premium_amount).round(2)
    out["scored_for_date"] = out.scored_for_date.dt.date

    print(f"\nScored {len(out):,} active policies for their next premium.")
    print(out.groupby("risk_band", observed=True)
          .agg(policies=("policy_id", "size"), premium_at_risk=("premium_at_risk", "sum"))
          .sort_values("premium_at_risk", ascending=False)
          .to_string(float_format=lambda v: f"${v:,.0f}"))
    return out


def save(scores: pd.DataFrame) -> None:
    path = DATA_DIR / "fact_risk_scores.csv"
    scores.to_csv(path, index=False)
    print(f"\nWrote {path.relative_to(ROOT)}")

    load_dotenv(ROOT / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        print("No DATABASE_URL set, so the scores stayed local. "
              "Add one to .env to push them into the database for Power BI.")
        return

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.begin() as conn:
            # Empty and refill rather than drop and recreate, so the table keeps the
            # definition, keys and index that sql/schema.sql gave it.
            conn.execute(text("TRUNCATE fact_risk_scores;"))
        scores.to_sql("fact_risk_scores", engine, if_exists="append", index=False)
        print("Wrote fact_risk_scores to the database — page 4 of the report reads this table.")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not write to the database: {exc}\n"
              f"Has sql/schema.sql been run against it yet?")


def main() -> None:
    tables = load_tables()
    print("Building features…")
    feat = build_features(tables)
    pipe, _ = train_and_test(feat)
    scores = score_active_policies(tables, feat, pipe)
    save(scores)


if __name__ == "__main__":
    main()
