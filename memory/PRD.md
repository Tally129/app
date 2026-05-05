# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
HIPAA-aligned wellness EMR for `natmedsol.com` (Natural Medical Solutions Wellness Center). NOT a medical practice — wellness office. Pixel-style aesthetic adapted from medspa-concierge to NatMedSol's deep-green / parchment / gold palette. Single-tenant, private app for one business — not a SaaS.

## Personas
- **Client (patient):** PWA-installable; schedule, intake, chart/labs/plan, secure messaging, billing.
- **Practitioner:** schedule, charts, telehealth, messaging, treatments, time clock, analytics.
- **Staff:** front desk, POS, transactions, inventory, time clock, treatments.
- **Admin:** all of the above + user mgmt, audit, CSV import, EOD reports, manual time-clock edits.

## Architecture
```
/app
├── backend
│   ├── audit.py / auth_utils.py / models.py / server.py (~2.5k lines, refactor pending)
│   └── tests/
│       ├── test_phase4.py (33 tests · 32 passing)
│       ├── test_phase5.py (20 tests · 20 passing)
│       └── test_phase6.py (17 tests · 17 passing)
├── frontend
│   ├── public/{manifest.json, service-worker.js, icons/}
│   └── src/
│       ├── components/{AddPatientWizard,…}
│       ├── lib/{api, auth, Protected}
│       └── pages/
│           ├── PortalLayout.jsx (grouped sidebar + mobile bottom-nav)
│           ├── TelehealthVisit.jsx (self-hosted WebRTC)
│           ├── patient/, provider/, admin/
│           └── portal/ (FrontDesk, POS, Treatments, Inventory, Transactions, TimeClock,
│                       MyAccount, ImportClients, Analytics, Messages, Security)
└── memory/{PRD.md, test_credentials.md}
```

## Tech Stack
- **Backend:** FastAPI · Motor · GridFS · bcrypt + JWT · reportlab (PDFs) · WebSocket signaling for telehealth · pyotp (MFA stub)
- **Frontend:** React + React Router · Tailwind + Shadcn UI · Lucide · Recharts · native `RTCPeerConnection` + `MediaRecorder` (no Daily.co/SDK) · PWA (manifest + service worker)

## What's Implemented (✅)
### Phase 1–3 (Foundation, Scheduling/Billing, Clinical/Comms) — done
JWT+RBAC+MFA+audit, intake, SOAP, GridFS files, appointments+availability, reminders, treatment plan, invoices, telehealth (now self-hosted), symptom tracker + lab Recharts, secure messaging.

### Phase 4 — Operations
Sidebar regrouped, My Account, Front Desk, POS (with PDF receipt), Treatments CRUD, Time Clock (breaks + admin edit), Inventory (auto-decrement + low-stock), Transactions ledger, CSV Import.

### Phase 5 — UX, Analytics, Telehealth UI
Provider Analytics dashboard (revenue trend/donut, top treatments, no-show rate, avg duration, low-stock count, 7/30/90/365 windows). Full PWA (manifest + SW + 192/512 icons + mobile bottom nav for clients). Dialog `<DialogDescription>` a11y across all 9 modals.

### Phase 6 — EHR-style upgrades (May 5, 2026) ⭐ NEW
- **N+1 fix** in `/api/analytics/overview` `notes_by_provider` (single `$in` lookup)
- **End-of-Day Cash Drawer PDF** report at `/api/reports/eod-cash-drawer`: revenue by method, total, drawer reconciliation worksheet, top items today, low-stock list. Admin/staff button on Transactions page.
- **EHR-style Add Client wizard** — 4-step modal (Demographics → Contact → Wellness profile → Preferences & consent) with auto-MRN `NMS-{6 hex}`, extended client fields (pronouns, gender_identity, language, marital_status, alt_phone, primary_concern, wellness_goals, current_supplements, dietary_restrictions, allergies, comms_pref, consent flags). MRN column on patient table.
- **EHR-style Appointments tab** (`/portal/provider/appointments`) — Day/Week views, color-coded by 6-state workflow (scheduled → arrived → in_session → completed / no_show / cancelled), 8a–7p hour grid, click-to-create dialog, side drawer with workflow buttons + jump to telehealth + chart link, "Up next" strip.
- **Self-hosted WebRTC telehealth** (no Daily.co, no SDK fees, fully under-control):
  - Backend: WebSocket `/api/ws/visit/{appt_id}` for SDP/ICE/chat relay, `/api/visits/{id}/chat` history, `/api/visits/{id}/recording` GridFS upload
  - Frontend: native `RTCPeerConnection` + STUN, mic/cam/screen-share toggles, in-call chat sidebar (`MessageSquare` icon → `chat-input` + `chat-send`), recording via `MediaRecorder` (provider-only) → uploaded WebM to GridFS, "waiting for client" overlay until peer joins
  - Stages: loading → consent (clients only) → tech check → in-call → ended
  - HIPAA red banner stays visible
- **Bug fixes** caught by tester: `decode_token` kwarg removed in WS handler, Radix `<SelectItem value="">` replaced with `__custom__`, `visit_mode` literal aligned to `in_person`/`telehealth`

### Quality Gates
- 70/70 backend pytest (Phase 1–6)
- HIPAA red banner permanent
- RBAC verified across every endpoint (clients receive 403 on operations)
- Audit logging on all mutations including telehealth WS join/leave + recording uploads

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Known Mocks (require keys to flip live)
| Service | Status |
|---------|--------|
| SendGrid email | stub (logs `_stubbed:true`) |
| Twilio SMS | stub |
| Stripe | stub |
| ~~Daily.co~~ | **REMOVED** — replaced by self-hosted WebRTC |

## Roadmap

### P1 — Next up
- **`server.py` modular refactor** into `routers/{auth, clients, scheduling, billing, pos, time, telehealth, messaging, admin, analytics, reports}.py` — file is now ~2.5k lines, deferred 3 sessions
- **WS auth hardening** — replace JWT-in-URL with one-shot signed handshake token (tokens currently leak into proxy access logs)
- **Optional `coturn` self-hosted TURN server** for clients behind strict NATs (Google STUN only covers ~85-90% of networks)
- **Visit summary auto-draft** — when call ends, prefill SOAP `subjective` from in-call chat transcript
- **In-call SOAP sidebar** for the provider during the visit (auto-saves)

### P2 — Future
- LLM-assisted SOAP suggestions (intake + last visit context)
- Recurring appointment series (weekly IV therapy etc.)
- Inventory lots / expiration tracking
- Web-push notifications via PWA
- Provider commission split on treatment sales
- Geofence / IP-restrict time-clock punches

### P3 — Nice-to-have
- Waitlist / cancellation auto-fill
- Treatment package bundles
- Multi-tenant support (deferred — single-tenant is the explicit user requirement)

## Known Limitations
- HIPAA banner stays until BAA-covered hosting + encryption-at-rest enabled
- WebRTC requires a TURN server for restrictive networks (currently STUN-only)
- Service worker only registers in production builds (intentional)
- `TEST123` is 7 chars — predates 8-char policy

_Last updated: May 5, 2026 (Phase 6)_
