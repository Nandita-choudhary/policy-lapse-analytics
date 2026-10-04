"""
Load the generated CSVs into PostgreSQL (Supabase).

Before running:

  1. Create a project at supabase.com and copy its Session pooler connection string
     (Connect → method "Session pooler" → URI). The direct address is IPv6-only.
  2. Put it in a .env file in the repo root — this file is gitignored, never commit it:

         DATABASE_URL=postgresql://postgres.PROJECTREF:YOURPASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres

  3. Create the tables:   psql "$DATABASE_URL" -f sql/schema.sql
  4. Then:                python etl/load_to_postgres.py

Rows are loaded with COPY rather than INSERT — 770,000 payment rows go in seconds instead of
many minutes. Dimensions load before facts so the foreign keys always have something to point
at, and each table is emptied first so the script can be run again safely.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Dimensions first — the fact tables' foreign keys depend on them.
LOAD_ORDER = [
    "dim_date",
    "dim_decline",
    "dim_customer",
    "dim_policy",
    "dim_payment_method",
    "fact_payments",
    "fact_lapse_events",
]


def main() -> None:
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("No DATABASE_URL found. Put it in a .env file in the repo root.")

    missing = [t for t in LOAD_ORDER if not (DATA_DIR / f"{t}.csv").exists()]
    if missing:
        sys.exit(f"Missing CSVs: {', '.join(missing)}. Run etl/generate_data.py first.")

    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            # Clear in reverse order so nothing is referenced while it is being removed.
            print("Clearing existing rows…")
            for table in reversed(LOAD_ORDER):
                cur.execute(f"TRUNCATE {table} CASCADE;")

            for table in LOAD_ORDER:
                path = DATA_DIR / f"{table}.csv"
                print(f"Loading {table:<20}", end=" ", flush=True)
                with path.open("r", encoding="utf-8") as fh:
                    # Name the columns from the CSV's own header. Without a column list COPY
                    # fills columns by position, so a column added to the generator in a
                    # different place from sql/schema.sql could load into the wrong field.
                    columns = fh.readline().strip()
                    fh.seek(0)
                    cur.copy_expert(
                        f"COPY {table} ({columns}) FROM STDIN WITH CSV HEADER NULL ''", fh
                    )
                cur.execute(f"SELECT count(*) FROM {table};")
                print(f"{cur.fetchone()[0]:>10,} rows")

            # Fresh statistics so the query planner makes sensible choices for Power BI.
            print("Analysing tables…")
            cur.execute("ANALYZE;")

        conn.commit()

    print("\nDone. Point Power BI Desktop at this database to build the report.")


if __name__ == "__main__":
    main()
