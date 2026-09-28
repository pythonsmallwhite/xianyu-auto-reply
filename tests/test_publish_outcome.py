import importlib.util
import unittest
from pathlib import Path


module_path = Path(__file__).resolve().parents[1] / "common" / "utils" / "publish_outcome.py"
spec = importlib.util.spec_from_file_location("publish_outcome", module_path)
publish_outcome = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_outcome)
classify = publish_outcome.classify_publish_result


class PublishOutcomeTests(unittest.TestCase):
    def test_confirmed_success_needs_item_id(self):
        self.assertEqual(classify({"success": True, "item_id": "123"}, request_started=True), "success")
        self.assertEqual(classify({"success": True}, request_started=True), "unknown")

    def test_explicit_failure_without_item_id_can_be_retried(self):
        self.assertEqual(classify({"success": False, "message": "rejected"}, request_started=True), "failed")
        self.assertEqual(classify({"success": False, "item_id": "123"}, request_started=True), "unknown")

    def test_exception_after_request_is_unknown(self):
        self.assertEqual(classify(None, request_started=True, raised=True), "unknown")
        self.assertEqual(classify(None, request_started=False, raised=True), "failed")

    def test_platform_unknown_flag_is_preserved(self):
        self.assertEqual(
            classify({"success": False, "_request_status_unknown": True}, request_started=True),
            "unknown",
        )


if __name__ == "__main__":
    unittest.main()
