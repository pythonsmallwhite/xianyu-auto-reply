import unittest
from uuid import UUID

from pydantic import ValidationError

from common.schemas.physical_logistics import (
    PhysicalLogisticsIdempotencyRecord,
    PhysicalLogisticsOrderContext,
    PhysicalLogisticsSubmissionRequest,
    PhysicalLogisticsSubmissionResult,
)
import importlib.util
from pathlib import Path

_service_path = Path(__file__).resolve().parents[1] / "common" / "services" / "physical_logistics_contract.py"
_service_spec = importlib.util.spec_from_file_location("physical_logistics_contract_under_test", _service_path)
_service_module = importlib.util.module_from_spec(_service_spec)
_service_spec.loader.exec_module(_service_module)
PhysicalLogisticsContractError = _service_module.PhysicalLogisticsContractError
request_fingerprint = _service_module.request_fingerprint
validate_submission_request = _service_module.validate_submission_request
validate_submission_result = _service_module.validate_submission_result


KEY = UUID("00000000-0000-4000-8000-000000000001")


def request(**overrides):
    values = {
        "owner_id": 7,
        "order_no": "order-1",
        "carrier_name": "carrier supplied by a future adapter",
        "tracking_number": "tracking-1",
        "idempotency_key": KEY,
        "fulfillment_kind": "physical_logistics",
    }
    values.update(overrides)
    return PhysicalLogisticsSubmissionRequest(**values)


def order(**overrides):
    values = {
        "owner_id": 7,
        "order_no": "order-1",
        "status": "pending_ship",
    }
    values.update(overrides)
    return PhysicalLogisticsOrderContext(**values)


class PhysicalLogisticsSchemaTests(unittest.TestCase):
    def test_request_requires_physical_kind_and_idempotency_key(self):
        valid = request()
        self.assertEqual(valid.fulfillment_kind, "physical_logistics")
        for mutation in (
            {"fulfillment_kind": "card_only"},
            {"idempotency_key": ""},
            {"tracking_number": "  "},
        ):
            with self.assertRaises((ValidationError, ValueError)):
                request(**mutation)

    def test_submitted_result_requires_opaque_protocol_receipt(self):
        values = {
            "owner_id": 7,
            "order_no": "order-1",
            "idempotency_key": KEY,
            "fulfillment_kind": "physical_logistics",
            "outcome": "submitted",
            "carrier_name": "carrier",
            "tracking_number": "tracking",
            "platform_reference": "opaque-reference",
            "protocol_receipt": "opaque-receipt",
        }
        self.assertEqual(PhysicalLogisticsSubmissionResult(**values).outcome, "submitted")
        for missing in ("platform_reference", "protocol_receipt", "tracking_number"):
            with self.assertRaises(ValidationError):
                PhysicalLogisticsSubmissionResult(
                    **{key: value for key, value in values.items() if key != missing}
                )

    def test_card_and_no_logistics_results_cannot_be_submitted(self):
        for kind in ("card_only", "no_logistics"):
            with self.assertRaises(ValidationError):
                PhysicalLogisticsSubmissionResult(
                    owner_id=7,
                    order_no="order-1",
                    idempotency_key=KEY,
                    fulfillment_kind=kind,
                    outcome="submitted",
                    carrier_name="carrier",
                    tracking_number="tracking",
                    platform_reference="reference",
                    protocol_receipt="receipt",
                )


class PhysicalLogisticsValidationTests(unittest.TestCase):
    def test_owner_and_status_are_fail_closed(self):
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_request(request(owner_id=8), order())
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_request(request(), order(status="shipped"))
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_request(request(), order(card_only_delivered=True))
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_request(request(), order(delivery_method="no_logistics"))

    def test_same_idempotency_key_must_keep_the_exact_request(self):
        original = request()
        record = PhysicalLogisticsIdempotencyRecord(
            owner_id=original.owner_id,
            order_no=original.order_no,
            idempotency_key=original.idempotency_key,
            request_fingerprint=request_fingerprint(original),
        )
        validate_submission_request(original, order(), record)
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_request(
                request(tracking_number="tracking-2"), order(), record
            )

    def test_result_must_match_owner_order_and_idempotency(self):
        submitted = PhysicalLogisticsSubmissionResult(
            owner_id=7,
            order_no="order-1",
            idempotency_key=KEY,
            fulfillment_kind="physical_logistics",
            outcome="submitted",
            carrier_name="carrier supplied by a future adapter",
            tracking_number="tracking-1",
            platform_reference="opaque-reference",
            protocol_receipt="opaque-receipt",
        )
        validate_submission_result(request(), submitted)
        with self.assertRaises(PhysicalLogisticsContractError):
            validate_submission_result(request(owner_id=8), submitted)

    def test_unknown_and_failed_are_explicit_and_never_success(self):
        for outcome, field in (("unknown", "error_message"), ("failed", "error_code")):
            result = PhysicalLogisticsSubmissionResult(
                owner_id=7,
                order_no="order-1",
                idempotency_key=KEY,
                fulfillment_kind="physical_logistics",
                outcome=outcome,
                **{field: "protocol unavailable"},
            )
            self.assertNotEqual(result.outcome, "submitted")


if __name__ == "__main__":
    unittest.main()
