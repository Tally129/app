# Natural Medical Solutions — Wellness EMR / CRM

## Original Problem Statement
HIPAA-aligned wellness EMR for `natmedsol.com` (Natural Medical Solutions Wellness Center). Wellness office, NOT a medical practice. Single-tenant, private app for one business — not a SaaS. Aesthetic adapted from medspa-concierge to NatMedSol's deep-green / parchment / gold palette.

## Personas
- **Client:** PWA-installable; schedule, intake, chart/labs/plan, secure messaging, billing.
- **Practitioner:** schedule, charts, telehealth (with live SOAP sidebar + AI draft), messaging, treatments, time clock, analytics.
- **Staff:** front desk, POS, transactions, inventory (lots/expiry), time clock.
- **Admin:** all the above + user mgmt, audit, CSV import, EOD reports, commission split, manual time-clock edits.

## Architecture
```
/app
├── backend
│   ├── audit.py / auth_utils.py / models.py / server.py (~2.9k lines, refactor pending)
│   └── tests/
│       ├── test_phase4.py (33 tests · 32 passing)
│       ├── test_phase5.py (20 tests · 20 passing)
│       ├── test_phase6.py (17 tests · 17 passing)
│       └── test_phase7.py (28 tests · 28 passing) ⭐
├── frontend
│   ├── public/{manifest.json, service-worker.js (push handlers), icons/}
│   └── src/
│       ├── components/{AddPatientWizard,…}
│       ├── lib/{api, auth, Protected}
│       └── pages/
│           ├── PortalLayout.jsx
│           ├── TelehealthVisit.jsx (WebRTC + SOAP sidebar + AI draft)
│           ├── patient/, provider/, admin/, portal/
└── memory/{PRD.md, test_credentials.md}
```

## Tech Stack
- **Backend:** FastAPI · Motor · GridFS · bcrypt + JWT · reportlab · WebSocket signaling · pyotp · **emergentintegrations (Claude Sonnet 4.5)** · pywebpush
- **Frontend:** React + React Router · Tailwind + Shadcn UI · Lucide · Recharts · native `RTCPeerConnection` + `MediaRecorder` · PWA (manifest + SW)

## What's Implemented (✅)
### Phase 1–6 — done
JWT+RBAC+MFA+audit, intake, SOAP, GridFS files, appointments+availability, reminders, treatment plan, invoices, symptom + lab Recharts, secure messaging, all of Phase 4 ops (POS/Inventory/TimeClock/FrontDesk/Treatments/Transactions/ImportClients), Phase 5 (Analytics + PWA + Telehealth UI redesign + a11y), Phase 6 (EHR Add Patient wizard + Appointments tab + self-hosted WebRTC + Cash Drawer + N+1 fix).

### Phase 7 — Security & Advanced Telehealth (May 5, 2026) ⭐ NEW
- **WS auth hardening** — JWT removed from URL; new `POST /api/visits/{id}/ws-ticket` issues a **single-use ticket** (60s TTL, expireAfter index). WebSocket accepts `?ticket=...` (preferred) or `?token=...` (legacy fallback)
- **coturn TURN env-var support** — backend `GET /api/webrtc/config` exposes `iceServers`. STUN by default; if `TURN_URL`/`TURN_USERNAME`/`TURN_PASSWORD` env are set, the entry is included automatically (frontend reads it). Deploy your own coturn anywhere and just point env vars
- **In-call provider SOAP sidebar** — toggleable panel, 4 fields (S/O/A/P), auto-saves every 5s to `/api/visits/{id}/live-soap`. Buttons: "From chat" (rule-based draft from chat transcript), **"AI draft"** (Claude Sonnet 4.5 via `EMERGENT_LLM_KEY`), "Save to chart" (writes a real visit note)
- **Auto-draft from chat transcript** — `POST /api/visits/{id}/auto-draft` returns SOAP-shaped JSON stitched from messages
- **LLM-assisted SOAP draft** — `POST /api/visits/{id}/llm-soap` with intake + last note + chat → Claude Sonnet 4.5 → strict JSON SOAP draft
- **Recurring appointments** — `POST /api/appointments/{id}/recurrence` (weekly/biweekly/monthly using `relativedelta`); `DELETE /api/appointments/series/{id}` cancels future series instances
- **Inventory lots & expiration** — `POST /api/inventory/{id}/lots` (lot_number, qty, expires_on, note), increments stock; `GET /api/inventory/expiring?days=60` returns items needing rotation. UI banner on Inventory page
- **Commission split** — `PUT /api/treatments/{id}/commission` (admin sets per-practitioner %), `GET /api/reports/commissions?days=30` returns per-practitioner earnings from POS treatment lines
- **Web push (VAPID)** — `GET /api/push/public-key`, `POST /api/push/subscribe|unsubscribe`. Service worker has `push` + `notificationclick` handlers. **Infrastructure only — no broadcast triggers wired yet**
- **Bug fixed by tester** (HIGH): `cancel_series` wrote British "cancelled" → AppointmentOut Literal expects American "canceled" → 500 on every list endpoint. Fixed + 15 corrupt rows repaired.
- **Improvements applied after testing**: TTL index on `ws_tickets`, `relativedelta`-based monthly recurrence, default `visit_mode` aligned to `in_person`

### Quality Gates
- 98/98 backend pytest pass (Phase 1–7)
- HIPAA red banner permanent
- RBAC verified across every endpoint
- Audit logging on all mutations including telehealth WS join/leave + recording uploads + commission edits + recurrence creation

## Test Credentials
See `/app/memory/test_credentials.md`. Primary: `tallyravello@gmail.com` / `TEST123` (admin).

## Mocked / Pending Integrations
| Service | Status |
|---------|--------|
| **Claude Sonnet 4.5** | ✅ LIVE via `EMERGENT_LLM_KEY` |
| coturn TURN | ✅ env-var support; user deploys server, sets `TURN_URL/USER/PASS` |
| Web push | ✅ VAPID infra + SW; broadcast triggers not wired |
| SendGrid email | stub |
| Twilio SMS | stub |
| Stripe | stub |

## Roadmap

### P1 — Next up
- **`server.py` modular refactor** into `routers/{auth, clients, scheduling, billing, pos, time, telehealth, messaging, admin, analytics, reports, push}.py`. File is now ~2.9k lines; **deferred 4 sessions** — needs a dedicated session
- **Wire push notification triggers** on: appointment reminders (1h before), new secure message, low-stock + expiring inventory alerts, visit started by provider
- Switch `cancelled`/`canceled` to a proper `AppointmentStatus` enum (defense-in-depth against the Phase 7 spelling regression)
- Robustify LLM JSON parser (strip ```json``` code fences before regex)
- Validate `keys.p256dh` / `keys.auth` on `/push/subscribe`

### P2 — Future
- Recurring appointments UI: edit-one-vs-edit-series, drag to reschedule
- Inventory lot consumption strategy (FEFO — first-expiring-first-out) on POS
- Provider commission paystub PDF
- LLM-assisted intake summarizer (one-paragraph chart preview)
- In-call screen-recording quality settings
- iPad-optimized provider view

### P3 — Nice-to-have
- Web push: client device manager (revoke per device)
- Multi-tenant support (deferred — single-tenant per user)

## Known Limitations
- HIPAA banner stays until BAA-covered hosting + encryption-at-rest enabled
- WebRTC needs TURN for restrictive networks; bring-your-own coturn
- Service worker registers only in production builds
- `TEST123` is 7 chars — predates 8-char policy

_Last updated: May 5, 2026 (Phase 7)_
