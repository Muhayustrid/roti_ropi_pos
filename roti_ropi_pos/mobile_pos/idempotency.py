from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import now_datetime

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import success

_log = logging.getLogger(__name__)

DOCTYPE = "Mobile POS Request"

# Operation -> set of business DocTypes that may be referenced by a completed
# request for that operation. Verified by ``verify_business_reference`` before a
# request is marked terminal.
OPERATION_REFERENCE_DOCTYPES: dict[str, set[str]] = {
	"v1.sessions.open": {"POS Opening Entry"},
	"v1.sales.submit": {"POS Invoice"},
	"v1.sales.create_return": {"POS Invoice"},
	"v1.closing.submit": {"POS Closing Entry"},
}

RETENTION_DAYS = 90
CLEANUP_BATCH_SIZE = 100

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class MutationResult:
	data: dict
	reference_doctype: str
	reference_name: str
	http_status: int = 201


def normalize_for_hash(value):
	if isinstance(value, Decimal):
		return format(value.normalize(), "f")
	if isinstance(value, dict):
		return {key: normalize_for_hash(value[key]) for key in sorted(value)}
	if isinstance(value, list):
		return [normalize_for_hash(item) for item in value]
	return value


def canonical_hash(operation_id: str, validated_payload: dict) -> str:
	normalized = normalize_for_hash(validated_payload)
	body = json.dumps(
		{"operation_id": operation_id, "payload": normalized},
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=True,
	)
	return hashlib.sha256(body.encode()).hexdigest()


def _scope_key(idempotency_key: str, operation_id: str) -> str:
	user = frappe.session.user
	body = f"{user}\n{operation_id}\n{idempotency_key}".encode()
	return hashlib.sha256(body).hexdigest()


def require_idempotency_key() -> str:
	key = frappe.get_request_header("X-Idempotency-Key")
	if not key or not _UUID.match(key):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"X-Idempotency-Key must be a lowercase UUID.",
			details={"field": "X-Idempotency-Key", "reason": "Expected a lowercase UUID."},
		)
	return key


def _get_existing_request(scope_key: str):
	name = frappe.db.get_value(DOCTYPE, {"scope_key": scope_key})
	if not name:
		return None
	return frappe.get_doc(DOCTYPE, name)


def _create_processing_request(scope_key: str, key: str, operation_id: str, request_hash: str):
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"scope_key": scope_key,
			"idempotency_key": key,
			"endpoint": operation_id,
			"request_hash": request_hash,
			"user": frappe.session.user,
			"status": "Processing",
		}
	)
	doc.insert(ignore_permissions=True, ignore_links=True)
	return doc


def _raise_if_hash_conflict(request, request_hash: str, operation_id: str) -> None:
	if request.request_hash != request_hash:
		raise MobilePOSAPIError(
			"IDEMPOTENCY_KEY_REUSED",
			"The idempotency key was already used with different data.",
			status=409,
			details={"endpoint": operation_id},
		)


def _request_in_progress(operation_id: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"REQUEST_IN_PROGRESS",
		"A request with this idempotency key is still being processed.",
		status=409,
		retryable=True,
		details={"endpoint": operation_id, "retry_after_seconds": 1},
	)


def replay_response(request) -> dict:
	response = frappe.parse_json(request.response_json)
	response.setdefault("meta", {})["replayed"] = True
	frappe.response["http_status_code"] = 200
	return response


def _complete_request(
	request,
	response: dict,
	*,
	reference_doctype: str,
	reference_name: str,
	http_status: int,
	audit_reference_written: bool,
) -> None:
	now = now_datetime()
	request.status = "Completed"
	request.reference_doctype = reference_doctype
	request.reference_name = reference_name
	request.http_status = http_status
	request.response_json = frappe.as_json(response)
	request.resolved_at = now
	request.expires_at = now + timedelta(days=RETENTION_DAYS)
	request.audit_reference_written = 1 if audit_reference_written else 0
	# The service has already verified the business reference in
	# ``verify_business_reference``; the control record is the trusted writer and
	# must not re-validate the dynamic link existence on each update.
	request.flags.ignore_links = True
	request.save(ignore_permissions=True)


def verify_business_reference(operation_id: str, result: MutationResult, key: str) -> None:
	allowed = OPERATION_REFERENCE_DOCTYPES.get(operation_id)
	if not allowed:
		raise MobilePOSAPIError(
			"IDEMPOTENCY_INVARIANT",
			"Unknown Mobile POS operation.",
			status=500,
			details={"endpoint": operation_id},
		)
	if result.reference_doctype not in allowed:
		raise MobilePOSAPIError(
			"IDEMPOTENCY_INVARIANT",
			"The business reference DocType is not allowed for this operation.",
			status=500,
			details={"endpoint": operation_id, "reference_doctype": result.reference_doctype},
		)
	if not result.reference_name:
		raise MobilePOSAPIError(
			"IDEMPOTENCY_INVARIANT",
			"The mutation returned no business reference.",
			status=500,
			details={"endpoint": operation_id},
		)
	persisted = frappe.db.get_value(
		result.reference_doctype, result.reference_name, "custom_mobile_pos_transaction_id"
	)
	if persisted != key:
		raise MobilePOSAPIError(
			"IDEMPOTENCY_INVARIANT",
			"The business reference does not carry the request transaction id.",
			status=500,
			details={"endpoint": operation_id, "reference_doctype": result.reference_doctype},
		)


def execute_idempotent(
	operation_id: str,
	validated_payload: dict,
	operation: Callable[[str], MutationResult],
) -> dict:
	key = require_idempotency_key()
	request_hash = canonical_hash(operation_id, validated_payload)
	scope_key = _scope_key(key, operation_id)

	existing = _get_existing_request(scope_key)
	if existing:
		_raise_if_hash_conflict(existing, request_hash, operation_id)
		if existing.status == "Completed":
			return replay_response(existing)
		raise _request_in_progress(operation_id)

	savepoint = f"idem_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(savepoint)
	try:
		request = _create_processing_request(scope_key, key, operation_id, request_hash)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		frappe.db.rollback(save_point=savepoint)
		existing = _get_existing_request(scope_key)
		if not existing:
			raise MobilePOSAPIError(
				"IDEMPOTENCY_INVARIANT",
				"A concurrent idempotency request disappeared before resolution.",
				status=500,
				details={"endpoint": operation_id},
			)
		_raise_if_hash_conflict(existing, request_hash, operation_id)
		if existing.status == "Completed":
			return replay_response(existing)
		raise _request_in_progress(operation_id)

	try:
		result = operation(key)
		verify_business_reference(operation_id, result, key)
		response = success(result.data, http_status=result.http_status)
		_complete_request(
			request,
			response,
			reference_doctype=result.reference_doctype,
			reference_name=result.reference_name,
			http_status=result.http_status,
			audit_reference_written=True,
		)
		frappe.db.release_savepoint(savepoint)
		return response
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise


def delete_expired_requests(batch_size: int = CLEANUP_BATCH_SIZE) -> int:
	"""Delete cleanup-eligible terminal Mobile POS Request rows.

	Deletes only records whose status is Completed/Rejected, ``expires_at`` has
	passed, no retention hold is set, and (when a business reference exists) the
	referenced ERPNext document still stores the matching
	``custom_mobile_pos_transaction_id``. A mismatch sets a retention hold and
	logs an operational error instead of deleting. ERPNext business documents are
	never deleted or mutated.
	"""
	now = now_datetime()
	names = frappe.db.get_all(
		DOCTYPE,
		filters={
			"status": ["in", ["Completed", "Rejected"]],
			"expires_at": ["<=", now],
			"retention_hold": 0,
		},
		pluck="name",
		limit=batch_size,
	)
	deleted = 0
	for name in names:
		request = frappe.get_doc(DOCTYPE, name)
		if request.reference_doctype and request.reference_name:
			persisted = frappe.db.get_value(
				request.reference_doctype,
				request.reference_name,
				"custom_mobile_pos_transaction_id",
			)
			if persisted != request.idempotency_key:
				request.retention_hold = 1
				request.retention_reason = (
					"Referenced ERPNext document no longer carries the matching Mobile POS transaction id."
				)
				request.flags.ignore_links = True
				request.save(ignore_permissions=True)
				_log.error(
					"Mobile POS Request %s retained: reference %s %s transaction id mismatch.",
					name,
					request.reference_doctype,
					request.reference_name,
				)
				continue
		# The control record carries no child tables, files, or cascade links, so a
		# direct delete is safe and never touches ERPNext business documents.
		frappe.db.delete(DOCTYPE, {"name": name})
		deleted += 1
	return deleted
