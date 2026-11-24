"""The reported problem: an event stamped 15:04:05.100Z is read as 15:04:05.000100, so it loses
its milliseconds."""

from __future__ import annotations

from datetime import UTC, datetime

from risk.timestamps import parse_event_timestamp


def test_an_event_at_100_milliseconds_reads_as_100_milliseconds() -> None:
    parsed = parse_event_timestamp("2026-11-20T15:04:05.100Z")
    assert parsed == datetime(2026, 11, 20, 15, 4, 5, 100_000, tzinfo=UTC)
