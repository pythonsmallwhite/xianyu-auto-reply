import unittest
import importlib.util
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / "common/utils/token_retry_policy.py"
SPEC = importlib.util.spec_from_file_location("token_retry_policy", POLICY_PATH)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
COOKIE_REFRESH_DEFER_STATUSES = POLICY.COOKIE_REFRESH_DEFER_STATUSES
token_failure_retry_delay = POLICY.token_failure_retry_delay


class TokenRetryPolicyTests(unittest.TestCase):
    def test_slider_failures_wait_for_the_cookie_refresh_cycle(self):
        for status in ("failed_captcha", "failed_captcha_exception", "failed_captcha_max_retries"):
            with self.subTest(status=status):
                self.assertEqual(token_failure_retry_delay(status, 180), 180)
                self.assertIn(status, COOKIE_REFRESH_DEFER_STATUSES)

    def test_other_retry_intervals_keep_their_existing_policy(self):
        self.assertEqual(token_failure_retry_delay("skipped_cooldown", 180), 300)
        self.assertEqual(token_failure_retry_delay("failed_api", 180), 5)


if __name__ == "__main__":
    unittest.main()
