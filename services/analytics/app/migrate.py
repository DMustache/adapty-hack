"""Apply the additive temporal migration before analytics serves requests."""

import os
import time
from pathlib import Path

import psycopg


def main():
    migrations = [Path("/app/postgres/init/003-temporal-predictions.sql"),
                  Path("/app/postgres/init/005-experiment-lineage.sql"),
                  Path("/app/postgres/init/006-retention-candidates.sql")]
    for attempt in range(30):
        try:
            conn = psycopg.connect(os.environ["DATABASE_URL"])
            break
        except psycopg.OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    with conn:
        for path in migrations:
            conn.execute(path.read_text())


if __name__ == "__main__":
    main()
