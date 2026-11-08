"""Check provisioned segment SQL against the local synthetic offline snapshot."""

import csv
import gzip
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = json.loads((ROOT / "grafana/dashboards/behavior-segments.json").read_text())
DATA_DIR = Path(os.environ.get("OFFLINE_DATA_DIR", ROOT / "data"))
COMPOSE_DIR = Path(os.environ.get("SEGMENT_COMPOSE_DIR", ROOT))
VARIABLE = re.compile(r"\$\{([a-z_]+):sqlstring\}")
FIELDS = {
    "platform": "platform",
    "country": "country",
    "channel": "acquisition_channel",
    "goal": "onboarding_goal",
    "flow": "flow",
    "test": "ab_test",
}


def render(sql, values):
    def substitute(match):
        return "'" + values[match.group(1)].replace("'", "''") + "'"

    sql = VARIABLE.sub(substitute, sql)
    assert "${" not in sql
    return sql.replace(
        "$__timeFilter(u.install_at)",
        "u.install_at BETWEEN '2026-07-01T00:00:00Z' AND '2026-11-08T00:00:00Z'",
    )


def query(panel, values):
    sql = render(panel["targets"][0]["rawSql"], values)
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
         'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At -F "|"'],
        input=sql + ";", text=True, capture_output=True, cwd=COMPOSE_DIR, check=True,
    )
    return [row.split("|") for row in result.stdout.strip().splitlines()]


def selected(row, group, values):
    if not ("2026-07-01T00:00:00Z" <= row["install_at"] <= "2026-11-08T00:00:00Z"):
        return False
    for name, column in FIELDS.items():
        value = values[f"{group}_{name}"]
        if value == "__all__":
            continue
        if name == "test" and value == "__no_test__":
            if row[column]:
                return False
        elif row[column] != value:
            return False
    return True


def main():
    variables = DASHBOARD["templating"]["list"]
    assert len(variables) == 12
    defaults = {variable["name"]: variable["current"]["value"] for variable in variables}
    assert set(defaults) == {f"{group}_{name}" for group in "ab" for name in FIELDS}
    assert set(defaults.values()) == {"__all__"}
    test_queries = [v["query"] for v in variables if v["name"].endswith("_test")]
    assert len(test_queries) == 2 and all("__no_test__" in q for q in test_queries)
    panels = {panel["id"]: panel for panel in DASHBOARD["panels"]}
    assert set(panels) >= {1, 2, 3, 4, 10, 11}
    for panel in panels.values():
        sql = panel["targets"][0]["rawSql"]
        assert sql.startswith("SELECT ") and " LIKE " not in sql.upper()
        assert "user_id as" not in sql.lower()
        assert all(f"${{{group}_{name}:sqlstring}}" in sql for group in "ab" for name in FIELDS)

    with gzip.open(DATA_DIR / "users.csv.gz", "rt", newline="") as stream:
        users = list(csv.DictReader(stream))
    scenarios = {
        "all": {},
        "disjoint_platforms": {"a_platform": "iOS", "b_platform": "Android"},
        "no_test": {"a_test": "__no_test__", "b_platform": "Android"},
        "empty": {"a_country": "ZZ", "b_platform": "Android"},
        "overlap": {"a_platform": "iOS", "b_country": "US"},
    }
    for label, changes in scenarios.items():
        values = defaults | changes
        groups = {g.upper(): [u for u in users if selected(u, g, values)] for g in "ab"}
        summary = {row[0]: row for row in query(panels[10], values)}
        assert set(summary) == {"A", "B"}
        for group, members in groups.items():
            result = summary[group]
            assert int(result[1]) == len(members), (label, group, "size")
            assert int(result[4]) == sum(u["push_opt_in"] == "yes" for u in members)
            if members:
                assert all(result[i] for i in (2, 3, 5))
            else:
                assert all(not result[i] for i in (2, 3, 5))
        overlap = len({u["user_id"] for u in groups["A"]} & {u["user_id"] for u in groups["B"]})
        assert int(query(panels[11], values)[0][0]) == overlap, label
        for panel_id, size_column in ((1, 3), (2, 3), (3, 4), (4, 4)):
            rows = query(panels[panel_id], values)
            counts = Counter()
            for row in rows:
                group = row[0]
                counts[group] += int(row[2 if panel_id in (1, 2) else 3])
                assert int(row[size_column]) == len(groups[group]), (label, panel_id, group)
            assert all(counts[group] == len(members) for group, members in groups.items())
        print(f"PASS {label}: A={len(groups['A'])} B={len(groups['B'])} overlap={overlap}")


if __name__ == "__main__":
    main()
