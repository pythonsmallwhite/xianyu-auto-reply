import importlib.util
import sys
import unittest
from pathlib import Path


module_path = Path(__file__).resolve().parents[1] / "common" / "utils" / "inventory_policy.py"
spec = importlib.util.spec_from_file_location("inventory_policy", module_path)
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


class InventoryPolicyTests(unittest.TestCase):
    def test_three_orders_offline_only_two_unsold_managed_listings(self):
        states = {}
        for order_id in ("one", "two", "three"):
            states = policy.apply_order_event(states, order_id, "placed")
            states = policy.apply_order_event(states, order_id, "paid")
        self.assertEqual(policy.available_stock(3, states), 0)
        listings = [
            policy.LinkedListing(i, "managed", "sold") for i in (1, 2, 3)
        ] + [
            policy.LinkedListing(i, "managed", "active") for i in (4, 5)
        ]
        self.assertEqual(
            policy.reconcile_listings(3, states, listings),
            (
                policy.InventoryAction(4, "schedule_offline"),
                policy.InventoryAction(5, "schedule_offline"),
            ),
        )

    def test_one_cancellation_restores_only_inventory_offline_listings(self):
        states = {"one": "reserved", "two": "reserved", "three": "reserved"}
        states = policy.apply_order_event(states, "one", "cancelled")
        self.assertEqual(policy.available_stock(3, states), 1)
        listings = [
            policy.LinkedListing(1, "managed", "sold"),
            policy.LinkedListing(2, "managed", "offline", "manual"),
            policy.LinkedListing(3, "historical", "offline", "inventory"),
            policy.LinkedListing(4, "managed", "offline", "inventory"),
            policy.LinkedListing(5, "managed", "offline", "inventory"),
        ]
        self.assertEqual(
            policy.reconcile_listings(3, states, listings),
            (
                policy.InventoryAction(4, "schedule_relist"),
                policy.InventoryAction(5, "schedule_relist"),
            ),
        )

    def test_pending_actions_are_cancelled_when_stock_reverses(self):
        states = {"one": "reserved"}
        self.assertEqual(
            policy.reconcile_listings(
                1, states, [policy.LinkedListing(4, "managed", "offline", "inventory", "relist")]
            ),
            (policy.InventoryAction(4, "cancel_relist"),),
        )
        states = policy.apply_order_event(states, "one", "cancelled")
        self.assertEqual(
            policy.reconcile_listings(
                1, states, [policy.LinkedListing(5, "managed", "active", None, "offline")]
            ),
            (policy.InventoryAction(5, "cancel_offline"),),
        )

    def test_duplicate_and_late_order_events_do_not_double_reserve(self):
        states = policy.apply_order_event({}, "one", "placed")
        states = policy.apply_order_event(states, "one", "paid")
        states = policy.apply_order_event(states, "one", "placed")
        self.assertEqual(policy.available_stock(3, states), 2)
        states = policy.apply_order_event(states, "one", "cancelled")
        states = policy.apply_order_event(states, "one", "placed")
        self.assertEqual(policy.available_stock(3, states), 3)

    def test_status_mapping_keeps_refund_occupied_and_does_not_release_on_late_close(self):
        self.assertEqual(policy.inventory_event_for_status("待付款"), None)
        self.assertEqual(policy.inventory_event_for_status("pending_payment"), "placed")
        self.assertEqual(policy.inventory_event_for_status("pending_ship"), "paid")
        self.assertEqual(policy.inventory_event_for_status("refunded"), "refunded")
        self.assertEqual(
            policy.inventory_event_for_status("cancelled", "refunded"),
            "refunding",
        )


if __name__ == "__main__":
    unittest.main()
