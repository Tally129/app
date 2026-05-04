# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
Build a HIPAA-aligned EMR / Wellness CRM for `natmedsol.com` (Natural Medical Solutions Wellness Center, Roswell, GA). Pixel-perfect-style aesthetic adapted from `medspa-concierge.emergent.host` to NatMedSol's deep-green / parchment / gold palette. Originally a marketing-clone; expanded into Power2Patient-style EMR including RBAC (Admin / Practitioner / Staff / Client), multi-step intake, SOAP notes, file vault, billing/POS, telehealth, inventory, time clock, secure messaging, and scheduling.

## Personas
- **Client (patient):** schedules, completes intake, views chart/labs/plan, secure-messages provider, pays bills.
- **Practitioner (Dr. Ravello):** schedule + availability, charts SOAP notes, signs off labs, telehealth, messaging, treatments, time clock.
- **Staff (front desk):** check-ins, walk-ins, POS, transactions, inventory, time clock, treatments, schedule.
- **Admin:** full access, user management, audit logs, reminders, CSV import, manual time-clock edits.

## Core Architecture
```
/app
├── backend
│   ├── audit.py          HIPAA-style audit logging middleware
│   ├── auth_utils.py     JWT, bcrypt, RBAC dependency
│   ├── models.py         Pydantic schemas (incl. Phase 4)
│   ├── server.py         FastAPI app (~2.2k lines, modularize next)
│   └── tests/test_phase4.py  Pytest covering Phase 4 (32/33 passing)
├── frontend
│   ├── src/lib/{api.js, auth.jsx}
│   ├── src/components/ui/  Shadcn library
│   └── src/pages/
│       ├── PortalLayout.jsx     Grouped sidebar (Today/Clients/Operations/Settings)
│       ├── patient/, provider/, admin/
│       └── portal/              Phase 4 pages (MyAccount, FrontDesk, PointOfSale,
│                                  Treatments, TimeClock, Inventory, Transactions,
│                                  ImportClients), Messages, Security
└── memory/{PRD.md, test_credentials.md}
```

## Tech Stack
- **Backend:** FastAPI · Motor (Mongo async) · GridFS for file vault · bcrypt + JWT · reportlab (PDF receipts) · pyotp (MFA stub)
- **Frontend:** React + React Router · Tailwind + Shadcn UI · Lucide icons · Recharts (symptom/lab trends) · Axios with refresh-token interceptor
- **Mocked integrations** (toggle-on when keys provided): SendGrid (email), Twilio (SMS), Stripe, Daily.co (telehealth)

## What's Implemented (✅)
### Phase 1 — Foundation
- JWT + refresh tokens, RBAC, MFA-ready scaffolding, audit log
- Client intake (multi-step), profile management
- SOAP notes with amendments
- Secure file uploads via GridFS
- Admin: user CRUD, role updates, audit log viewer

### Phase 2 — Scheduling & Billing
- Appointments + availability (per-practitioner)
- Reminder settings (email/SMS stubs)
- Treatment plan builder
- Invoices + Stripe stub + Chase POS mark-paid

### Phase 3 — Clinical & Comms
- Telehealth visit room (Daily.co stub w/ consent capture)
- Symptom tracker + lab values (Recharts visualization)
- Secure provider ↔ client messaging w/ unread badge

### Phase 4 — Operations (May 4, 2026) ⭐ NEW
- **Sidebar regrouped**: Today · Clients · Operations · Settings (4 personas)
- **My Account**: profile editor + password change
- **Front Desk**: today's queue, walk-in/scheduled check-in, room assignment, status workflow
- **Point of Sale**: catalog tabs (Treatments / Inventory / Custom), cart math (qty/discount/tip/tax-rate), 5 payment methods, **PDF receipt auto-download** post-checkout
- **Treatments catalog**: full CRUD with active flag, category, SKU, duration, price
- **Time Clock**: punch in/out, break tracking (multi-break per shift), 7-day total stat, admin manual edit of any shift
- **Inventory**: CRUD, manual stock adjust w/ reason/note, **auto-decrement on POS sale**, low-stock banner + stubbed SendGrid alert
- **Transactions ledger**: filter by client / payment method / search, downloadable PDF receipt per row
- **Import Clients (admin)**: CSV upload with header preview, dedupe-by-email, error report

### Quality Gates
- HIPAA "Demo Environment" red banner is permanent
- Audit-logged actions: every Phase 4 mutation
- RBAC enforced across all Phase 4 endpoints (verified: clients receive 403 on inventory/POS/treatments/transactions/time-clock-all/front-desk/import)
- Pytest suite at `/app/backend/tests/test_phase4.py` — 33 cases, 32 passing (the 1 skip = password rotation that requires resetting demo creds)

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Mocked / Pending Integrations
| Service | Status | Trigger |
|---------|--------|---------|
| SendGrid email | stub (logs `_stubbed:true`) | reminders, low-stock, password reset |
| Twilio SMS | stub | reminders |
| Stripe | stub | invoice + POS `stripe` method |
| Daily.co | stub room | telehealth visit |

User must provide API keys to flip integrations live.

## Roadmap / Backlog

### P1 — Next up
- Provider analytics dashboard (revenue per provider, no-show rate, avg visit length)
- Modularize `/app/backend/server.py` into `routers/` (auth, clients, scheduling, billing, pos, time, etc.) — file is ~2.2k lines
- Fix `<DialogContent>` accessibility warnings (add `<DialogDescription>` everywhere)
- Real Daily.co integration once `DAILY_API_KEY` provided
- Real Stripe integration with webhooks for `pos.checkout` `stripe` method

### P2 — Future
- Automated SOAP suggestions (LLM-assisted draft from intake + last visit)
- Patient PWA / mobile-optimized portal
- Recurring appointment series (e.g. weekly IV therapy)
- Inventory lots / expiration tracking
- Automated low-stock reorder workflow

### P3 — Nice-to-have
- Waitlist / cancellation auto-fill
- Treatment package bundles (buy 5, get 6th 50% off)
- Practitioner commission split on treatment sales
- Geofence / IP-restrict time-clock punches

## Known Limitations
- Demo HIPAA banner present until BAA-covered hosting + encryption-at-rest is enabled
- `TEST123` password is 7 chars (predates 8-char policy); use longer passwords for any newly created accounts.
- No multi-tenancy yet; deployment is single-clinic.

_Last updated: May 4, 2026_
