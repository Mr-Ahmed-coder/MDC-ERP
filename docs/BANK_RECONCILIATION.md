# Bank Reconciliation (Odoo Community 18-style)

Reconcile an imported bank statement against the bank account's book journal
lines. At `/m/bankrec` (Accounting launcher). Permission `bankrec` —
super_admin, accountant.

## Flow
1. **Import Statement** — pick a bank account, opening/closing balances, and
   upload a **CSV** or **Excel (.xlsx)** file, or paste CSV. Columns are detected
   automatically: Date, Label/Description, Ref, and Amount (or separate
   Debit/Credit). Each row becomes a statement line.
2. **Duplicate detection** — on import, any line whose date + amount + reference
   already exists for that bank account is flagged "duplicate?".
3. **Reconcile workspace** — every line shows a **suggested match** (a book
   journal line on the bank account with the same amount within a 5-day window):
   - **Auto-match all** — matches every line with a confident book counterpart.
   - **Match** / **Manual** — confirm the suggestion or pick a specific book entry.
   - **+ Payment** — for a line with no book entry, posts a balanced journal
     entry (bank account ↔ a counterpart account you choose) and marks it matched.
   - **Write-off** — for bank charges, fees or small differences, posts an
     adjusting entry to an expense/income account.
   - **Unmatch** — reverses a match and un-clears the book line.
   Matched book lines are flagged via `JournalLine.cleared`, tying into the ledger.
4. **Approval workflow** — a fully-matched statement can be marked **Reconciled**,
   then **Approved** by a super_admin or accountant. Approval records who/when and
   **locks** the statement against further edits.
5. **History** — the statement list shows each statement's bank, date, matched
   progress, difference and status.

Every action (import, match, auto-match, payment, write-off, unmatch, reconcile,
approve) is written to the **audit log**.

## Honest notes
Matching is by amount + date window against the bank account's own book journal
lines (the correct book-vs-bank approach) — it does not fuzzy-match on partner or
memo text beyond that. "Create payment" and "Write-off" post real balanced
journal entries through the shared `post_journal` helper, so they flow into the
General Ledger. The older simple manual reconciliation (`bankrecon`) is kept
alongside this as "Bank Reconciliation (Simple)".
