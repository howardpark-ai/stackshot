"""datewords.py — a date as a person reads it, and the one rule for saying its year.

A date of the current year is written without its year ("Tue Nov 10th 16:20"); a date of any other year says it ("Fri Mar 5th 2027 18:30"). The current year is the one it
is now in the instance's timezone ([instance] timezone, config.tz). A caller that has its own now (a board's clock, the day a question is put) passes it as `today`: a date, or a
datetime of the instance's timezone. The year of the date being written is its own (a datetime is read in the zone it is given in).

The board pages take their words from their string table (web/i18n.fmt_date) and ask other_year here. Stored values and machine fields stay ISO and do not come through this module.
Stdlib and core/config only."""
from __future__ import annotations

import datetime as dt
import time

from stackshot.core import config as _cfg


def other_year(d: dt.date, today: dt.date | None = None) -> bool:
    """Does a date (or a datetime) need its year said: is it in a year other than the current one?"""
    if today is None:
        today = dt.datetime.fromtimestamp(time.time(), _cfg.tz())
    return d.year != today.year


def ordinal(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def day_words(d: dt.date, today: dt.date | None = None) -> str:
    """"Tue Nov 10th"; "Fri Mar 5th 2027" for a day of another year."""
    year = f" {d.year}" if other_year(d, today) else ""
    return f"{d:%a %b} {d.day}{ordinal(d.day)}{year}"


def when_words(t: dt.date, today: dt.date | None = None, clock: bool = True) -> str:
    """day_words, followed by the clock of a datetime: "Tue Nov 10th 16:20", "Fri Mar 5th 2027 18:30". A date has no clock."""
    return day_words(t, today) + (f" {t:%H:%M}" if clock and isinstance(t, dt.datetime) else "")


def numeric_day(d: dt.date, today: dt.date | None = None) -> str:
    """The short numeric form of a day: "11-10"; "2027-03-05" for a day of another year."""
    return f"{d:%Y-%m-%d}" if other_year(d, today) else f"{d:%m-%d}"
