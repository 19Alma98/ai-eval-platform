from datetime import UTC, datetime, timedelta

from aiobs_server.application.project_overview import bucket_size_for_range


def test_bucket_size_short_range_is_5_minutes():
    until = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    since = until - timedelta(minutes=15)
    assert bucket_size_for_range(since, until) == timedelta(minutes=5)
    since_1h = until - timedelta(hours=1)
    assert bucket_size_for_range(since_1h, until) == timedelta(minutes=5)


def test_bucket_size_6h_is_15_minutes():
    until = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    since = until - timedelta(hours=6)
    assert bucket_size_for_range(since, until) == timedelta(minutes=15)


def test_bucket_size_24h_is_1_hour():
    until = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    since = until - timedelta(hours=24)
    assert bucket_size_for_range(since, until) == timedelta(hours=1)


def test_bucket_size_7d_is_6_hours():
    until = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    since = until - timedelta(days=7)
    assert bucket_size_for_range(since, until) == timedelta(hours=6)
