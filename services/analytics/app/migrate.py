"""Apply the additive temporal migration before analytics serves requests."""

import os
import time
from pathlib import Path

import psycopg


def main():
    sql = Path("/app/postgres/init/003-temporal-predictions.sql").read_text()
    for attempt in range(30):
        try:
            conn = psycopg.connect(os.environ["DATABASE_URL"])
            break
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    with conn:
        conn.execute(sql)


if __name__ == "__main__":
    main()
