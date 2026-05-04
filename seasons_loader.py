"""Load pool seasons from seasons.txt.

Format per line: year open_month open_day close_month close_day rate
"""

import os
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Season:
    year: int
    open: date
    close: date
    rate: float


_DEF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seasons.txt")


def load(path: str | None = None) -> list[Season]:
    p = path or _DEF_PATH
    seasons: list[Season] = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            seasons.append(Season(
                year=int(parts[0]),
                open=date(int(parts[0]), int(parts[1]), int(parts[2])),
                close=date(int(parts[0]), int(parts[3]), int(parts[4])),
                rate=float(parts[5]),
            ))
    return seasons


# module-level singleton, lazily loaded
_cache: list[Season] | None = None


def _get() -> list[Season]:
    global _cache
    if _cache is None:
        _cache = load()
    return _cache


def get_rate(date_str: str) -> float:
    """Given a YYYY-MM-DD string, return the seasonal rate for that year."""
    return next(s.rate for s in _get() if s.year == int(date_str[:4]))


def get_rate_for_date(date_str: str) -> float:
    """Alias of get_rate for backward compatibility."""
    return get_rate(date_str)


def get_current_season(today: date | None = None) -> Season | None:
    """Return the season containing *today*, or None."""
    if today is None:
        import datetime
        import pytz
        central = pytz.timezone("US/Central")
        today = datetime.datetime.now(central).date()
    return next((s for s in _get() if s.open <= today <= s.close), None)


def get_season_by_year(year: int) -> Season | None:
    """Return the season for a specific year."""
    return next((s for s in _get() if s.year == year), None)
