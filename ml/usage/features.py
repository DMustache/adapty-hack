"""Point-in-time usage features for churn snapshots. Only events with occurred_at STRICTLY BEFORE as_of_at count.

Features (per snapshot):
  sessions_7d, sessions_30d        sessions in [as_of_at - N days, as_of_at)
  days_since_last_session          as_of_at - last session before as_of_at (null if none yet)
  sessions_trend_7d_delta          sessions in the last 7 days minus sessions in the 7 days before that
  sessions_trend_7d_ratio          (last 7 days + 1) / (previous 7 days + 1)
A session is an event whose name is in SESSION_EVENTS. Subscribers with no usage data at all (not tracked) get
null features rather than zeros, so "not tracked" is never mistaken for "inactive".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SESSION_EVENTS = {"session_start", "app_open", "[Amplitude] Start Session"}
USAGE_FEATURES = ["sessions_7d", "sessions_30d", "days_since_last_session", "sessions_trend_7d_delta",
                  "sessions_trend_7d_ratio"]
_NS_DAY = 86_400 * 10**9


def _ns(s: pd.Series) -> np.ndarray:
    """UTC nanoseconds since epoch, whatever resolution pandas stored (s, ms, us or ns)."""
    return pd.to_datetime(s, utc=True).dt.as_unit("ns").astype("int64").to_numpy()


def usage_features(snaps: pd.DataFrame, events: pd.DataFrame, user_col: str = "subscriber_id",
                   session_events: set[str] = SESSION_EVENTS, tracked_users: set[str] | None = None) -> pd.DataFrame:
    """Return USAGE_FEATURES aligned with snaps.index.

    snaps: needs user_id and as_of_at (UTC). events: needs `user_col`, event_name, occurred_at (UTC).
    tracked_users: subscribers whose usage is tracked (default: everyone with at least one event).
    """
    out = pd.DataFrame(np.nan, index=snaps.index, columns=USAGE_FEATURES)
    if snaps.empty:
        return out
    tracked = set(events[user_col].unique()) if tracked_users is None else set(tracked_users)
    sess = events[events["event_name"].isin(session_events)]
    times = {u: np.sort(_ns(g["occurred_at"])) for u, g in sess.groupby(user_col)}
    t_all = _ns(snaps["as_of_at"])
    users = snaps["user_id"].to_numpy()
    for u in np.unique(users):
        if u not in tracked:
            continue
        rows = np.where(users == u)[0]
        t = t_all[rows]
        ev = times.get(u, np.empty(0, dtype=np.int64))
        now = np.searchsorted(ev, t, side="left")               # events strictly before as_of_at
        d7 = np.searchsorted(ev, t - 7 * _NS_DAY, side="left")
        d14 = np.searchsorted(ev, t - 14 * _NS_DAY, side="left")
        d30 = np.searchsorted(ev, t - 30 * _NS_DAY, side="left")
        last7, prev7 = now - d7, d7 - d14
        idx = out.index[rows]
        out.loc[idx, "sessions_7d"] = last7
        out.loc[idx, "sessions_30d"] = now - d30
        last = ev[np.maximum(now - 1, 0)] if len(ev) else np.zeros(len(t), dtype=np.int64)
        out.loc[idx, "days_since_last_session"] = np.where(now > 0, (t - last) / _NS_DAY, np.nan)
        out.loc[idx, "sessions_trend_7d_delta"] = last7 - prev7
        out.loc[idx, "sessions_trend_7d_ratio"] = (last7 + 1) / (prev7 + 1)
    return out
