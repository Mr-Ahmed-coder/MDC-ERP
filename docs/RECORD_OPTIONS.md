# Record Options: Add, Edit, Archive, Restore, and Delete

## Purpose

The ERP now provides a common lifecycle for records. Authorized staff may continue to add and edit records through the existing module screens. Archive and restore actions are available through **Record Options** and preserve an audit snapshot. Hard deletion is restricted to non-protected records and always requires a reason.

Open `/record-options` or the **Record Options** module to review archived records and restore eligible entries.

## Lifecycle rules

| Action | Behavior |
|---|---|
| Add | Creates a new record through the owning module’s validated form. |
| Edit | Updates an existing record through the owning module and retains ordinary audit history. |
| Archive | Marks records with an `active` field inactive where supported and records the actor, time, reason, and serialized snapshot in `record_archive`. |
| Restore | Re-enables an archived record where the original model still exists and records the restoring actor and time. |
| Delete | Permanently removes only non-protected records after a reason is supplied. |
| Cancel/void | Use the owning financial or clinical workflow instead of deletion when the record has history or downstream effects. |

> Invoices, invoice lines, payments, laboratory orders, radiology orders, consultations, journal entries, journal lines, audit events, and archive records are protected from hard deletion. Archive or cancel them through their domain workflow.

## Permissions

The `record_options` permission is available to `super_admin`, `it_admin`, `branch_manager`, `accountant`, and `auditor`. Module-level permissions and branch row scope still apply to the underlying record screens. Grant this permission only to staff who understand the consequences of restoring or deleting operational data.

## Operational requirements

Run `flask --app wsgi db upgrade` before enabling the feature on an existing deployment. This applies the `record_archive` table migration. Review `flask --app wsgi audit-finance` after lifecycle actions and before closing a financial period. Keep backups and test restoration before performing bulk cleanup.

## API and integration guidance

External integrations should use domain endpoints and stable identifiers. They should not directly delete database rows. If an integration needs a deactivation function, call the owning module’s archive action and record a source reference and reason in the audit trail.
