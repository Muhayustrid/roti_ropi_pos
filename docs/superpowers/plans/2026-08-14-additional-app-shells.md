# Additional App Shells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish installable inactive shell releases for `selling_additional` and `stock_additional` without moving runtime ownership.

**Architecture:** Generate each normal Frappe scaffold in the bench. Replace its generated Git checkout with the existing GitHub repository, then copy only scaffold files into that checkout. Each shell declares ERPNext as its only dependency. Install guards allow the shell stage, reject unsafe direct target-release installation, and allow direct target installation on fresh sites.

**Tech Stack:** Python 3.14, Frappe and ERPNext v16, MariaDB, Flit, Ruff, ESLint, and pre-commit.

**Spec:** `docs/superpowers/specs/2026-08-14-app-ownership-extraction-design.md`

## Global Constraints

- Run every bench command inside `/workspace/development/frappe-bench` in the development container.
- Run `ls apps/ sites/ Procfile` once before any other bench command.
- Pass `--site development.localhost` to every site command.
- Use `development.localhost` as the implementation test site, per the user's execution-time choice. It must keep `allow_tests = true`, remain scheduler-disabled, and receive no destructive shared-data cleanup.
- Preserve each target repository's existing `.gitignore` and Git history.
- Use publisher `ITJURI`, email `ropierpnext@gmail.com`, and license `MIT`.
- Expose no moved DocType, fixture, hook, patch, or asset from either shell tag.
- Do not modify `bakery_manufacturing`, `roti_ropi_pos`, ERPNext, or Frappe in this phase.
- Do not reset, clean, stash, overwrite, or stage any existing dirty path.
- Do not install on an active site, push, tag, deploy, or commit without separate approval.
- Treat `sites/common_site_config.json` as shared bench state. Record whether `developer_mode` exists and its exact value before changing it.
- Get explicit approval before changing shared `developer_mode`. Restore its prior value or remove the key immediately after scaffolding.
- Do not remove the disposable generated repositories. Move them under `$CLAUDE_JOB_DIR/tmp` for the job lifetime.
- Do not uninstall either shell from `development.localhost`. Verify uninstall only on a separately approved disposable site. Shell uninstall is never a rollback method.

---

### Task 1: Record State and Verify the Development Test Site

**Files:**
- Verify only: every current app working tree
- Verify only: `sites/apps.txt`
- Verify only: `sites/development.localhost/`

**Interfaces:**
- Consumes: current bench and target GitHub repositories.
- Produces: a protected-state record and a verified development test site with Frappe, ERPNext, bakery, `allow_tests = true`, and scheduler disabled.

- [ ] **Step 1: Confirm the bench root**

Inside the container:

```bash
cd /workspace/development/frappe-bench
ls apps/ sites/ Procfile
```

Expected: all three paths exist. Run no other bench command if this fails.

- [ ] **Step 2: Record protected working trees**

On the host:

```bash
git -C apps/roti_ropi_pos status --short
git -C apps/bakery_manufacturing status --short
git -C apps/erpnext status --short
git -C apps/frappe status --short
gh repo view Muhayustrid/selling_additional --json defaultBranchRef,url
gh repo view Muhayustrid/stock_additional --json defaultBranchRef,url
```

Expected: both target default branches are `main`. Store this output in the execution transcript. Do not write it into a repository.

- [ ] **Step 3: Record shared developer mode and request approval only if a temporary change is needed**

Read `sites/common_site_config.json` without printing unrelated keys. Record one of these states in the execution transcript:

```text
developer_mode: absent
developer_mode: 0
developer_mode: 1
```

`bench new-app` does not require developer mode. Skip any config change unless the approved scaffold environment needs development dependencies. If a change is needed, get explicit approval first, then run:

```bash
cd /workspace/development/frappe-bench
bench set-config -g developer_mode 1
```

After both scaffolds exist, restore the recorded state exactly:

```bash
# Prior value was 0
bench set-config -g developer_mode 0

# Prior key was absent. Installed Frappe treats literal None as deletion.
bench set-config -g developer_mode None
```

Expected: no active site's effective developer mode changes beyond the approved scaffold window. Never print `show-config` or the full config file because it can contain secrets.

- [ ] **Step 4: Verify the existing development test site**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost list-apps
bench --site development.localhost scheduler status
python - <<'PY'
import json
from pathlib import Path

config = json.loads(Path("sites/development.localhost/site_config.json").read_text())
print(f"allow_tests={config.get('allow_tests', False)}")
PY
```

Expected: site lists `frappe`, `erpnext`, `bakery_manufacturing`, and `roti_ropi_pos`; scheduler is disabled; `allow_tests=True`. Do not recreate the site or reinstall existing apps.

- [ ] **Step 5: Verify current bakery ownership**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost execute frappe.db.get_value \
  --args '["DocType", "Price Group", "module"]'
bench --site development.localhost execute frappe.override_whitelisted_method \
  --args '["erpnext.stock.utils.scan_barcode"]'
```

Expected: Price Group remains `Bakery Manufacturing`, and scanner resolves to the bakery path. This step writes nothing.

### Task 2: Scaffold the `selling_additional` Shell

**Files:**
- Create through scaffold: `selling_additional/README.md`
- Create through scaffold: `selling_additional/license.txt`
- Create through scaffold: `selling_additional/pyproject.toml`
- Create through scaffold: `selling_additional/.editorconfig`
- Create through scaffold: `selling_additional/.eslintrc`
- Create through scaffold: `selling_additional/.pre-commit-config.yaml`
- Create through scaffold: `selling_additional/selling_additional/__init__.py`
- Modify: `selling_additional/selling_additional/hooks.py`
- Create: `selling_additional/selling_additional/install.py`
- Create through scaffold: `selling_additional/selling_additional/modules.txt`
- Create through scaffold: `selling_additional/selling_additional/patches.txt`
- Create through scaffold: `selling_additional/selling_additional/selling_additional/__init__.py`
- Test: `selling_additional/selling_additional/tests/test_shell_contract.py`

**Interfaces:**
- Consumes: Frappe's `bench new-app` generator and `origin/main` from `Muhayustrid/selling_additional`.
- Produces: app `selling_additional`, module `Selling Additional`, and `required_apps = ["erpnext"]`.
- Produces: `selling_additional.install.before_install()`.
- The guard allows shell installation when bakery owns Price Group.
- The guard rejects a direct target-release install when target DocType JSON exists and bakery owns Price Group.
- The guard allows a direct target-release install when no Price Group metadata exists.

- [ ] **Step 1: Generate the disposable scaffold**

Inside the container:

```bash
cd /workspace/development/frappe-bench
printf 'Selling Additional\nERPNext extensions for pricing, POS, and selling workflows\nITJURI\nropierpnext@gmail.com\nmit\nN\nN\nN\n' | bench new-app selling_additional
```

Expected: `apps/selling_additional` contains a normal Frappe app scaffold and `sites/apps.txt` contains `selling_additional` once.

- [ ] **Step 2: Replace only the generated Git checkout**

On the host:

```bash
mv apps/selling_additional "$CLAUDE_JOB_DIR/tmp/selling_additional-scaffold"
git clone https://github.com/Muhayustrid/selling_additional.git apps/selling_additional
rsync -a --exclude='.git' --exclude='.gitignore' \
  "$CLAUDE_JOB_DIR/tmp/selling_additional-scaffold/" \
  apps/selling_additional/
git -C apps/selling_additional switch -c feat/inactive-shell
git -C apps/selling_additional status --short
```

Expected: remote `.gitignore` remains unchanged. All other scaffold paths appear as additions on `feat/inactive-shell`.

- [ ] **Step 3: Write the failing shell contract tests**

Create `selling_additional/selling_additional/tests/test_shell_contract.py`:

```python
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe


class TestSellingAdditionalShell(unittest.TestCase):
    def test_metadata_and_dependency(self):
        hooks = importlib.import_module("selling_additional.hooks")

        self.assertEqual(hooks.app_title, "Selling Additional")
        self.assertEqual(
            hooks.app_description,
            "ERPNext extensions for pricing, POS, and selling workflows",
        )
        self.assertEqual(hooks.app_publisher, "ITJURI")
        self.assertEqual(hooks.app_email, "ropierpnext@gmail.com")
        self.assertEqual(hooks.app_license.lower(), "mit")
        self.assertEqual(hooks.required_apps, ["erpnext"])

    def test_shell_registers_no_moved_runtime_ownership(self):
        hooks = importlib.import_module("selling_additional.hooks")

        self.assertFalse(getattr(hooks, "override_whitelisted_methods", {}))
        self.assertFalse(getattr(hooks, "doc_events", {}))
        self.assertFalse(getattr(hooks, "fixtures", []))
        self.assertFalse(getattr(hooks, "page_js", {}))
        self.assertFalse(getattr(hooks, "after_migrate", []))

    @patch("selling_additional.install._target_price_group_json_exists", return_value=False)
    @patch("selling_additional.install._bakery_owns_price_group", return_value=True)
    def test_shell_install_allows_bakery_owned_price_group(self, _owns, _target_exists):
        from selling_additional.install import before_install

        before_install()

    @patch("selling_additional.install._target_price_group_json_exists", return_value=True)
    @patch("selling_additional.install._bakery_owns_price_group", return_value=True)
    def test_direct_target_install_rejects_bakery_owned_price_group(self, _owns, _target_exists):
        from selling_additional.install import before_install

        with self.assertRaises(frappe.ValidationError):
            before_install()

    def test_shell_contains_no_target_doctype_json(self):
        app_root = Path(__file__).parents[1]
        self.assertFalse(
            (app_root / "selling_additional" / "doctype" / "price_group" / "price_group.json").exists()
        )

    def test_patches_file_has_both_migration_sections(self):
        patches = (Path(__file__).parents[1] / "patches.txt").read_text()
        self.assertEqual(
            patches,
            "[pre_model_sync]\n\n[post_model_sync]\n",
        )

    @patch("selling_additional.install._target_price_group_json_exists", return_value=True)
    @patch("selling_additional.install._bakery_owns_price_group", return_value=False)
    def test_fresh_target_install_without_legacy_metadata_passes(self, _owns, _target_exists):
        from selling_additional.install import before_install

        before_install()
```

Write `selling_additional/patches.txt` exactly as:

```text
[pre_model_sync]

[post_model_sync]
```

Both headers stay in shell and target releases. Frappe's INI parser expects both sections when migration requests each patch type.

- [ ] **Step 4: Run the test and verify RED**

Inside the container:

```bash
cd /workspace/development/frappe-bench
python -m unittest selling_additional.tests.test_shell_contract
```

Expected: FAIL because `required_apps` and `selling_additional.install` do not exist.

- [ ] **Step 5: Add minimal shell metadata**

Keep scaffold metadata and add this exact dependency in `selling_additional/hooks.py`:

```python
required_apps = ["erpnext"]
before_install = "selling_additional.install.before_install"
```

Do not add DocType JSON, fixtures, runtime overrides, document events, patches, or assets.

- [ ] **Step 6: Implement the target-release guard**

Create `selling_additional/install.py`:

```python
from pathlib import Path

import frappe
from frappe import _


def _target_price_group_json_exists() -> bool:
    return Path(
        frappe.get_app_path(
            "selling_additional",
            "selling_additional",
            "doctype",
            "price_group",
            "price_group.json",
        )
    ).is_file()


def _bakery_owns_price_group() -> bool:
    return bool(
        frappe.db.exists(
            "DocType",
            {"name": "Price Group", "module": "Bakery Manufacturing"},
        )
    )


def before_install() -> None:
    if _target_price_group_json_exists() and _bakery_owns_price_group():
        frappe.throw(
            _(
                "Install the inactive selling_additional shell before deploying "
                "the Price Group cutover release."
            )
        )
```

This file has no install-time write.

- [ ] **Step 7: Run the unit tests and verify GREEN**

```bash
cd /workspace/development/frappe-bench
python -m unittest selling_additional.tests.test_shell_contract
```

Expected: PASS.

- [ ] **Step 8: Install the shell on the development test site**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost install-app selling_additional
bench --site development.localhost list-apps
```

Expected: install succeeds although Price Group remains bakery-owned. Site lists `selling_additional` after `bakery_manufacturing`.

- [ ] **Step 9: Verify installed shell state**

Add an integration test to `test_shell_contract.py` using `IntegrationTestCase`:

```python
from frappe.tests import IntegrationTestCase


class TestInstalledSellingAdditionalShell(IntegrationTestCase):
    def test_module_exists_without_ownership_transfer(self):
        self.assertTrue(frappe.db.exists("Module Def", "Selling Additional"))
        self.assertEqual(
            frappe.db.get_value("DocType", "Price Group", "module"),
            "Bakery Manufacturing",
        )
```

Run:

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module selling_additional.tests.test_shell_contract
```

Expected: PASS.

- [ ] **Step 10: Run static checks**

```bash
cd /workspace/development/frappe-bench/apps/selling_additional
pre-commit run --all-files
git diff --check
git status --short
```

Expected: all checks pass. Only intended scaffold and shell files differ.

- [ ] **Step 11: Stop for commit approval**

Show `git diff --stat`, `git diff`, test output, and protected working-tree status. After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/selling_additional
git add .editorconfig .eslintrc .gitignore .pre-commit-config.yaml README.md license.txt pyproject.toml \
  selling_additional
git diff --cached --name-status
git commit -m "feat: add inactive selling additional shell"
```

Expected: one target-repository commit. Do not stage an unexpected file.

### Task 3: Scaffold the `stock_additional` Shell

**Files:**
- Create through scaffold: `stock_additional/README.md`
- Create through scaffold: `stock_additional/license.txt`
- Create through scaffold: `stock_additional/pyproject.toml`
- Create through scaffold: `stock_additional/.editorconfig`
- Create through scaffold: `stock_additional/.eslintrc`
- Create through scaffold: `stock_additional/.pre-commit-config.yaml`
- Create through scaffold: `stock_additional/stock_additional/__init__.py`
- Modify: `stock_additional/stock_additional/hooks.py`
- Create: `stock_additional/stock_additional/install.py`
- Create through scaffold: `stock_additional/stock_additional/modules.txt`
- Create through scaffold: `stock_additional/stock_additional/patches.txt`
- Create through scaffold: `stock_additional/stock_additional/stock_additional/__init__.py`
- Test: `stock_additional/stock_additional/tests/test_shell_contract.py`

**Interfaces:**
- Consumes: Frappe's `bench new-app` generator and `origin/main` from `Muhayustrid/stock_additional`.
- Produces: app `stock_additional`, module `Stock Additional`, and `required_apps = ["erpnext"]`.
- Produces: `stock_additional.install.before_install()`.
- The guard allows shell installation while bakery provides the scanner.
- The guard rejects direct target-release installation while bakery still registers the scanner.
- The guard allows direct target installation on a fresh site without bakery.

- [ ] **Step 1: Generate the disposable scaffold**

```bash
cd /workspace/development/frappe-bench
printf 'Stock Additional\nERPNext extensions for stock scanning and inventory workflows\nITJURI\nropierpnext@gmail.com\nmit\nN\nN\nN\n' | bench new-app stock_additional
```

Expected: `apps/stock_additional` contains a normal scaffold and `sites/apps.txt` contains `stock_additional` once.

- [ ] **Step 2: Replace only the generated Git checkout**

On the host:

```bash
mv apps/stock_additional "$CLAUDE_JOB_DIR/tmp/stock_additional-scaffold"
git clone https://github.com/Muhayustrid/stock_additional.git apps/stock_additional
rsync -a --exclude='.git' --exclude='.gitignore' \
  "$CLAUDE_JOB_DIR/tmp/stock_additional-scaffold/" \
  apps/stock_additional/
git -C apps/stock_additional switch -c feat/inactive-shell
git -C apps/stock_additional status --short
```

Expected: remote `.gitignore` remains unchanged. All other scaffold paths appear as additions.

- [ ] **Step 3: Write the failing shell contract tests**

Create `stock_additional/stock_additional/tests/test_shell_contract.py`:

```python
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe


class TestStockAdditionalShell(unittest.TestCase):
    def test_metadata_and_dependency(self):
        hooks = importlib.import_module("stock_additional.hooks")

        self.assertEqual(hooks.app_title, "Stock Additional")
        self.assertEqual(
            hooks.app_description,
            "ERPNext extensions for stock scanning and inventory workflows",
        )
        self.assertEqual(hooks.app_publisher, "ITJURI")
        self.assertEqual(hooks.app_email, "ropierpnext@gmail.com")
        self.assertEqual(hooks.app_license.lower(), "mit")
        self.assertEqual(hooks.required_apps, ["erpnext"])

    def test_shell_registers_no_moved_runtime_ownership(self):
        hooks = importlib.import_module("stock_additional.hooks")

        self.assertFalse(getattr(hooks, "override_whitelisted_methods", {}))
        self.assertFalse(getattr(hooks, "doc_events", {}))
        self.assertFalse(getattr(hooks, "fixtures", []))

    @patch("stock_additional.install._target_scanner_exists", return_value=False)
    @patch("stock_additional.install._bakery_registers_scanner", return_value=True)
    def test_shell_install_allows_bakery_scanner(self, _registers, _target_exists):
        from stock_additional.install import before_install

        before_install()

    @patch("stock_additional.install._target_scanner_exists", return_value=True)
    @patch("stock_additional.install._bakery_registers_scanner", return_value=True)
    def test_direct_target_install_rejects_bakery_scanner(self, _registers, _target_exists):
        from stock_additional.install import before_install

        with self.assertRaises(frappe.ValidationError):
            before_install()

    def test_shell_contains_no_target_scanner(self):
        app_root = Path(__file__).parents[1]
        self.assertFalse((app_root / "overrides" / "barcode_scanner.py").exists())

    def test_patches_file_has_both_migration_sections(self):
        patches = (Path(__file__).parents[1] / "patches.txt").read_text()
        self.assertEqual(
            patches,
            "[pre_model_sync]\n\n[post_model_sync]\n",
        )

    @patch("stock_additional.install._target_scanner_exists", return_value=True)
    @patch("stock_additional.install._bakery_registers_scanner", return_value=False)
    def test_fresh_target_install_without_legacy_provider_passes(self, _registers, _target_exists):
        from stock_additional.install import before_install

        before_install()
```

Write `stock_additional/patches.txt` exactly as:

```text
[pre_model_sync]

[post_model_sync]
```

Both headers stay in shell and target releases.

- [ ] **Step 4: Run the test and verify RED**

```bash
cd /workspace/development/frappe-bench
python -m unittest stock_additional.tests.test_shell_contract
```

Expected: FAIL because `required_apps` and `stock_additional.install` do not exist.

- [ ] **Step 5: Add minimal shell metadata**

Add to `stock_additional/hooks.py`:

```python
required_apps = ["erpnext"]
before_install = "stock_additional.install.before_install"
```

Do not add a fixture, scanner hook, Item hook, patch, or asset.

- [ ] **Step 6: Implement the target-release guard**

Create `stock_additional/install.py`:

```python
from pathlib import Path

import frappe
from frappe import _

SCANNER_METHOD = "erpnext.stock.utils.scan_barcode"
BAKERY_SCANNER = "bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode"


def _target_scanner_exists() -> bool:
    return Path(
        frappe.get_app_path("stock_additional", "overrides", "barcode_scanner.py")
    ).is_file()


def _bakery_registers_scanner() -> bool:
    if "bakery_manufacturing" not in frappe.get_installed_apps():
        return False

    providers = frappe.get_hooks(
        "override_whitelisted_methods",
        app_name="bakery_manufacturing",
    ).get(SCANNER_METHOD, [])
    return BAKERY_SCANNER in providers


def before_install() -> None:
    if _target_scanner_exists() and _bakery_registers_scanner():
        frappe.throw(
            _(
                "Install the inactive stock_additional shell before deploying "
                "the barcode cutover release."
            )
        )
```

The guard reads hook state and writes nothing.

- [ ] **Step 7: Run the unit tests and verify GREEN**

```bash
cd /workspace/development/frappe-bench
python -m unittest stock_additional.tests.test_shell_contract
```

Expected: PASS.

- [ ] **Step 8: Install the shell on the development test site**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost install-app stock_additional
bench --site development.localhost list-apps
```

Expected: install succeeds while bakery remains the only active scanner provider.

- [ ] **Step 9: Verify installed shell state**

Add:

```python
from frappe.tests import IntegrationTestCase


class TestInstalledStockAdditionalShell(IntegrationTestCase):
    def test_module_exists_without_scanner_transfer(self):
        self.assertTrue(frappe.db.exists("Module Def", "Stock Additional"))
        providers = frappe.get_hooks("override_whitelisted_methods").get(
            "erpnext.stock.utils.scan_barcode",
            [],
        )
        self.assertNotIn(
            "stock_additional.overrides.barcode_scanner.custom_scan_barcode",
            providers,
        )
```

Run:

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_shell_contract
```

Expected: PASS.

- [ ] **Step 10: Run static checks**

```bash
cd /workspace/development/frappe-bench/apps/stock_additional
pre-commit run --all-files
git diff --check
git status --short
```

Expected: all checks pass. Only intended scaffold and shell files differ.

- [ ] **Step 11: Stop for commit approval**

Show the intended diff and tests. After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/stock_additional
git add .editorconfig .eslintrc .gitignore .pre-commit-config.yaml README.md license.txt pyproject.toml \
  stock_additional
git diff --cached --name-status
git commit -m "feat: add inactive stock additional shell"
```

Expected: one target-repository commit. Do not stage an unexpected file.

### Task 4: Verify Shell Install Behavior and Prepare Separate Uninstall Test

**Files:**
- Test: `selling_additional/selling_additional/tests/test_shell_contract.py`
- Test: `stock_additional/stock_additional/tests/test_shell_contract.py`
- Verify only: site metadata and current source trees

**Interfaces:**
- Consumes: both shell commits and existing `development.localhost` test site.
- Produces: proof that shell lifecycle changes no moved ownership.

- [ ] **Step 1: Record baseline ownership**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost execute \
  frappe.db.get_value --args '["DocType", "Price Group", "module"]'
bench --site development.localhost list-apps
```

Expected: Price Group module is `Bakery Manufacturing`. Both shell apps are installed.

- [ ] **Step 2: Run full shell suites**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests --app selling_additional
bench --site development.localhost run-tests --app stock_additional
```

Expected: both suites pass.

- [ ] **Step 3: Keep uninstall off the shared development site**

Do not run `uninstall-app` on `development.localhost`. Record shell install invariants there only: both Module Def rows exist, Price Group remains bakery-owned, and bakery remains scanner and past-order provider.

The uninstall/reinstall lifecycle requires a separately approved disposable site. If approved later, create that site from the same shell commits, install current bakery plus both shells, record bakery-owned row counts, uninstall both shells, verify bakery tables and counts remain, then reinstall. Do not use shared development data for this destructive proof.

- [ ] **Step 4: Recheck protected working trees**

On the host:

```bash
git -C apps/roti_ropi_pos status --short
git -C apps/bakery_manufacturing status --short
git -C apps/erpnext status --short
git -C apps/frappe status --short
```

Expected: outputs match Task 1, except this plan remains an intended untracked file in `roti_ropi_pos` until separately approved.

### Task 5: Review and Publish the Shell Releases

**Files:**
- Modify: `selling_additional/README.md`
- Modify: `stock_additional/README.md`
- Verify: all files in both target repositories

**Interfaces:**
- Consumes: green shell commits.
- Produces: reviewed shell branches and immutable release tags for Stage A.

- [ ] **Step 1: Document shell scope**

Add this section to both README files:

```markdown
## Shell release

This release installs only the app and its module. It does not own runtime
hooks, DocTypes, Custom Fields, migrations, or assets. Feature ownership moves
in the coordinated cutover release.
```

Document `required_apps = ["erpnext"]` and the tested Frappe v16 range.

- [ ] **Step 2: Run final gates**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests --app selling_additional
bench --site development.localhost run-tests --app stock_additional
cd apps/selling_additional && pre-commit run --all-files && git diff --check
cd ../stock_additional && pre-commit run --all-files && git diff --check
```

Expected: all tests and checks pass.

- [ ] **Step 3: Stop for README commit approval**

After explicit approval:

```bash
git -C apps/selling_additional add README.md
git -C apps/selling_additional commit -m "docs: define inactive shell scope"
git -C apps/stock_additional add README.md
git -C apps/stock_additional commit -m "docs: define inactive shell scope"
```

- [ ] **Step 4: Request independent review**

Use `superpowers:requesting-code-review` for both target repository diffs. Fix only confirmed shell findings. Reject changes that move feature ownership into this release.

- [ ] **Step 5: Stop for push and tag approval**

Report each branch, SHA, diff, test result, and proposed tag. Do not push or tag until explicit approval.

After approval:

```bash
git -C apps/selling_additional push -u origin feat/inactive-shell
git -C apps/stock_additional push -u origin feat/inactive-shell
git -C apps/selling_additional tag -a shell-v0.1.0 -m "Inactive selling additional shell"
git -C apps/stock_additional tag -a shell-v0.1.0 -m "Inactive stock additional shell"
git -C apps/selling_additional push origin shell-v0.1.0
git -C apps/stock_additional push origin shell-v0.1.0
```

Expected: remote branches and annotated shell tags point to reviewed SHAs.

- [ ] **Step 6: Verify the staged shell boundary before publishing**

On `development.localhost`, assert Price Group remains bakery-owned and bakery remains scanner and past-order provider after both shell installs. Run uninstall/reinstall only on a separately approved disposable site.

Document that `before_install` does not protect an already-installed shell. Frappe returns early for an installed app before invoking this hook. Target-release safety belongs to each cutover release's `pre_model_sync` assertion and populated-upgrade tests.

Fresh direct target-install and unsafe populated-cutover scenarios require cutover code. Run them in the stock and selling cutover plans, not this shell plan.

Expected: shell installation changes no runtime ownership.

- [ ] **Step 7: Restore shared developer mode and stop before any target-site installation**

If Task 1 temporarily changed `developer_mode`, restore the exact recorded value now and verify only that key. Stage A installation on any target site belongs to the coordinated rollout plan. Shell completion does not authorize active-site installation.
