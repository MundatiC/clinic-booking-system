"""Pure slot arithmetic (no I/O). All wall-clock work happens in clinic-local time.

Grid: a slot may start only at a multiple of `slot_minutes` after local
midnight (00:00, 00:30, 01:00, ... for 30-minute slots).
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Window = tuple[time, time]
Slot = tuple[datetime, datetime]  # (start, end), timezone-aware UTC


def local_day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """UTC instants for [local midnight of `day`, local midnight of the next day)."""
    start = datetime.combine(day, time(0), tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _exists_locally(naive: datetime, tz: ZoneInfo) -> bool:
    """False for wall-clock times skipped by a DST jump (they don't exist)."""
    aware = naive.replace(tzinfo=tz)
    return aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive


def generate_slots(
    day: date, windows: Iterable[Window], tz: ZoneInfo, slot_minutes: int
) -> list[Slot]:
    """Every grid-aligned slot that fits entirely inside one of the windows."""
    step = timedelta(minutes=slot_minutes)
    slots: list[Slot] = []
    for win_start, win_end in sorted(windows):
        first = -(-_minutes(win_start) // slot_minutes) * slot_minutes  # ceil to grid
        cursor = datetime.combine(day, time(0)) + timedelta(minutes=first)
        limit = datetime.combine(day, win_end)
        while cursor + step <= limit:
            if _exists_locally(cursor, tz):
                start = cursor.replace(tzinfo=tz).astimezone(UTC)
                slots.append((start, (cursor + step).replace(tzinfo=tz).astimezone(UTC)))
            cursor += step
    return slots


def is_on_grid(start: datetime, tz: ZoneInfo, slot_minutes: int) -> bool:
    local = start.astimezone(tz)
    return (
        local.second == 0
        and local.microsecond == 0
        and (local.hour * 60 + local.minute) % slot_minutes == 0
    )


def fits_in_windows(
    start: datetime, tz: ZoneInfo, slot_minutes: int, windows: Iterable[Window]
) -> bool:
    """True if [start, start + slot) lies entirely inside a single window (local time)."""
    local = start.astimezone(tz).replace(tzinfo=None)
    end = local + timedelta(minutes=slot_minutes)
    for win_start, win_end in windows:
        if datetime.combine(local.date(), win_start) <= local and end <= datetime.combine(
            local.date(), win_end
        ):
            return True
    return False
