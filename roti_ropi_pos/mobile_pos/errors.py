from __future__ import annotations


class MobilePOSAPIError(Exception):
	"""Stable, in-endpoint Mobile POS domain error.

	Authentication, mobile route-hook, rate-limit, and routing failures happen
	before endpoint code and retain Frappe's native response shape. Known
	failures raised after a v1 endpoint starts are mapped by
	``roti_ropi_pos.mobile_pos.responses.api_endpoint`` into the documented
	error envelope and HTTP status after rollback to the endpoint savepoint.
	Unknown exceptions are never converted into permission or domain errors;
	they propagate to Frappe's request-ID logging and native HTTP 500 handling.
	"""

	def __init__(
		self,
		code: str,
		message: str,
		*,
		status: int = 400,
		details: dict | None = None,
		retryable: bool = False,
	) -> None:
		super().__init__(message)
		self.code = code
		self.message = message
		self.status = status
		self.details = details or {}
		self.retryable = retryable
