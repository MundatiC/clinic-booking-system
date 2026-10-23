"""Pure slot arithmetic, including a DST zone (the clinic may not always be in Nairobi)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.slots import fits_in_windows, generate_slots, is_on_grid, local_day_bounds_utc

NBO = ZoneInfo("Africa/Nairobi")
LONDON = ZoneInfo("Europe/London")


def test_generate_slots_in_utc() -> None:
    slots = generate_slots(date(2030, 1, 8), [(time(8), time(9))], NBO, 30)
    assert slots == [
        (datetime(2030, 1, 8, 5, 0, tzinfo=UTC), datetime(2030, 1, 8, 5, 30, tzinfo=UTC)),
        (datetime(2030, 1, 8, 5, 30, tzinfo=UTC), datetime(2030, 1, 8, 6, 0, tzinfo=UTC)),
    ]


def test_day_bounds_nairobi() -> None:
    start, end = local_day_bounds_utc(date(2030, 1, 8), NBO)
    assert start == datetime(2030, 1, 7, 21, 0, tzinfo=UTC)
    assert end == datetime(2030, 1, 8, 21, 0, tzinfo=UTC)


def test_dst_spring_forward_skips_nonexistent_times() -> None:
    # 2030-03-31 in London: 01:00 GMT jumps to 02:00 BST.
    slots = generate_slots(date(2030, 3, 31), [(time(0), time(3))], LONDON, 30)
    local_starts = [s.astimezone(LONDON).strftime("%H:%M") for s, _ in slots]
    assert local_starts == ["00:00", "00:30", "02:00", "02:30"]
    assert all(e - s == timedelta(minutes=30) for s, e in slots)


def test_dst_day_is_23_hours() -> None:
    start, end = local_day_bounds_utc(date(2030, 3, 31), LONDON)
    assert end - start == timedelta(hours=23)


def test_grid_is_checked_in_local_time() -> None:
    # India (+05:30): 09:00 local is 03:30 UTC. The grid must follow local time.
    kolkata = ZoneInfo("Asia/Kolkata")
    assert is_on_grid(datetime(2030, 1, 8, 3, 30, tzinfo=UTC), kolkata, 30)
    assert not is_on_grid(datetime(2030, 1, 8, 3, 45, tzinfo=UTC), kolkata, 30)


def test_fits_in_windows_boundaries() -> None:
    windows = [(time(8), time(12)), (time(13), time(17))]

    def fits(hh: int, mm: int) -> bool:
        return fits_in_windows(datetime(2030, 1, 8, hh, mm, tzinfo=NBO), NBO, 30, windows)

    assert fits(8, 0) and fits(11, 30) and fits(16, 30)
    assert not fits(7, 30) and not fits(12, 0) and not fits(12, 30) and not fits(17, 0)
