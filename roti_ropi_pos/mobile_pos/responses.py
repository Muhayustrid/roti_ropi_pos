from __future__ import annotations

import functools
import logging
from collections.abc import Callable

import frappe

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

_log = logging.getLogger(__name__)

# Set once an endpoint has committed a phase it intends to keep. A commit ends the
# transaction and InnoDB drops every savepoint with it, so the endpoint savepoint is
# gone from that moment on and must never be named again.
_DURABLE_COMMIT_FLAG = "mobile_pos_durable_commit"


def commit_durable_phase() -> None:
	"""Commit a phase the endpoint must keep, and retire the endpoint savepoint.

	Closing deliberately commits its ``Reserved``, ``DraftCreated``, and
	``SubmitStarted`` phases so a crashed request can be recovered from the
	database alone. Each commit also destroys the savepoint ``api_endpoint``
	established: MariaDB then answers both ``ROLLBACK TO SAVEPOINT`` and
	``RELEASE SAVEPOINT`` with error 1305, ``SAVEPOINT ... does not exist``.
	Marking the commit keeps the endpoint from naming a savepoint that is gone,
	and keeps the committed phases from being undone by a later rollback that was
	only ever meant to reach the savepoint. The mark is set before the commit
	because the savepoint dies the moment ``COMMIT`` is issued, whichever
	``after_commit`` callback fails afterwards.
	"""
	frappe.flags[_DURABLE_COMMIT_FLAG] = True
	frappe.db.commit()


def _savepoint_survives() -> bool:
	return not frappe.flags.get(_DURABLE_COMMIT_FLAG)


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


def _rollback_to(savepoint: str) -> None:
	"""Undo the endpoint's writes without ever naming a retired savepoint.

	Two things retire the endpoint savepoint. A durable phase commit ends the
	transaction, and a transaction-level abort (InnoDB does this on deadlock)
	discards every savepoint. In both cases ``ROLLBACK TO SAVEPOINT`` fails with
	MariaDB 1305 and would replace the documented error envelope with a native
	HTTP 500. After a durable commit the fallback is also the only correct
	behaviour: a full rollback cannot undo what was committed, so the durable
	phases survive and only the uncommitted remainder is discarded.
	"""
	if not _savepoint_survives():
		frappe.db.rollback()
		return
	try:
		frappe.db.rollback(save_point=savepoint)
	except Exception:
		frappe.db.rollback()


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
		previous_durable_commit = frappe.flags.get(_DURABLE_COMMIT_FLAG)
		frappe.flags[_DURABLE_COMMIT_FLAG] = False
		frappe.db.savepoint(savepoint)
		try:
			# Pass the handler return through unchanged. Read-only adapters and
			# ``execute_idempotent`` own their success envelopes; this decorator
			# only owns stable expected-error envelopes and the savepoint.
			return func(*args, **kwargs)
		except MobilePOSAPIError as error:
			_rollback_to(savepoint)
			request_id = frappe.generate_hash(length=26)
			server_time = frappe.utils.now_datetime().astimezone().isoformat()
			_log.info("Mobile POS request %s failed: %s", request_id, error.code)
			frappe.response["http_status_code"] = error.status
			return error_envelope(error, request_id, server_time)
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			raise
		except Exception:
			_rollback_to(savepoint)
			request_id = frappe.generate_hash(length=26)
			_log.exception("Mobile POS request %s raised an unknown exception", request_id)
			raise
		finally:
			# A durable commit already retired the savepoint; naming it would raise
			# MariaDB 1305 for nothing.
			if _savepoint_survives():
				try:
					frappe.db.release_savepoint(savepoint)
				except Exception:  # release best-effort after a transaction abort
					pass
			frappe.flags[_DURABLE_COMMIT_FLAG] = previous_durable_commit

	return wrapper
