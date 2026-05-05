# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
Build a HIPAA-aligned EMR / Wellness CRM for `natmedsol.com` (Natural Medical Solutions Wellness Center, Roswell, GA). Pixel-perfect-style aesthetic adapted from `medspa-concierge.emergent.host` to NatMedSol's deep-green / parchment / gold palette. Originally a marketing-clone; expanded into Power2Patient-style EMR including RBAC (Admin / Practitioner / Staff / Client), multi-step intake, SOAP notes, file vault, billing/POS, telehealth, inventory, time clock, secure messaging, scheduling, and a patient PWA.

## Personas
- **Client (patient):** schedules, intake, chart/labs/plan, secure messaging, payments. Mobile PWA-installable with bottom-nav.
- **Practitioner:** schedule + availability, SOAP notes, lab review, telehealth, messaging, treatments, time clock, analytics.
- **Staff:** check-ins, walk-ins, POS, transactions, inventory, time clock, treatments, schedule.
- **Admin:** full access, user management, audit logs, reminders, CSV import, manual time-clock edits, analytics, all of the above.

## Architecture
```
/app
├── backend
│   ├── audit.py          HIPAA-style audit logging middleware
│   ├── auth_utils.py     JWT + bcrypt + RBAC dependency
│   ├── models.py         Pydantic schemas (incl. Phase 4 + analytics)
│   ├── server.py         FastAPI app (~2.3k lines — to be split into routers/)
│   └── tests/
│       ├── test_phase4.py  (33 tests, 32 passing)
│       └── test_phase5.py  (20 tests, 20 passing — analytics + telehealth + a11y + PWA)
├── frontend
│   ├── public/
│   │   ├── manifest.json
│   │   ├── service-worker.js
│   │   └── icons/icon-192.png, icon-512.png
│   ├── src/lib/{api.js, auth.jsx, Protected.jsx}
│   ├── src/components/ui/  Shadcn library
│   └── src/pages/
│       ├── PortalLayout.jsx     Grouped sidebar (Today/Clients/Operations/Settings) + mobile bottom nav for clients
│       ├── TelehealthVisit.jsx  SimplePractice/Tebra-style: consent → tech check → join → in-call → ended
│       ├── patient/, provider/, admin/
│       └── portal/              Phase 4 pages + Analytics + Messages + Security
└── memory/{PRD.md, test_credentials.md}
```

## Tech Stack
- **Backend:** FastAPI · Motor (Mongo async) · GridFS for file vault · bcrypt + JWT · reportlab (PDF receipts) · pyotp (MFA stub) · httpx (Daily.co REST) · pytest
- **Frontend:** React + React Router · Tailwind + Shadcn UI · Lucide icons · Recharts (symptom/lab trends + analytics) · Axios with refresh-token interceptor · @daily-co/daily-js (HIPAA-ready)
- **PWA:** manifest + service worker (network-first for /api to protect PHI, cache-first for static), home-screen install, mobile bottom nav

## What's Implemented (✅)
### Phase 1 — Foundation
- JWT + refresh tokens, RBAC, MFA-ready, audit log, intake, profiles, SOAP, GridFS files, admin user mgmt

### Phase 2 — Scheduling & Billing
- Appointments + availability, reminder settings, treatment plan builder, invoices + Stripe stub + Chase POS

### Phase 3 — Clinical & Comms
- Symptom tracker, lab values + Recharts visualizations, secure messaging w/ unread badge

### Phase 4 — Operations (May 4, 2026)
- Sidebar regrouped (Today/Clients/Operations/Settings)
- My Account, Front Desk (queue/walk-ins/rooms), POS (catalog + cart + 5 payment methods + auto PDF receipt), Treatments CRUD, Time Clock (punch + breaks + admin edit), Inventory (CRUD + auto-decrement + low-stock banner), Transactions ledger, Import Clients (CSV)
- All RBAC verified, 32/33 pytest passing

### Phase 5 — UX, Analytics & Telehealth (May 5, 2026) ⭐ NEW
- **Provider Analytics dashboard** (/portal/{admin,provider}/analytics): revenue total/series/by-method, appointments KPIs (no-show rate, avg duration, completed), top treatments by revenue, notes by provider, low-stock count. Window selector: 7/30/90/365 days. Recharts line + donut + horizontal-bar.
- **Telehealth redesign** modeled after SimplePractice/Tebra: consent → tech check → join → in-call → ended stages. Uses `@daily-co/daily-js` to mount Daily Prebuilt iframe with NMS theme. Stub mode when `DAILY_API_KEY` is unset.
- **Full PWA**: manifest.json (theme #2f4a3a, NatMedSol brand, shortcuts), service worker (production-only, network-first /api for PHI protection), 192/512 icons, mobile bottom nav (Home/Visits/Messages/Chart/Me) for clients.
- **Dialog a11y**: `<DialogDescription>` added on all 9 modals (FrontDesk, Treatments, Inventory ×2, PatientAppointments, Messages, ProviderSchedule ×2). Eliminates the shadcn console warning.
- 20/20 pytest pass (test_phase5.py)

### Quality Gates
- Permanent HIPAA red banner on every portal page
- Audit-logged actions on all mutations including telehealth (room/token/consent/recording)
- RBAC enforced across all endpoints (clients receive 403 on operations endpoints)
- Pytest at `/app/backend/tests/` covering 53 cases (52 passing)

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Mocked / Pending Integrations
| Service | Status | Trigger to flip live |
|---------|--------|---------|
| **Daily.co Telehealth** | stub w/ HIPAA-ready architecture | provide `DAILY_API_KEY` (BAA-tier) env var |
| SendGrid email | stub | provide `SENDGRID_API_KEY` |
| Twilio SMS | stub | provide `TWILIO_*` credentials |
| Stripe | stub | provide `STRIPE_SECRET_KEY` |

## Roadmap

### P1 — Next up
- **Modularize `/app/backend/server.py`** (~2.3k lines) into `routers/` packages — DEFERRED from this batch due to risk; estimated 30k token effort, recommend dedicated session
- Daily.co live mode: provide BAA-tier API key, then re-test in-call iframe + recording
- Optimize Analytics queries with MongoDB `$match`/`$group` aggregation pipelines (currently in-memory aggregation works for demo scale only)
- Replace N+1 user lookups in `notes_by_provider` with single `$in` query
- End-of-Day Cash Drawer report (one-click PDF: today's revenue by method, top treatments, items needing reorder)

### P2 — Future
- Automated SOAP suggestions (LLM-assisted draft from intake + last visit)
- Recurring appointment series (weekly IV therapy etc.)
- Inventory lots / expiration tracking
- Push notifications via PWA + web-push
- Provider commission split on treatment sales

### P3 — Nice-to-have
- Waitlist / cancellation auto-fill
- Treatment package bundles (buy 5, get 6th 50% off)
- Geofence / IP-restrict time-clock punches
- Multi-tenant support for additional clinic locations

## Known Limitations
- HIPAA banner present until BAA-covered hosting + encryption-at-rest is enabled
- Daily.co in stub mode (no `DAILY_API_KEY`) — telehealth UI works but no actual video transport
- `TEST123` password is 7 chars (predates 8-char policy); use longer passwords for new accounts
- Service worker only registers in production builds (intentional, smooths dev hot-reload)
- Single-tenant (one clinic); no multi-tenancy

_Last updated: May 5, 2026_
