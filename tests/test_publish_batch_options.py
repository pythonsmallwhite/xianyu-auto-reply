"""Request schema and migration contracts without importing a live application."""
import ast
from pathlib import Path
from typing import List, Literal
import unittest

from pydantic import BaseModel, Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]


class PublishBatchOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ast.parse((ROOT / "backend-web/app/api/routes/product_publish.py").read_text(encoding="utf-8-sig"))
        definitions = [n for n in source.body if isinstance(n, ast.ClassDef) and n.name in {
            "BatchPublishRequest", "BatchRetryRequest"}]
        namespace = dict(BaseModel=BaseModel, Field=Field, model_validator=model_validator, List=List, Literal=Literal)
        exec(compile(ast.Module(body=definitions, type_ignores=[]), "real_publish_schemas", "exec"), namespace)
        cls.Create, cls.Retry = namespace["BatchPublishRequest"], namespace["BatchRetryRequest"]
        for schema in (cls.Create, cls.Retry):
            schema.model_rebuild(_types_namespace=namespace)

    def test_explicit_window_and_material_default(self):
        for hours in (0, 1, 3, 5, 12, 24):
            with self.subTest(hours=hours):
                request = self.Create(account_ids=["acct"], material_ids=[11], window_hours=hours)
                self.assertEqual((request.window_hours, request.address_mode), (hours, "material"))
                self.assertEqual(self.Retry(target_ids=[1], window_hours=hours).window_hours, hours)
        with self.assertRaises(ValidationError):
            self.Create(account_ids=["acct"], material_ids=[11])
        with self.assertRaises(ValidationError):
            self.Retry(target_ids=[1])

    def test_immediate_account_count_uses_deduplicated_selection(self):
        self.Create(account_ids=["acct", "acct"], material_ids=[11, 12], window_hours=0)
        with self.assertRaises(ValidationError):
            self.Create(account_ids=["acct", "acct2"], material_ids=[11], window_hours=0)
        self.Create(account_ids=["acct", "acct2"], material_ids=[11], window_hours=1)

    def test_invalid_modes_and_windows_rejected(self):
        for mode in (None, "", "pool"):
            with self.assertRaises(ValidationError):
                self.Create(account_ids=["acct"], material_ids=[11], window_hours=1, address_mode=mode)
        for hours in (-1, 2, 6, 48, None):
            with self.assertRaises(ValidationError):
                self.Create(account_ids=["acct"], material_ids=[11], window_hours=hours)
        self.assertEqual(self.Create(account_ids=["acct"], material_ids=[11], window_hours=0, address_mode="random").address_mode, "random")

    def test_legacy_migration_keeps_null_strategy(self):
        tree = ast.parse((ROOT / "common/db/init_database.py").read_text(encoding="utf-8-sig"))
        migrations = next(ast.literal_eval(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COLUMN_MIGRATIONS" for t in node.targets)
            and isinstance(node.value, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "xy_publish_batches" for k in node.value.keys))
        field = next(row for row in migrations["xy_publish_batches"] if row[0] == "address_mode")
        self.assertEqual(field[1], "VARCHAR(20) DEFAULT NULL")


if __name__ == "__main__":
    unittest.main()
