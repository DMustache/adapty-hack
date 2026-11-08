"""Point-in-time usage (engagement) features for churn snapshots.

Only events with occurred_at STRICTLY BEFORE as_of_at count, so a snapshot never sees its own instant or the future.

Features (per snapshot):
  sessions_7d, sessions_14d, sessions_30d  sessions in [as_of_at - N days, as_of_at)
  days_since_last_session                  as_of_at - last session before as_of_at (null if none yet)
  days_since_last_activity                 as_of_at - last event of ANY kind before as_of_at
  sessions_trend_7d_delta                  sessions in the last 7 days minus sessions in the 7 days before that
  sessions_trend_7d_ratio                  (last 7 days + 1) / (previous 7 days + 1)
  session_rate_7d_vs_30d                   (sessions_7d + 1) / (sessions_30d * 7/30 + 1): > 1 = using the app more
                                           than its 30-day average, < 1 = fading
A session is an event whose name is in SESSION_EVENTS.

Missing history: a subscriber whose usage is not tracked gets null features, never zeros, so "not tracked" is never
mistaken for "inactive". By default a subscriber counts as tracked at as_of_at once they have at least one event (of
any kind) before as_of_at: deciding it from all their events would leak the future (an event logged after as_of_at
would turn nulls into zeros). Pass `tracked_since` (subscriber -> UTC time tracking started, e.g. the SDK rollout)
when you know it; then a tracked subscriber with no events yet gets zero sessions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SESSION_EVENTS = {"session_start", "app_open", "[Amplitude] Start Session"}
USAGE_FEATURES = ["sessions_7d", "sessions_14d", "sessions_30d", "days_since_last_session",
                  "days_since_last_activity", "sessions_trend_7d_delta", "sessions_trend_7d_ratio",
                  "session_rate_7d_vs_30d"]
_NS_DAY = 86_400 * 10**9


def _ns(s) -> np.ndarray:
    """UTC nanoseconds since epoch, whatever resolution pandas stored (s, ms, us or ns)."""
    return pd.to_datetime(pd.Series(s), utc=True).dt.as_unit("ns").astype("int64").to_numpy()


def usage_features(snaps: pd.DataFrame, events: pd.DataFrame, user_col: str = "subscriber_id",
                   session_events: set[str] = SESSION_EVENTS,
                   tracked_since: dict[str, pd.Timestamp] | None = None) -> pd.DataFrame:
    """Return USAGE_FEATURES aligned with snaps.index.

    snaps: needs user_id and as_of_at (UTC). events: needs `user_col`, event_name, occurred_at (UTC).
    tracked_since: optional subscriber -> time usage tracking started (see module docstring).
    """
    out = pd.DataFrame(np.nan, index=snaps.index, columns=USAGE_FEATURES)
    if snaps.empty:
        return out
    events = events[events[user_col].notna() & events["occurred_at"].notna()]
    all_times = {u: np.sort(_ns(g["occurred_at"])) for u, g in events.groupby(user_col)}
    sess = events[events["event_name"].isin(session_events)]
    sess_times = {u: np.sort(_ns(g["occurred_at"])) for u, g in sess.groupby(user_col)}
    since = {u: _ns([t])[0] for u, t in (tracked_since or {}).items() if pd.notna(t)}
    empty = np.empty(0, dtype=np.int64)
    t_all = _ns(snaps["as_of_at"])
    users = snaps["user_id"].to_numpy()
    for u in np.unique(users):
        if u not in all_times and u not in since:
            continue
        rows = np.where(users == u)[0]
        t = t_all[rows]
        anyev = all_times.get(u, empty)
        n_any = np.searchsorted(anyev, t, side="left")             # events of any kind strictly before as_of_at
        tracked = n_any > 0
        if u in since:
            tracked |= since[u] < t
        if not tracked.any():
            continue
        ev = sess_times.get(u, empty)
        now = np.searchsorted(ev, t, side="left")                  # sessions strictly before as_of_at
        d7 = np.searchsorted(ev, t - 7 * _NS_DAY, side="left")
        d14 = np.searchsorted(ev, t - 14 * _NS_DAY, side="left")
        d30 = np.searchsorted(ev, t - 30 * _NS_DAY, side="left")
        last7, prev7, last14, last30 = now - d7, d7 - d14, now - d14, now - d30
        last_sess = ev[np.maximum(now - 1, 0)] if len(ev) else np.zeros(len(t), dtype=np.int64)
        last_any = anyev[np.maximum(n_any - 1, 0)] if len(anyev) else np.zeros(len(t), dtype=np.int64)
        vals = {
            "sessions_7d": last7, "sessions_14d": last14, "sessions_30d": last30,
            "days_since_last_session": np.where(now > 0, (t - last_sess) / _NS_DAY, np.nan),
            "days_since_last_activity": np.where(n_any > 0, (t - last_any) / _NS_DAY, np.nan),
            "sessions_trend_7d_delta": last7 - prev7,
            "sessions_trend_7d_ratio": (last7 + 1) / (prev7 + 1),
            "session_rate_7d_vs_30d": (last7 + 1) / (last30 * 7 / 30 + 1),
        }
        idx = out.index[rows[tracked]]
        for name, v in vals.items():
            out.loc[idx, name] = np.asarray(v, dtype=float)[tracked]
    return out
