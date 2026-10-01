"""Offline contracts for managed seller edits and guarded polish results."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from pydantic import ValidationError

from common.schemas.item import BatchSellerItemEditRequest


ROOT = Path(__file__).resolve().parents[1]


class ManagedItemEditContractTests(unittest.TestCase):
    def test_request_requires_explicit_window_and_rejects_empty_images(self):
        with self.assertRaises(ValidationError):
            BatchSellerItemEditRequest(
                item_ids=["item-1"],
                window_hours=2,
                patch={"title": "new"},
            )
        with self.assertRaises(ValidationError):
            BatchSellerItemEditRequest(
                item_ids=["item-1"],
                window_hours=1,
                patch={"images": []},
            )

    def test_payload_omits_images_for_retention_and_state_has_unknown_guard(self):
        request = BatchSellerItemEditRequest(
            item_ids=["item-1"],
            window_hours=3,
            patch={"title": "new"},
        )
        self.assertNotIn("images", request.patch.model_dump(exclude_unset=True))
        source = (ROOT / "common/services/managed_item_edit_service.py").read_text(encoding="utf-8")
        self.assertIn('if patch.get("images") == []', source)
        self.assertIn('row.status != "failed"', source)
        self.assertIn('"unknown"', source)
        self.assertIn("origin_predicates", source)

    def test_final_edit_call_is_guarded_and_unknown_is_explicit(self):
        source = (ROOT / "backend-web/app/services/xianyu_item_edit_service.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        edit_calls = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id == "_call_seller_api"]
        self.assertTrue(any(any(keyword.arg == "request_guard" for keyword in call.keywords) for call in edit_calls))
        self.assertIn('"status": "unknown"', source)


if __name__ == "__main__":
    unittest.main()
