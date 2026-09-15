# MDC Diagnostic ERP — User Manual

**Version 10.0 candidate** · For reception, cashiers, laboratory, radiology, and clinical staff.

---

## 1. Signing in

Open the ERP address in your browser and enter your username and password. On first login you must set a new password. If you forget it, ask an administrator to reset it — passwords cannot be recovered, only reset.

Your **role** decides what you can see and do. You will only be shown the menus relevant to your work.

---

## 2. Getting around

| Element | Where | What it does |
|---------|-------|--------------|
| **Sidebar** | Left | All modules, grouped (Patients, Laboratory, Radiology, Accounting, …). |
| **Global search** | Top bar | Type a name, phone, MRN, or a document number (INV-, RCT-, LAB-, RAD-) and press Enter. A single exact match opens the record directly. |
| **Breadcrumbs** | Below top bar | Shows where you are; click any level to go back. |
| **★ Favorites** | Top bar | Star the current page to pin it; open the star menu to jump to pinned pages. |
| **🕐 Recently viewed** | Top bar | The records you opened most recently. |
| **🔔 Notifications** | Top bar | Events relevant to your role (payments, reports ready, low stock…). |
| **Dark mode** | Top bar | Toggle light/dark for comfortable viewing. |

The interface is mobile-friendly — on a phone the sidebar collapses into a menu button.

---

## 3. The core workflow

The system is built around one clean patient journey. After each step, a green **Next step** banner appears and takes you straight to the next action — you never have to hunt for the next page.

```
Patient Registration → Doctor Request → Invoice → Payment → Laboratory / Radiology → Report
```

### 3.1 Register a patient
**Patients → New.** Enter name, gender, phone, and any ID. On save you land directly on the **patient hub**, where a Next step banner suggests **Create Invoice**. The patient's MRN is generated automatically.

### 3.2 Create an invoice / order tests
From the patient hub choose **Create Invoice** (or the **+Invoice / +Laboratory / +Radiology** action buttons). Add services; the totals calculate automatically. Ordering a lab or radiology service creates the matching order.

### 3.3 Register payment
On an unpaid invoice the Next step banner reads **Register Payment**. Enter the amount and method (Cash, Card, Mobile Money — Sahal / EVC Plus / e-Dahab — or Credit/Insurance). The system will not let you take more than the outstanding balance and shows a clear message if you try.

### 3.4 Laboratory / Radiology
Once an invoice is paid, its banner reads **Proceed to Laboratory** or **Proceed to Radiology** and links straight to the order.
- **Laboratory:** collect the sample, enter results, then **Approve**. Approved results can be printed with a digital signature.
- **Radiology:** enter technique, findings, and impression, then finalise. The report prints on the clinic's structured template with the radiologist's signature block.

### 3.5 Report
Approved lab and radiology reports can be printed or handed to the patient. Every printed document carries a verification barcode/QR and a digital signature line.

---

## 4. The patient hub

Opening any patient shows one screen with everything about them:

- **Smart buttons** with live counts: Invoices, Payments, Laboratory, Radiology, Reports, Accounting, Doctor Requests, Appointment.
- **Related Records** — one click to each linked record type.
- **Activity Timeline** — every event (registration, requests, invoices, payments, results, prints) with who did it and when.
- **Next step** — the single most useful next action for this patient.

---

## 5. Working with lists

Every list (patients, invoices, orders, …) supports:

- **Quick search** — the search box filters as you type.
- **Sorting** — click a column header to sort; click again to reverse.
- **Filtering** — status and date-range filters above the table.
- **Pagination** — large lists are paged for speed.
- **CSV export** — the **⭳ CSV** button exports exactly what is on screen.

---

## 6. Printing

Printed documents (invoices, receipts, vouchers, lab and radiology reports) use clean, professional layouts with the clinic's branding, a reference number, a scannable barcode/QR for verification, and a digital signature block naming the staff member and the date.

---

## 7. Notifications

The 🔔 bell shows events meant for your role, for example:

| Event | Who is notified |
|-------|-----------------|
| Payment received | Cashier, Accountant, Branch Manager |
| Report completed | Reception, Lab Technician, Radiologist |
| Low inventory | Lab Technician, Storekeeper, Admin |
| New referral | Reception |

Open a notification to jump to the related record; mark items as read once handled.

---

## 8. Tips

- Use **global search** as your fastest way to open anything — it understands names, phone numbers, MRNs, and document numbers.
- **Star** the pages you use every day so they are one click away.
- Follow the green **Next step** banner — it always points to the correct next action and keeps the workflow moving with the fewest clicks.
- If a message says you don't have permission, your role doesn't include that action — ask an administrator if you believe you need it.
