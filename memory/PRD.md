# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
HIPAA-aligned wellness EMR for `natmedsol.com` (Natural Medical Solutions Wellness Center). Wellness office, **not** a medical practice. Single-tenant private app, not SaaS. Aesthetic adapted from medspa-concierge to NatMedSol's deep-green / parchment / gold palette.

## Personas
- **Client:** PWA-installable; schedule, intake, chart/labs/plan, secure messaging, billing. Sign in with **email or Google**.
- **Practitioner:** schedule (full EHR view), charts, telehealth (live SOAP sidebar + AI draft), messaging, treatments, time clock, analytics.
- **Staff:** front desk, POS, transactions, inventory (lots/expiry), time clock.
- **Admin:** all of the above + user mgmt, audit, CSV import, EOD reports, manual time-clock edits.

> **All roles sign in at `/login`** (no separate staff URL — the same form authenticates clients, practitioners, staff, and admins).

## Architecture
```
/app
├── backend
│   ├── audit.py / auth_utils.py / models.py / server.py (~3.1k lines, refactor pending)
│   └── tests/  test_phase{4,5,6,7,8}.py — 109/110 (1 pre-existing skip)
├── frontend
│   ├── public/{manifest.json, service-worker.js (push handlers), icons/}
│   └── src/
│       ├── components/{AddPatientWizard,…}
│       ├── lib/{api, auth, push, Protected}
│       └── pages/
│           ├── PortalLayout.jsx (auto-subscribes to push on login)
│           ├── TelehealthVisit.jsx (WebRTC + SOAP sidebar + AI draft)
│           ├── patient/, provider/, admin/, portal/
└── memory/{PRD.md, test_credentials.md}
```

## What's Implemented (✅)
### Phase 1–7 — done
JWT+RBAC+MFA+audit, intake, SOAP, GridFS files, appointments+availability, reminders, treatment plan, invoices, symptom tracker + lab Recharts, secure messaging, all of Phase 4 ops (POS/Inventory/TimeClock/FrontDesk/Treatments/Transactions/ImportClients), Phase 5 (Analytics + PWA + Telehealth UI redesign + a11y), Phase 6 (EHR Add Patient wizard + Appointments tab + self-hosted WebRTC + Cash Drawer + N+1 fix), Phase 7 (WS auth hardening + ICE config + live SOAP sidebar + auto-draft + Claude SOAP + recurring appts + lots/expiration + push infra + commissions).

### Phase 8 — Push Triggers, Google SSO, Cleanup (May 5, 2026) ⭐ NEW
- **Push notification triggers** wired to:
  - Appointment 1-hour reminder — `_appointment_reminder_loop` runs every 5 min, idempotent via `reminder_sent_at` flag
  - Daily expiring-inventory ping — `_expiring_inventory_loop` (admins/staff)
  - New secure message — invoked from `messages.create` to other thread participants
  - Low-stock on POS sale — admins/staff get a push when stock crosses threshold
  - Visit started (telehealth in_session) — pings the client to join
- **Emergent-managed Google SSO** via `POST /api/auth/google/session` exchanging `X-Session-ID` for our internal JWT. New Google accounts auto-created with role `client` and a matching Clients row. Existing email matches are linked.
- **Removed commission feature entirely** (treatments here are not commission-based). Endpoints `PUT /api/treatments/{id}/commission` + `GET /api/reports/commissions` now 404. UI button + dialog removed from Treatments page.
- **Login UX fixes** — title now "Sign in" (was "Patient Portal Sign In"), subtitle "Clients, practitioners, staff, and admins all sign in here." so staff don't wonder where to log in.
- **Critical bug fix from tester** — `AppointmentStatus` Literal extended to include `scheduled`, `arrived`, `in_session`. Previously the EHR Start-visit button + visit-started push were dead code (Pydantic 422'd). Now functional.
- **PWA push subscribe flow** — `/app/frontend/src/lib/push.js` ensures every authenticated user is subscribed (best-effort, silent failure).

### Phase 9 — Dedicated Telehealth Hub & Staff Portal (May 5, 2026) ⭐ NEW
- **Dedicated `/staff-login`** — separate dark-themed sign-in for staff/practitioners/admins (still routes back to `/login` for clients). All four roles can sign in at either URL.
- **Telehealth Hub** at `/portal/{role}/telehealth` — single-purpose page with tabs for Upcoming · Active · History · Equipment test, plus an Instant-visit dialog (provider+ only). Stat cards for Active now / Starting within 1h / Upcoming total. STUN/TURN/Browser/Push diagnostics in Equipment tab.
- **Staff Dashboard** at `/portal/staff` — front-desk-first KPIs (In clinic, Walk-ins, Completed today, Revenue), quick check-in, POS, Up Next, Time Clock, Low-stock and Expiring rails.
- **Admin Telehealth nav link** added to admin sidebar Today group.
- **Idempotent staff seed** — `frontdesk@natmedsol.local` / `FrontDesk!2345` (role=staff) auto-seeded for QA.
- **InstantVisitDialog** now uses `useNavigate` (SPA route) instead of `window.location.href` so auth context survives.
- **Carry-over fixes**: AppointmentIn + AppointmentUpdate validated to accept `status="in_session"` on both POST and PUT (regression confirmed by iter7 testing agent).

### Quality Gates
- 109/110 backend pytest pass (1 environmental skip) + 13/13 new Phase 9 pytest in `/app/backend/tests/test_phase9.py`
- iter7 testing agent: 4/4 Phase 9 carry-overs ✅, RBAC sidebar ✅, regression smoke ✅
- HIPAA red banner permanent
- RBAC verified across every endpoint
- Audit logging on all mutations

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Mocked / Pending Integrations
| Service | Status |
|---------|--------|
| **Claude Sonnet 4.5 (LLM SOAP)** | ✅ LIVE via `EMERGENT_LLM_KEY` |
| **Emergent Google SSO** | ✅ LIVE |
| **Web push (VAPID)** | ✅ LIVE — auto-subscribe + 5 trigger hooks wired |
| coturn TURN | ✅ env-var support; user deploys server |
| SendGrid email | stub |
| Twilio SMS | stub |
| Stripe | stub |

## Roadmap

### P1 — Next up
- **`server.py` modular refactor** into `routers/` — file is now ~3.1k lines (deferred 5 sessions). Its own dedicated session.
- Migrate `AppointmentStatus` from Literal to a proper Python `Enum` + DB sanitizer at startup (defense-in-depth against the recurring "Literal vs DB drift" class of bug)
- Validate `keys.p256dh` / `keys.auth` on `POST /api/push/subscribe`
- Add `_httpx` timeout = 7s on Google session exchange (currently 15s — risk of worker stall)
- Track + cancel background loops on shutdown event

### P2 — Future
- LLM-assisted intake summarizer (one-paragraph chart preview)
- iPad-optimized provider view
- Recurring appointment UI: edit-one-vs-edit-series + drag to reschedule
- FEFO (first-expiring-first-out) inventory consumption on POS

### P3 — Nice-to-have
- Push: per-device manager (revoke per browser)
- Web push for staff: shift-handoff notes, time-clock punch confirmations

## Known Limitations
- HIPAA banner stays until BAA-covered hosting + encryption-at-rest
- WebRTC needs TURN for restrictive networks (bring your own coturn)
- Service worker registers only in production builds
- `TEST123` is 7 chars — predates 8-char policy

_Last updated: May 5, 2026 (Phase 9 — Telehealth Hub + Staff Portal)_
