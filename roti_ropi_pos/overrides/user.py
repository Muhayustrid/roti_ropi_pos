import frappe
from frappe.core.doctype.user.user import User
from frappe.model.document import LazyDocument


class MobilePOSUser(User):
	"""User controller override for Mobile POS.

	During migrations or fixture imports (e.g. sync_fixtures / bench migrate),
	Frappe uses `frappe.get_lazy_doc('User', ...)` when updating user roles/types.
	Because `LazyUser` is dynamically constructed at runtime via `type()`, RQ
	cannot pickle the class/instance if `create_contact` is enqueued into
	`frappe.db.after_commit`.

	Core `User.on_update` supports synchronous execution when `frappe.flags.in_install`
	or `frappe.in_test` is true (`now = frappe.in_test or frappe.flags.in_install`).
	This override preserves full core `User.on_update` behavior but temporarily
	forces `frappe.flags.in_install = True` around `super().on_update()` strictly
	when `self` is a `LazyDocument` and migration/import is active.
	"""

	def on_update(self):
		if self._is_lazy_migration_context():
			old_in_install = frappe.flags.get("in_install")
			frappe.flags.in_install = True
			try:
				super().on_update()
			finally:
				if old_in_install is None:
					frappe.flags.pop("in_install", None)
				else:
					frappe.flags.in_install = old_in_install
		else:
			super().on_update()

	def _is_lazy_migration_context(self) -> bool:
		return bool(isinstance(self, LazyDocument) and (frappe.flags.in_migrate or frappe.flags.in_import))
