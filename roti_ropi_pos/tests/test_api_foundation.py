from decimal import Decimal

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import api_endpoint, success
from roti_ropi_pos.mobile_pos.validation import decimal_string, reject_fields, require_json_object


class TestAPIFoundation(IntegrationTestCase):
	def test_success_envelope_has_stable_metadata(self):
		result = success({"value": "ok"}, request_id="REQ-1", server_time="2026-07-23T14:30:00+07:00")
		self.assertEqual(result["ok"], True)
		self.assertEqual(result["data"], {"value": "ok"})
		self.assertEqual(result["meta"]["api_version"], "v1")
		self.assertEqual(result["meta"]["request_id"], "REQ-1")
		self.assertEqual(result["meta"]["server_time"], "2026-07-23T14:30:00+07:00")
		self.assertEqual(result["meta"]["replayed"], False)

	def test_success_sets_http_status_code(self):
		success({"value": "ok"}, http_status=201)
		self.assertEqual(frappe.response["http_status_code"], 201)

	def test_success_generates_request_id_and_server_time_when_omitted(self):
		result = success({"value": "ok"})
		self.assertTrue(result["meta"]["request_id"])
		self.assertTrue(result["meta"]["server_time"])

	def test_decimal_string_rejects_float(self):
		with self.assertRaisesRegex(MobilePOSAPIError, "decimal string"):
			decimal_string(1.5, field="amount")
		self.assertEqual(decimal_string("1.50", field="amount"), Decimal("1.50"))

	def test_decimal_string_rejects_invalid_syntax(self):
		with self.assertRaisesRegex(MobilePOSAPIError, "decimal string"):
			decimal_string("abc", field="amount")

	def test_reject_fields_blocks_server_owned_values(self):
		with self.assertRaisesRegex(MobilePOSAPIError, "company"):
			reject_fields({"company": "Roti Ropi"}, {"company", "owner"})

	def test_reject_fields_passes_when_no_blocked_field_present(self):
		reject_fields({"customer": "Ayu"}, {"company", "owner"})

	def test_require_json_object_rejects_non_dict(self):
		with self.assertRaisesRegex(MobilePOSAPIError, "JSON object"):
			require_json_object([1, 2, 3], field="payload")

	def test_require_json_object_returns_dict(self):
		self.assertEqual(require_json_object({"a": 1}, field="payload"), {"a": 1})

	def test_mobile_pos_api_error_carries_status_and_details(self):
		error = MobilePOSAPIError("NO_OPEN_SESSION", "missing", status=422, details={"pos_profile": "X"})
		self.assertEqual(error.code, "NO_OPEN_SESSION")
		self.assertEqual(error.status, 422)
		self.assertEqual(error.details, {"pos_profile": "X"})
		self.assertEqual(error.retryable, False)

	def test_api_endpoint_maps_known_error_to_envelope(self):
		@api_endpoint
		def raise_known():
			raise MobilePOSAPIError(
				"INVALID_REQUEST", "bad", status=400, details={"field": "x", "reason": "y"}
			)

		frappe.response["http_status_code"] = None
		result = raise_known()
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"], {"field": "x", "reason": "y"})
		self.assertEqual(result["error"]["retryable"], False)
		self.assertEqual(result["meta"]["api_version"], "v1")
		self.assertEqual(frappe.response["http_status_code"], 400)

	def test_api_endpoint_returns_success_envelope(self):
		@api_endpoint
		def handler():
			return success({"value": "ok"})

		frappe.response["http_status_code"] = None
		result = handler()
		self.assertEqual(result["ok"], True)
		self.assertEqual(result["data"], {"value": "ok"})
		self.assertEqual(result["meta"]["api_version"], "v1")

	def test_api_endpoint_re_raises_unknown_exception(self):
		@api_endpoint
		def raise_unknown():
			raise RuntimeError("boom")

		with self.assertRaises(RuntimeError):
			raise_unknown()
