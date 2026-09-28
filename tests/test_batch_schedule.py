import random
import unittest
from datetime import datetime, timedelta, timezone

import importlib.util
from pathlib import Path

module_path = Path(__file__).resolve().parents[1] / "common" / "utils" / "batch_schedule.py"
spec = importlib.util.spec_from_file_location("batch_schedule", module_path)
batch_schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch_schedule)
next_allowed_start = batch_schedule.next_allowed_start
plan_product_offsets = batch_schedule.plan_product_offsets


class ProductScheduleTests(unittest.TestCase):
    def test_five_accounts_one_hour_have_six_minute_gap(self):
        offsets = plan_product_offsets(5, 1, random.Random(42))
        self.assertEqual(len(offsets), 5)
        self.assertGreaterEqual(offsets[0], 0)
        self.assertLessEqual(offsets[-1], 3600 - 360)
        for earlier, later in zip(offsets, offsets[1:]):
            self.assertGreaterEqual(later - earlier + 1e-9, 360)

    def test_all_windows_and_group_sizes_stay_within_window(self):
        for hours in (1, 3, 5, 12, 24):
            for count in (1, 2, 5, 10):
                for seed in range(20):
                    offsets = plan_product_offsets(count, hours, random.Random(seed))
                    self.assertEqual(len(offsets), count)
                    self.assertGreaterEqual(offsets[0], 0)
                    self.assertLessEqual(offsets[-1], hours * 3600)
                    if count > 1:
                        gap = hours * 3600 / (2 * count)
                        for earlier, later in zip(offsets, offsets[1:]):
                            self.assertGreaterEqual(later - earlier + 1e-9, gap)

    def test_delayed_request_keeps_actual_start_gap(self):
        start = datetime(2026, 9, 28, tzinfo=timezone.utc)
        planned = start + timedelta(minutes=10)
        previous_actual = start + timedelta(minutes=9)
        ready = next_allowed_start(
            planned, previous_actual, timedelta(minutes=6), start + timedelta(hours=1)
        )
        self.assertEqual(ready, start + timedelta(minutes=15))

    def test_overdue_request_is_not_started(self):
        start = datetime(2026, 9, 28, tzinfo=timezone.utc)
        self.assertIsNone(
            next_allowed_start(
                start + timedelta(minutes=50),
                start + timedelta(minutes=58),
                timedelta(minutes=6),
                start + timedelta(hours=1),
            )
        )

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_product_offsets(0, 1)
        with self.assertRaises(ValueError):
            plan_product_offsets(5, 2)


if __name__ == "__main__":
    unittest.main()
