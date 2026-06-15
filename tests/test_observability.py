from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from persistence.sqlite import SQLiteDatabase
from services.observability import (
    emit_event,
    get_gauges_snapshot,
    get_histograms_snapshot,
    get_metrics_snapshot,
    increment_counter,
    observe_histogram,
    render_prometheus,
    set_gauge,
)


class ObservabilityTests(unittest.TestCase):
    def test_sqlite_error_marks_database_unready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database = SQLiteDatabase(Path(tmp_dir) / "platform.db")

            with self.assertRaises(sqlite3.OperationalError):
                with database.transaction() as connection:
                    connection.execute("SELECT * FROM missing_table")

            self.assertEqual(get_gauges_snapshot()["database.sqlite.ready"], 0.0)

    def test_request_total_counts_started_request_once(self) -> None:
        before = get_metrics_snapshot().get("http.requests.total", 0)

        emit_event("http_request_started")
        emit_event("http_request_completed", status_code=200, duration_seconds=0.1)

        after = get_metrics_snapshot()["http.requests.total"]
        self.assertEqual(after - before, 1)

    def test_histogram_snapshot_uses_cumulative_buckets(self) -> None:
        metric_name = "test.observability.duration_seconds"

        observe_histogram(metric_name, 0.1, buckets=(0.1, 0.5, 1.0))
        observe_histogram(metric_name, 0.7, buckets=(0.1, 0.5, 1.0))

        histogram = get_histograms_snapshot()[metric_name]
        self.assertEqual(histogram["count"], 2)
        self.assertEqual(histogram["buckets"][0.1], 1)
        self.assertEqual(histogram["buckets"][0.5], 1)
        self.assertEqual(histogram["buckets"][1.0], 2)

    def test_prometheus_renderer_exports_counter_gauge_and_histogram(self) -> None:
        increment_counter("test.observability.requests")
        set_gauge("test.observability.ready", 1.0)
        observe_histogram(
            "test.observability.latency_seconds",
            0.2,
            buckets=(0.1, 0.5),
        )

        payload = render_prometheus()

        self.assertIn("ai_risk_test_observability_requests_total 1", payload)
        self.assertIn("ai_risk_test_observability_ready 1", payload)
        self.assertIn(
            'ai_risk_test_observability_latency_seconds_bucket{le="0.5"} 1',
            payload,
        )
        self.assertIn("ai_risk_test_observability_latency_seconds_count 1", payload)


if __name__ == "__main__":
    unittest.main()
