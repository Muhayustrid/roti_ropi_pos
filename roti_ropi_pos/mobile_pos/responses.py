from __future__ import annotations

import functools
import logging
from collections.abc import Callable

import frappe

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

_log = logging.getLogger(__name__)


def success(
	data: dict,
	*,
	http_status: int = 200,
	request_id: str | None = None,
	server_time: str | None = None,
	replayed: bool = False,
) -> dict:
	"""Build the stable success envelope and set the response HTTP status.

	Read-only endpoint adapters own their successful envelope. Standard
	mutation success envelopes are owned by ``execute_idempotent``; this
	helper must not be called by mutation operation callbacks.
	"""
	frappe.response["http_status_code"] = http_status
	return {
		"ok": True,
		"data": data,
		"meta": {
			"api_version": "v1",
			"request_id": request_id or frappe.generate_hash(length=26),
			"server_time": server_time or frappe.utils.now_datetime().astimezone().isoformat(),
			"replayed": replayed,
		},
	}


def error_envelope(error: MobilePOSAPIError, request_id: str, server_time: str) -> dict:
	return {
		"ok": False,
		"error": {
			"code": error.code,
			"message": error.message,
			"details": error.details,
			"retryable": error.retryable,
		},
		"meta": {
			"api_version": "v1",
			"request_id": request_id,
			"server_time": server_time,
			"replayed": False,
		},
	}


def api_endpoint(func: Callable[..., dict]) -> Callable[..., dict]:
	"""Common inner decorator for every v1 endpoint.

	Establishes a savepoint, maps ``MobilePOSAPIError`` into the documented
	error envelope/status after rollback, and re-raises unknown exceptions
	after request-ID logging. Known permission failures are converted to
	``MobilePOSAPIError`` by the service or common Mobile POS endpoint boundary
	before this mapper handles them; unknown exceptions are never converted into
	permission errors.

	Authentication, mobile route-hook, rate-limit, and routing failures happen
	before this decorator and retain Frappe's native response shape.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs) -> dict:
		savepoint = f"mobile_pos_{frappe.generate_hash(length=10)}"
		frappe.db.savepoint(savepoint)
		try:
			# Pass the handler return through unchanged. Read-only adapters and
			# ``execute_idempotent`` own their success envelopes; this decorator
			# only owns stable expected-error envelopes and the savepoint.
			return func(*args, **kwargs)
		except MobilePOSAPIError as error:
			frappe.db.rollback(save_point=savepoint)
			request_id = frappe.generate_hash(length=26)
			server_time = frappe.utils.now_datetime().astimezone().isoformat()
			_log.info("Mobile POS request %s failed: %s", request_id, error.code)
			frappe.response["http_status_code"] = error.status
			return error_envelope(error, request_id, server_time)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			request_id = frappe.generate_hash(length=26)
			_log.exception("Mobile POS request %s raised an unknown exception", request_id)
			raise
		finally:
			try:
				frappe.db.release_savepoint(savepoint)
			except Exception:  # release best-effort after rollback
				pass

	return wrapper
