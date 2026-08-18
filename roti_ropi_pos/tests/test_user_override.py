from unittest.mock import patch

import frappe
from frappe.model.document import LazyDocument, get_controller, get_lazy_controller
from frappe.tests import IntegrationTestCase


class TestUserOverride(IntegrationTestCase):
	def test_lazy_user_under_migrate_forces_synchronous_create_contact(self):
		"""Under frappe.flags.in_migrate, on_update on a LazyUser instance must execute

		create_contact synchronously (via now=True by forcing in_install context),
		leaving NO unpickleable after_commit payload in frappe.db.after_commit.
		"""
		# Ensure lazy controller for User is loaded
		lazy_user_cls = get_lazy_controller("User")
		self.assertTrue(issubclass(lazy_user_cls, LazyDocument))

		lazy_user = frappe.get_lazy_doc("User", "Administrator")
		self.assertIsInstance(lazy_user, LazyDocument)

		# Set up migrate context outside test
		previous_in_migrate = frappe.flags.get("in_migrate")
		previous_in_install = frappe.flags.get("in_install")
		previous_in_test = frappe.in_test

		frappe.flags.in_migrate = True
		frappe.flags.in_install = False
		frappe.in_test = False

		frappe.db.after_commit._functions.clear()

		try:
			with patch("frappe.core.doctype.user.user.create_contact") as mock_create_contact:
				lazy_user.on_update()

				# Must execute create_contact synchronously
				mock_create_contact.assert_called_once()
				self.assertEqual(mock_create_contact.call_args[1].get("user"), lazy_user)

				# Core cache invalidation may add an unrelated after-commit callback. The
				# migration hazard is specifically a queued callback that captures LazyUser.
				for callback in frappe.db.after_commit._functions:
					closure_values = [cell.cell_contents for cell in callback.__closure__ or ()]
					self.assertNotIn(
						lazy_user,
						closure_values,
						"LazyUser.on_update queued an unpickleable after_commit payload!",
					)

			# Ensure frappe.flags.in_install was restored to False
			self.assertFalse(frappe.flags.get("in_install"))
		finally:
			frappe.in_test = previous_in_test
			if previous_in_migrate is None:
				frappe.flags.pop("in_migrate", None)
			else:
				frappe.flags.in_migrate = previous_in_migrate
			if previous_in_install is None:
				frappe.flags.pop("in_install", None)
			else:
				frappe.flags.in_install = previous_in_install

	def test_normal_user_outside_migrate_retains_enqueue_behavior(self):
		"""Outside migrate/import, normal User.on_update retains core behavior (enqueueing

		create_contact via after_commit).
		"""
		normal_user = frappe.get_doc("User", "Administrator")
		self.assertNotIsInstance(normal_user, LazyDocument)

		previous_in_migrate = frappe.flags.get("in_migrate")
		previous_in_install = frappe.flags.get("in_install")
		previous_in_test = frappe.in_test

		frappe.flags.in_migrate = False
		frappe.flags.in_install = False
		frappe.in_test = False

		frappe.db.after_commit._functions.clear()

		try:
			normal_user.on_update()

			# In normal production mode outside test/install, create_contact is enqueued via after_commit
			self.assertEqual(
				len(frappe.db.after_commit._functions),
				1,
				"Normal User.on_update outside migrate must register after_commit callback",
			)
			self.assertFalse(frappe.flags.get("in_install"))
		finally:
			frappe.in_test = previous_in_test
			if previous_in_migrate is None:
				frappe.flags.pop("in_migrate", None)
			else:
				frappe.flags.in_migrate = previous_in_migrate
			if previous_in_install is None:
				frappe.flags.pop("in_install", None)
			else:
				frappe.flags.in_install = previous_in_install
