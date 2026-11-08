"""Apply the additive temporal migration before analytics serves requests."""

import os
from pathlib import Path

import psycopg


def main():
    sql = Path("/app/postgres/init/003-temporal-predictions.sql").read_text()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(sql)


if __name__ == "__main__":
    main()
