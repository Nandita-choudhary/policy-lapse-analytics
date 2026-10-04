-- ---------------------------------------------------------------------------------------
-- The Lapse That Isn't — star schema
--
-- One fact table of premium payment attempts sits at the centre. Everything else is a
-- dimension that explains an attempt: who paid, for what policy, with which payment method,
-- on what day, and — when it failed — why.
--
-- A second, much smaller fact table records the end of a policy, because an ending is a
-- different kind of event from a payment and has its own grain.
--
-- Run this once against the database before loading:  psql "$DATABASE_URL" -f sql/schema.sql
-- ---------------------------------------------------------------------------------------

DROP TABLE IF EXISTS fact_payments CASCADE;
DROP TABLE IF EXISTS fact_lapse_events CASCADE;
DROP TABLE IF EXISTS dim_payment_method CASCADE;
DROP TABLE IF EXISTS dim_policy CASCADE;
DROP TABLE IF EXISTS dim_customer CASCADE;
DROP TABLE IF EXISTS dim_decline CASCADE;
DROP TABLE IF EXISTS dim_date CASCADE;


-- --------------------------------------------------------------------- dimensions -------

-- One row per calendar day. is_payday_window is what makes finding 4 visible: it marks the
-- days just after the 1st and the 15th, when people have money in the account again.
CREATE TABLE dim_date (
    date_id            DATE PRIMARY KEY,
    year               SMALLINT     NOT NULL,
    quarter            CHAR(2)      NOT NULL,
    month_number       SMALLINT     NOT NULL,
    month_name         VARCHAR(12)  NOT NULL,
    year_month         CHAR(7)      NOT NULL,
    day_of_month       SMALLINT     NOT NULL,
    day_name           VARCHAR(10)  NOT NULL,
    is_weekend         BOOLEAN      NOT NULL,
    is_payday          BOOLEAN      NOT NULL,
    days_since_payday  SMALLINT     NOT NULL,
    is_payday_window   BOOLEAN      NOT NULL
);

-- One row per dishonour reason. decline_category is the hinge of the whole retry story:
-- a Soft dishonour can succeed on a later attempt, a Hard one never can.
CREATE TABLE dim_decline (
    decline_id           SMALLINT PRIMARY KEY,
    decline_code         VARCHAR(32)  NOT NULL UNIQUE,
    decline_description  VARCHAR(80)  NOT NULL,
    decline_category     VARCHAR(8)   NOT NULL CHECK (decline_category IN ('Hard', 'Soft')),
    is_retryable         BOOLEAN      NOT NULL
);

CREATE TABLE dim_customer (
    customer_id          INTEGER PRIMARY KEY,
    join_date            DATE         NOT NULL,
    state                VARCHAR(4)   NOT NULL,
    acquisition_channel  VARCHAR(20)  NOT NULL,
    age_band             VARCHAR(8)   NOT NULL
);

CREATE TABLE dim_policy (
    policy_id          INTEGER PRIMARY KEY,
    customer_id        INTEGER      NOT NULL REFERENCES dim_customer (customer_id),
    product            VARCHAR(10)  NOT NULL,
    billing_frequency  VARCHAR(8)   NOT NULL,
    premium_amount     NUMERIC(10,2) NOT NULL,
    start_date         DATE         NOT NULL
);

-- card_expiry_date is null for direct debits. It is what finding 2 is built on.
CREATE TABLE dim_payment_method (
    method_id         INTEGER PRIMARY KEY,
    customer_id       INTEGER      NOT NULL REFERENCES dim_customer (customer_id),
    method_type       VARCHAR(14)  NOT NULL,
    card_scheme       VARCHAR(12),
    card_type         VARCHAR(8),
    bank              VARCHAR(12)  NOT NULL,
    card_expiry_date  DATE
);


-- -------------------------------------------------------------------------- facts -------

-- Grain: one premium payment ATTEMPT. A failed payment that is retried twice produces three
-- rows, which is the point — the retries are where the money leaks.
CREATE TABLE fact_payments (
    payment_id      BIGINT PRIMARY KEY,
    policy_id       INTEGER       NOT NULL REFERENCES dim_policy (policy_id),
    customer_id     INTEGER       NOT NULL REFERENCES dim_customer (customer_id),
    method_id       INTEGER       NOT NULL REFERENCES dim_payment_method (method_id),
    date_id         DATE          NOT NULL REFERENCES dim_date (date_id),
    amount          NUMERIC(10,2) NOT NULL,
    fee             NUMERIC(6,2)  NOT NULL,
    attempt_number  SMALLINT      NOT NULL,
    payment_status  VARCHAR(8)    NOT NULL CHECK (payment_status IN ('Success', 'Failed')),
    decline_id      SMALLINT      REFERENCES dim_decline (decline_id)
);

-- Grain: one ended policy. end_type is the headline split — did the customer decide to go,
-- or did the payments simply stop working?
CREATE TABLE fact_lapse_events (
    policy_id         INTEGER PRIMARY KEY REFERENCES dim_policy (policy_id),
    customer_id       INTEGER      NOT NULL REFERENCES dim_customer (customer_id),
    end_date          DATE         NOT NULL REFERENCES dim_date (date_id),
    end_type          VARCHAR(10)  NOT NULL CHECK (end_type IN ('Cancelled', 'Lapsed')),
    end_reason        VARCHAR(40)  NOT NULL,
    final_decline_id  SMALLINT     REFERENCES dim_decline (decline_id)
);


-- Grain: one active policy, scored for its next scheduled premium. Rebuilt from scratch every
-- time model/predict_failures.py runs. This is the only table in the schema that is a model
-- output rather than a record of something that happened.
CREATE TABLE fact_risk_scores (
    policy_id        INTEGER PRIMARY KEY REFERENCES dim_policy (policy_id),
    customer_id      INTEGER       NOT NULL REFERENCES dim_customer (customer_id),
    scored_for_date  DATE          NOT NULL,
    risk_score       NUMERIC(6,5)  NOT NULL,
    premium_amount   NUMERIC(10,2) NOT NULL,
    risk_band        VARCHAR(10)   NOT NULL,
    premium_at_risk  NUMERIC(10,2) NOT NULL
);


-- ---------------------------------------------------------------------- indexes ---------
-- The fact table is scanned by date, by policy and by dishonour reason on every page of the
-- report, so each gets an index.

CREATE INDEX idx_payments_date     ON fact_payments (date_id);
CREATE INDEX idx_payments_policy   ON fact_payments (policy_id);
CREATE INDEX idx_payments_decline  ON fact_payments (decline_id);
CREATE INDEX idx_payments_status   ON fact_payments (payment_status, attempt_number);
CREATE INDEX idx_lapse_date        ON fact_lapse_events (end_date);
CREATE INDEX idx_lapse_type        ON fact_lapse_events (end_type);
CREATE INDEX idx_risk_band         ON fact_risk_scores (risk_band);
