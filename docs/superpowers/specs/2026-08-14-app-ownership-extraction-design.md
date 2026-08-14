# App Ownership Extraction Design

**Status:** Draft for review
**Date:** 2026-08-14
**Scope:** `bakery_manufacturing`, `selling_additional`, `stock_additional`, and `roti_ropi_pos`

## 1. Purpose

Move generic stock and selling extensions out of `bakery_manufacturing`.
Keep all existing DocType names, Custom Field names, tables, and business data.
Fix the confirmed barcode, Price Group, and sidebar defects during the ownership cutover.

This work uses a staged rollout. The new apps install first as inactive shells.
A coordinated release then transfers metadata, fixtures, hooks, assets, and runtime ownership.

## 2. Approved Decisions

- Use `https://github.com/Muhayustrid/stock_additional.git` for stock extensions.
- Use `https://github.com/Muhayustrid/selling_additional.git` for selling extensions.
- Keep all three Price Group DocType names unchanged.
- Move the Desk POS walk-in customization to `selling_additional` now.
- Give `selling_additional` its own Workspace and Workspace Sidebar.
- Do not inject Price Group into ERPNext's Selling sidebar.
- Use a staged rollout without a feature outage.
- Keep the uncommitted bakery sidebar prototype patch unchanged.
- Restore only the known leaked Price Group edit in ERPNext's sidebar source.
- Use test-driven development for every behavior change.

## 3. App Metadata

### `selling_additional`

- Title: `Selling Additional`
- Description: `ERPNext extensions for pricing, POS, and selling workflows`
- Publisher: `ITJURI`
- Email: `ropierpnext@gmail.com`
- License: `MIT`

### `stock_additional`

- Title: `Stock Additional`
- Description: `ERPNext extensions for stock scanning and inventory workflows`
- Publisher: `ITJURI`
- Email: `ropierpnext@gmail.com`
- License: `MIT`

## 4. Target Ownership

### 4.1 `stock_additional`

`stock_additional` owns:

- `Item.custom_default_uom_warehouse`;
- the effective `erpnext.stock.utils.scan_barcode` override;
- batch default-UOM resolution;
- conversion-factor validation;
- barcode hook, fixture, source-contract, and integration tests.

It does not own Manufacture Stock Entry behavior.

### 4.2 `selling_additional`

`selling_additional` owns:

- `Price Group`;
- `Price Group Item`;
- `Price Group Outlet`;
- the Price Group form script;
- generated Price List and Item Price management;
- POS Profile assignment and recovery;
- `POS Invoice.custom_walk_in_customer_name`;
- `Sales Invoice.custom_walk_in_customer_name`;
- Desk POS walk-in input and validation;
- the effective past-order list override;
- its own Workspace and Workspace Sidebar;
- related fixtures, patches, assets, and tests.

### 4.3 `bakery_manufacturing`

`bakery_manufacturing` owns only bakery manufacturing behavior:

- the `Serial and Batch Bundle` controller override;
- Manufacture Stock Entry batch-quantity synchronization;
- focused manufacturing tests.

One compatibility release may keep lazy import shims for moved Python paths.
The shims contain no business logic and register no hooks.

The existing uncommitted `SidebarHeader.prototype` patch and its untracked test remain untouched.
They are not part of this extraction.

### 4.4 `roti_ropi_pos`

`roti_ropi_pos` keeps ownership of:

- the Mobile POS API;
- OAuth and cashier authorization;
- idempotency and recovery;
- DTO and error contracts;
- ERPNext POS orchestration.

It consumes persisted fields and effective registered hooks.
It does not import private helpers from the three extension apps.

## 5. Dependency Graph

```python
# stock_additional/hooks.py
required_apps = ["erpnext"]

# selling_additional/hooks.py
required_apps = ["erpnext"]

# bakery_manufacturing/hooks.py
required_apps = ["erpnext"]

# roti_ropi_pos/hooks.py
required_apps = ["erpnext", "stock_additional", "selling_additional"]
```

`roti_ropi_pos` no longer depends on `bakery_manufacturing`.

Each moved hook must have exactly one active provider.
Tests must enumerate providers across all installed apps.
Installed-app order must not select behavior through duplicate hooks.

## 6. Non-Goals

This work does not:

- rename a DocType, table, field, or business document;
- change Mobile POS API contracts;
- change the Manufacture Stock Entry algorithm;
- move ERPNext transactional rows to new tables;
- uninstall `bakery_manufacturing`;
- edit Frappe source;
- add Price Group to ERPNext's Selling sidebar;
- remove the uncommitted bakery sidebar prototype patch.

## 7. Stock Barcode Correctness

### 7.1 Item Configuration

Add an Item validation hook in `stock_additional`.

If the custom UOM is empty, validation succeeds.
If the custom UOM equals the stock UOM, validation succeeds without a conversion row.
If the UOMs differ, the Item must contain a positive conversion factor for the custom UOM.
A missing, zero, or negative factor raises a configuration error.

The scanner repeats this validation at runtime.
This protects legacy invalid data and direct database changes.

### 7.2 Scan Behavior

The override keeps the installed ERPNext scanner signature.
It calls the core scanner first.
It enriches only results with both `batch_no` and `item_code`.

A valid custom UOM returns:

```python
{
    "uom": custom_uom,
    "conversion_factor": positive_factor,
}
```

A missing, zero, or negative factor raises a validation error.
The override must not return the custom UOM in that case.
The transaction row must remain unchanged.

This replaces the current warning-only behavior.
It prevents one carton from silently posting as one stock unit.

## 8. Price Group Ownership Model

### 8.1 Ownership Fields

`selling_additional` owns these read-only Custom Fields:

- `Price List.custom_selling_additional_price_group`;
- `Item Price.custom_selling_additional_price_group`;
- `POS Profile.custom_selling_additional_price_group`;
- `POS Profile.custom_selling_additional_previous_price_list`.

Each field links to the existing `Price Group` DocType.
The previous-price-list field links to `Price List`.

These fields replace naming conventions as the ownership authority.
The `PG-<price_group_name>` convention remains for generated Price List names.

### 8.2 Locking

A Price Group save locks its own database row through the document update.
It then locks target POS Profile rows in sorted name order.
It checks ownership only after acquiring those locks.

A profile owned by another Price Group causes a validation error.
Concurrent claims produce one owner and one rejected transaction.

The Price Group row lock serializes managed Price List and Item Price changes for one group.
Name and ownership checks reject collisions before mutation.

### 8.3 Enabled Lifecycle

When a Price Group is enabled:

1. Create or enable its managed Price List.
2. Update the Price List currency.
3. Mark the Price List as owned by the Price Group.
4. Upsert managed Item Prices by `(item_code, uom)`.
5. Delete only stale Item Prices marked as owned by the Price Group.
6. Lock every desired POS Profile.
7. Save each profile's previous price list before the first claim.
8. Claim each profile and assign the managed Price List.
9. Restore owned profiles that no longer match an outlet.

Customer-specific, supplier-specific, batch-specific, date-specific, and unmarked Item Prices remain untouched.

### 8.4 Disabled Lifecycle

When a Price Group is disabled:

1. Restore every POS Profile owned by the Price Group.
2. Clear the profile ownership fields.
3. Disable the managed Price List.
4. Keep managed Item Prices for a later re-enable.
5. Skip Item Price saves while the Price List is disabled.

This avoids ERPNext's rejection of Item Price saves against a disabled Price List.

### 8.5 Delete Lifecycle

Before deleting a Price Group:

1. Lock and restore every owned POS Profile.
2. Delete only Item Prices marked as owned by the Price Group.
3. Clear the Price List ownership marker.
4. Disable the Price List.
5. Keep the Price List record.

The controller must not use `force=True`.
It must not delete unmarked prices.
It must fail before mutation when ownership invariants do not match.

Keeping the Price List avoids dangling historical and custom references.

### 8.6 UOM Changes

Managed Item Price identity uses `(item_code, uom)`.
If an Item stock UOM changes, the next Price Group save creates the new managed row.
It then removes the old managed UOM row.

Unmarked legacy rows require explicit operator classification during migration.
The migration must not guess their ownership.

## 9. Desk POS Walk-In Behavior

### 9.1 Validation

A non-empty walk-in display name requires:

- a POS Profile;
- an enabled default Customer on that profile;
- an invoice Customer equal to that default Customer.

The validation runs in `selling_additional` for both POS Invoice and POS-created Sales Invoice paths.
It rejects the field for a registered non-default Customer.

`roti_ropi_pos` keeps its existing API validation.
The selling validation provides defense for Desk and other server call paths.

### 9.2 Client Behavior

Use a page-specific POS asset instead of a global Desk asset.
Do not run a one-second timer on every Desk route.

When the Customer changes or resets, clear `custom_walk_in_customer_name`.
Render one walk-in input on the POS page.
Do not patch HTML by replacing escaped customer-name text.

### 9.3 Past Orders

The server override keeps permission-aware ERPNext queries.
It searches `custom_walk_in_customer_name` alongside Customer fields.

For display, project the walk-in name into the response's display customer name.
Keep the actual `customer` identifier unchanged.
The standard ERPNext renderer then displays the projected name.

This removes the fragile `String.replace()` markup mutation.

## 10. App-Owned Navigation

`selling_additional` ships:

- a standard `Selling Additional` Workspace;
- a standard `Selling Additional` Workspace Sidebar;
- a Price Group link owned by that sidebar.

It does not save ERPNext's standard `Selling` Workspace Sidebar.
It does not use a runtime prototype patch to add the Price Group link.
It does not include the old bakery `after_migrate` hook.

## 11. Staged Migration

### 11.1 Stage A: Install Inactive Shell Apps

Create both Frappe apps from their existing GitHub repositories.
The first release contains metadata, module definitions, dependencies, and install guards.
It contains no moved DocType JSON, fixture, runtime override, or public asset.

Install both shell apps on each target site.
This creates the `Selling Additional` and `Stock Additional` Module Def records.
It does not change existing behavior.

A target-release `before_install` guard must detect existing bakery-owned Price Group metadata.
It must reject direct target installation when the shell stage was skipped.
Fresh sites without Price Group metadata may install the target release directly.

### 11.2 Stage B: Preflight

Stop traffic and workers before cutover.
Take a database and files backup.
Record all four app SHAs and installed-app order.

Run a read-only preflight that checks:

- all three Price Group DocTypes exist;
- all Price Group parents and child rows are readable;
- every linked generated Price List exists;
- no outlet causes two Price Groups to claim one POS Profile;
- every candidate managed Item Price has one unambiguous owner;
- every active profile has a recoverable previous price list;
- all custom UOM Items have positive conversion factors;
- the legacy Selling sidebar has zero or one exact Price Group item;
- each moved hook and fixture has one planned target owner;
- no Server Script, Client Script, Scheduled Job, or integration uses an unsupported old path.

Preflight writes a reviewable report and changes no data.
Any ambiguity blocks migration.

### 11.3 Existing POS Profile Recovery Map

The old controller did not store previous price lists.
Migration must not invent those values.

For a profile already pointing to a generated Price Group list, preflight attempts to recover the previous value from Version history.
An operator must review every recovered value.

If history cannot prove a value, the operator supplies an explicit map:

```json
{
  "POS Profile Name": "Previous Price List Name"
}
```

The cutover patch validates every mapped profile and Price List.
Missing, invalid, or extra entries block migration.
The patch stores approved values in the new previous-price-list field.

### 11.4 Stage C: Coordinated Source Cutover

Deploy coordinated revisions of all four repositories while traffic remains stopped.

`selling_additional` gains:

- the three Price Group DocTypes;
- Price Group controller and form code;
- walk-in fixtures and behavior;
- ownership fields;
- Workspace and Workspace Sidebar;
- migration patches and tests.

`stock_additional` gains:

- the Item Custom Field fixture;
- Item validation;
- the scanner override;
- migration checks and tests.

`bakery_manufacturing` removes active ownership of moved features.
It keeps the manufacturing override and temporary import shims only.

`roti_ropi_pos` changes dependencies and source-contract expectations.
Its public API behavior remains unchanged.

No overlap window may serve requests.

### 11.5 Stage D: Model and Data Cutover

Use a `selling_additional` `pre_model_sync` patch for existing shell-installed sites.
The patch:

1. verifies the shell app and Module Def;
2. updates only the three exact DocType module values;
3. changes `Bakery Manufacturing` to `Selling Additional`;
4. clears DocType and module caches;
5. deletes no parent or child business rows.

Normal model sync then imports one authoritative DocType JSON copy from `selling_additional`.

Use `post_model_sync` patches to:

1. import exact-name Custom Fields;
2. mark generated Price Lists;
3. classify and mark managed Item Prices;
4. store approved previous-price-list values;
5. mark and reconcile owned POS Profiles;
6. remove the exact legacy sidebar child row;
7. clear related caches.

All patches must be idempotent.
A second run must produce no data change.

## 12. Fixture Handoff

Use exact Custom Field names in fixture filters.
Do not filter only by `fieldname`.

Target owners:

| Custom Field | Owner |
| --- | --- |
| `Item-custom_default_uom_warehouse` | `stock_additional` |
| `POS Invoice-custom_walk_in_customer_name` | `selling_additional` |
| `Sales Invoice-custom_walk_in_customer_name` | `selling_additional` |
| Price List ownership field | `selling_additional` |
| Item Price ownership field | `selling_additional` |
| POS Profile ownership fields | `selling_additional` |

Remove the bakery fixture declarations in the coordinated cutover.
Do not delete the database fields or their stored values.

## 13. Hook Handoff

Expected active providers after cutover:

| Hook | Owner |
| --- | --- |
| `erpnext.stock.utils.scan_barcode` | `stock_additional` |
| ERPNext past-order list method | `selling_additional` |
| `Serial and Batch Bundle` controller | `bakery_manufacturing` |
| `POS Invoice` controller | `roti_ropi_pos` |
| `POS Closing Entry` controller | `roti_ropi_pos` |

Remove the old bakery barcode and past-order registrations in the same release.
Tests must assert exactly one provider for each moved hook.

## 14. ERPNext Sidebar Recovery

### 14.1 Source Tree

Current ERPNext status contains unrelated user work:

- `banking/yarn.lock` is modified;
- `.codegraph/` is untracked;
- `graphify-out/` is untracked.

These paths remain untouched.

The current `erpnext/workspace_sidebar/selling.json` diff contains only:

- one 12-line Price Group child item;
- the timestamp exported by the bakery hook.

Before reverting, re-read the diff.
Abort if any additional edit appears.
If the diff still matches, reverse only those known lines.
Do not reset or restore any other ERPNext path.
Do not commit an ERPNext source change.

### 14.2 Site Database

The cleanup patch finds the ERPNext `Selling` Workspace Sidebar by exact app and title.
It searches child rows by the full legacy shape:

- parent and parent type;
- `type = "Link"`;
- `link_type = "DocType"`;
- `link_to = "Price Group"`;
- `label = "Price Group"`;
- the known child flags.

Zero matches is an idempotent no-op.
One match is deleted directly as that child row.
More than one match aborts migration.

The patch must not call `WorkspaceSidebar.save()`.
It must not replace the parent child table.
It must not alter unrelated sidebar items.
It clears the relevant sidebar cache after deletion.

## 15. Compatibility Shims

Keep lazy import shims for one compatibility release only.
They preserve supported old Python paths without registering hooks.

The preflight records all references to old paths.
Known first-party callers move in the coordinated release.
A missing target app raises an actionable import error only when a shim is used.

Remove shims in the next release after all sites pass a reference scan.

## 16. Repository Change Map

### 16.1 `stock_additional`

Create:

- normal Frappe app structure;
- module `Stock Additional`;
- exact Item fixture;
- Item validation hook;
- barcode override and resolver;
- preflight checks;
- unit, integration, hook, and migration tests;
- README and static-check configuration.

### 16.2 `selling_additional`

Create:

- normal Frappe app structure;
- module `Selling Additional`;
- three Price Group DocTypes;
- corrected Price Group controller;
- exact selling fixtures;
- Desk POS walk-in behavior;
- past-order override;
- Workspace and Workspace Sidebar;
- preflight and migration patches;
- lifecycle, concurrency, UI, hook, and migration tests;
- README and static-check configuration.

### 16.3 `bakery_manufacturing`

Keep:

- the Serial and Batch Bundle controller override;
- manufacturing tests;
- `required_apps = ["erpnext"]`;
- temporary import shims.

Remove active ownership of:

- Price Group DocTypes and implementation;
- barcode override;
- past-order override;
- moved fixtures;
- walk-in source import;
- legacy `after_migrate` hook;
- moved tests.

Do not modify the existing uncommitted sidebar prototype patch or its test.

### 16.4 `roti_ropi_pos`

Change:

- required apps;
- barcode source-contract expectations;
- ownership documentation;
- cross-app test commands.

Keep:

- API field names;
- customer validation;
- invoice persistence;
- history projection;
- dynamic scanner resolution.

## 17. Testing Strategy

Use a dedicated test site.
Do not use the active development site.

Every production behavior starts with a failing regression test.
Each test must fail for the missing or defective behavior.

### 17.1 `stock_additional`

Test:

- effective hook ownership;
- core signature compatibility;
- core delegation;
- empty custom UOM pass-through;
- stock UOM pass-through;
- valid conversion enrichment;
- missing conversion rejection;
- zero conversion rejection;
- negative conversion rejection;
- no response or row mutation after rejection;
- Item validation;
- fixture identity and value preservation.

### 17.2 `selling_additional`

Test:

- existing Price Group data after ownership transfer;
- managed Price List creation and enablement;
- managed Item Price upsert by `(item_code, uom)`;
- removal of only marked stale prices;
- preservation of manual and scoped prices;
- UOM-change cleanup;
- profile claim locking;
- cross-group claim rejection;
- outlet-removal recovery;
- disable recovery without Item Price save errors;
- delete recovery without dangling links;
- retained disabled Price List;
- absence of `force=True` cleanup behavior;
- walk-in validation for the default Customer;
- rejection for registered Customers;
- customer reset clearing;
- past-order projection without HTML replacement;
- app-owned Workspace and Sidebar;
- exact hook and fixture ownership.

### 17.3 Migration and Sidebar

Test:

- populated-site ownership transfer;
- parent and child data invariants;
- approved previous-price-list recovery;
- rejection of incomplete recovery maps;
- ambiguous Item Price rejection;
- patch idempotency;
- zero legacy sidebar item no-op;
- one legacy sidebar item deletion;
- duplicate legacy item rejection;
- preservation of unrelated sidebar child rows;
- no file change under `apps/erpnext` after migrate.

### 17.4 Cross-App Gates

Run:

- clean installs of both new apps;
- upgrade from a populated bakery-owned snapshot;
- full suites for all four apps;
- related ERPNext regression modules;
- pre-commit for all four repositories;
- clean asset builds;
- hook-provider checks with all apps installed;
- manual batch scan, Price Group, Desk POS, and Mobile POS smoke tests.

## 18. Rollout

### 18.1 Shell Release

1. Scaffold both apps.
2. Connect them to the existing GitHub repositories.
3. install them on a dedicated test site.
4. verify shell install and uninstall behavior.
5. release and install the shell tags on target sites.

### 18.2 Cutover Release

1. stop traffic and workers;
2. verify the shell apps are installed;
3. take and verify a backup;
4. run preflight;
5. review the recovery map and ambiguity report;
6. deploy coordinated revisions of all four apps;
7. reverse only the known ERPNext sidebar source leak;
8. run one site migration;
9. run post-migration invariants;
10. build assets and clear cache;
11. run full automated and manual gates;
12. reopen traffic only after all gates pass.

No commit, push, active-site install, or migration occurs without separate approval for that phase.

## 19. Rollback

Rollback before traffic reopens uses the verified backup.
Do not use app uninstall as rollback.
Uninstalling an owner app can drop its DocType tables.

Rollback steps:

1. keep maintenance mode active;
2. restore database and files;
3. restore all four app revisions;
4. restore installed-app order and built assets;
5. clear caches;
6. run the previous release smoke test;
7. reopen traffic only after verification.

After traffic reopens, prefer a forward fix.
A later restore can discard valid business transactions.

## 20. Release Gates

The cutover remains blocked unless:

1. both shell apps are installed;
2. backup and restore rehearsal pass;
3. preflight reports no unresolved ambiguity;
4. every moved DocType and fixture has one owner;
5. every moved hook has one provider;
6. every Price Group DocType belongs to `Selling Additional`;
7. all custom field values remain unchanged;
8. all POS Profiles have valid recovery state;
9. all custom UOM Items have valid conversion factors;
10. all four full app suites pass;
11. static checks and asset builds pass;
12. migration is idempotent;
13. migrate leaves Frappe and ERPNext source clean except unrelated pre-existing work;
14. intended diffs receive cross-repository review;
15. no unresolved Critical or Important finding remains.

## 21. Follow-Up Release

After all sites run one stable compatibility release:

- scan all code and site records for old Python paths;
- remove unused compatibility shims;
- remove handoff-only checks that all sites completed;
- keep migration idempotency guards;
- keep exact-one-owner and exact-one-provider tests;
- update the compatibility tag matrix;
- consider the unrelated bakery sidebar prototype in a separate approved task.

## 22. Acceptance Criteria

The extraction is complete when:

1. barcode invalid conversion data fails closed;
2. Price Group deletion creates no dangling POS Profile link;
3. Price Group lifecycle deletes no unowned Item Price;
4. profile claims cannot silently overwrite another group;
5. disabled Price Groups do not trigger Item Price save failures;
6. walk-in names apply only to the default profile Customer;
7. Price Group data and names remain unchanged;
8. all moved fields preserve existing values;
9. ERPNext's leaked sidebar source edit is removed without touching unrelated work;
10. migrate never writes into ERPNext source;
11. `selling_additional` owns its navigation;
12. `bakery_manufacturing` retains only manufacturing runtime ownership;
13. `roti_ropi_pos` keeps its public API behavior;
14. fresh-install and populated-upgrade tests pass;
15. rollback rehearsal succeeds.
