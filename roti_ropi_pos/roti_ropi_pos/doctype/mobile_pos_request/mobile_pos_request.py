import re

import frappe
from frappe import _
from frappe.model.document import Document

from roti_ropi_pos.mobile_pos.idempotency import OPERATION_REFERENCE_DOCTYPES

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_IMMUTABLE = ("scope_key", "idempotency_key", "request_hash", "user", "endpoint")
_VALID_TRANSITIONS = {
	"Processing": {"Completed", "Rejected"},
	"Completed": set(),
	"Rejected": set(),
}


class MobilePOSRequest(Document):
	def validate(self):
		self._validate_idempotency_key()
		self._validate_endpoint()
		self._validate_status()
		self._validate_immutability()
		self._validate_state_transition()
		self._validate_retention()

	def _validate_idempotency_key(self):
		if not self.idempotency_key or not _UUID.match(self.idempotency_key):
			frappe.throw(_("Idempotency key must be a lowercase UUID."))

	def _validate_endpoint(self):
		if self.endpoint not in OPERATION_REFERENCE_DOCTYPES:
			frappe.throw(_("Endpoint is not a recognized Mobile POS operation."))

	def _validate_status(self):
		if self.status not in _VALID_TRANSITIONS:
			frappe.throw(_("Status must be Processing, Completed, or Rejected."))

	def _validate_immutability(self):
		previous = self._previous_state()
		if not previous:
			return
		for field in _IMMUTABLE:
			if self.get(field) != previous.get(field):
				frappe.throw(_("{0} is immutable after creation.").format(_(field)))

	def _validate_state_transition(self):
		previous = self._previous_state()
		if not previous:
			return
		old = previous.get("status")
		new = self.status
		if old == new:
			return
		if new not in _VALID_TRANSITIONS.get(old, set()):
			frappe.throw(_("Cannot transition Mobile POS Request from {0} to {1}.").format(old, new))

	def _previous_state(self):
		if self.is_new():
			return None
		if not getattr(self, "_doc_before_save", None):
			self.load_doc_before_save()
		return self.get_doc_before_save()

	def _validate_retention(self):
		if self.retention_hold and not self.retention_reason:
			frappe.throw(_("A retention reason is required when retention hold is set."))
