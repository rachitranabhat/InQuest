"""Time handling. Internally everything is stored in UTC (ISO 8601 with 'Z').

Synthetic activity is generated in the display timezone (Ontario) because
detection features such as "night-time share" are about local hours. These
helpers convert between the two in one place.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

import config

try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo(config.DISPLAY_TZ)
except Exception:  # noqa: BLE001 - Windows without the tzdata package
    LOCAL_TZ = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_series_to_utc_iso(s: pd.Series) -> pd.Series:
    ts = pd.to_datetime(s)
    if LOCAL_TZ is not None:
        ts = ts.dt.tz_localize(config.DISPLAY_TZ, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    else:  # fixed EDT offset fallback for the simulated October period
        ts = (ts + pd.Timedelta(hours=4)).dt.tz_localize("UTC")
    return ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_iso_to_local(s: pd.Series) -> pd.Series:
    """UTC ISO strings -> naive local timestamps (for features, filters and display)."""
    ts = pd.to_datetime(s, utc=True)
    if LOCAL_TZ is not None:
        return ts.dt.tz_convert(config.DISPLAY_TZ).dt.tz_localize(None)
    return (ts - pd.Timedelta(hours=4)).dt.tz_localize(None)


def local_to_utc_iso(ts: datetime) -> str:
    return local_series_to_utc_iso(pd.Series([ts])).iloc[0]


def utc_iso_to_local_dt(value: str) -> datetime:
    return utc_iso_to_local(pd.Series([value])).iloc[0].to_pydatetime()
