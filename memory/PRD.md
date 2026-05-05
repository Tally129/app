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

### Phase 10 — Forms & Consents + UX cleanup (May 5, 2026) ⭐ NEW
- **HIPAA red banner removed** from every page (PortalLayout, StaffLogin, TelehealthVisit, Login).
- **"36 years in practice"** copy update on Home (was 29+).
- **Admin Overview StatCards now clickable** — Clients/Users/Visit notes/Files/Appt requests/Audit each route to a list page. Two new clinic-wide drill-downs added: `/portal/admin/notes` (AdminNotesList, with provider filter + name search) and `/portal/admin/files` (AdminFilesList).
- **Front Desk KPI cards (In clinic / Walk-ins / Completed) now act as filter toggles** — write `?filter=in_clinic|walk_in|checked_out` to URL, with a visible chip + clear button.
- **Forms & Consents** new feature (admin / practitioner / staff):
  - 3 built-in templates auto-seeded: Treatment Consent, HIPAA Notice, Photo & Likeness Release.
  - **AI Transcribe** PDF/DOCX/TXT → Claude 4.5 → editable form schema (uses `pypdf` + `python-docx` for text extraction, then strict-JSON prompt to Claude via Emergent LLM key).
  - **AI Generate** from a free-text prompt.
  - In-app form builder with text/textarea/email/phone/number/date/checkbox/radio/select/signature field types.
  - Search by title, filter by category, archive (toggle active), built-ins are soft-archive only.
  - **Soft-link send** → tokenized `/forms/respond/:token` URL the patient can open without logging in. Submitted forms appear in the Submissions tab. Auto-push notification to the linked client if they are a portal user.
  - Public `FormResponder.jsx` page renders the form with a touch/mouse signature pad and validates required fields before submit.
- **Backend endpoints (Phase 10)**: `GET/POST/PUT/DELETE /api/forms/templates`, `POST /api/forms/transcribe`, `POST /api/forms/generate`, `POST /api/forms/send`, `GET /api/forms/submissions`, `GET /api/forms/submissions/{id}`, `GET /api/public/forms/{token}`, `POST /api/public/forms/{token}/submit`, `GET /api/notes/all`.
- **New deps**: `pypdf`, `python-docx`, `lxml` (added to requirements.txt).

### Phase 11 — SOAP Notes hub + Detox Protocols (May 5, 2026) ⭐ NEW
- **SOAP Notes hub** at `/portal/{admin,staff,provider}/soap`:
  - Notes tab: clinic-wide list with **filter by client + by author/provider** + free-text search.
  - Templates tab: provider/admin can create, edit, delete starter SOAP templates (subjective / objective / assessment / plan with optional visit_type 'telehealth' or 'in_person').
  - "New SOAP" dialog → pick a client + a template → S/O/A/P sections pre-fill → save attaches to that client's chart (history retained on patient profile via existing `/notes` per-client endpoint).
  - Seeded templates: 'General wellness follow-up' + 'Telehealth check-in'.
- **Protocols** at `/portal/{admin,staff,provider}/protocols`:
  - Templates tab: configurable X-week × N-treatments-per-week protocols. Built-in 'Natural Medical Solutions Detox' (4 wk × 2/wk) auto-seeded with the daily outline, recommended foods, foods-to-avoid, and lifestyle guidance from the supplied DOCX template.
  - Propose flow: provider/admin selects a client and customizes weeks/sessions → an enrollment is created with status `proposed` and a sessions grid (week × session) → web-push notification sent to the client.
  - Patient view at `/portal/patient/protocols`:
    - Awaiting acceptance section with **Accept / Decline** buttons + optional note.
    - Active section with progress bar; History section for past protocols.
    - Read-only sessions grid (provider-only check-off).
  - Per-session check-offs (provider/admin/staff): clicking a session toggles complete, stamps `completed_by_name` + timestamp; when all sessions complete, status auto-advances to `completed`.
  - Clinic-wide enrollments index with filter by **client / provider / status** + search.
- **Backend endpoints (Phase 11)**: `GET/POST/PUT/DELETE /api/soap-templates`, `GET/POST/PUT/DELETE /api/protocols/templates`, `POST /api/protocols/enrollments`, `GET /api/protocols/enrollments(?client_id|practitioner_id|status)`, `GET /api/protocols/enrollments/{id}`, `POST /api/protocols/enrollments/{id}/decision`, `POST /api/protocols/enrollments/{id}/sessions`.

### Phase 12 — Logo refresh + Protocol AI assist (May 5, 2026) ⭐ NEW
- **New brand logo** (Natural Medical Solutions emblem with leaf+banner) replaces the old SVG monogram across the entire app — Home, Login, StaffLogin, FormResponder, sidebar, favicon. White background was punched to alpha=0 so it sits cleanly on the parchment palette.
- **"36 years in practice"** copy now applied everywhere (the bio paragraph on Home was missed in Phase 10 — fixed).
- **Protocols → AI Transcribe + AI Generate** mirrors the Forms & Consents flow:
  - `POST /api/protocols/transcribe` (multipart PDF/DOCX/TXT) → Claude 4.5 → structured protocol draft (weeks, sessions/week, foods, lifestyle, supplements, daily outline).
  - `POST /api/protocols/generate` (`{prompt}`) → Claude 4.5 → drafted protocol from a free-text description.
  - Both restricted to admin+practitioner (staff/client → 403).
  - Drafts pre-fill the Protocol Template Editor for one-click save.
- Lessons: testing agent caught a 1-line missing-state regression (`useState(null)` for showAi was inserted slightly out of order; corrected).

### Phase 13 — Document Library, Push opt-in, Recordings, Forms delivery, Last-login (May 5, 2026) ⭐ NEW
- **Document Library** (`/portal/{role}/library`) — universal AI ingest. Drop a PDF/DOCX/TXT → Claude 4.5 classifies as form / protocol / soap / supplement / other → matching transcription path runs → operator clicks "Save to ..." which creates the real template in the right destination.
  - Backend: `POST /api/library/classify` (multipart), `POST/GET/DELETE /api/library/supplements`.
  - 4 LLM helpers added: `_llm_classify_document`, `_llm_form_transcribe` (existing), `_llm_protocol_transcribe` (existing), `_llm_soap_template_extract`, `_llm_supplement_extract`.
- **Push notification opt-in banner** — `<PushOptInBanner>` mounted globally. Bottom-right card shown once when `Notification.permission==='default'` and not previously dismissed. Tied to existing `ensurePushSubscription()` helper.
- **WebM telehealth recording → GridFS** — was already written; added `GET /api/visits/{appt_id}/recordings` + `GET /api/visits/{appt_id}/recordings/{file_id}` (streams from GridFS as `video/webm` with RBAC). Recording UI in TelehealthVisit.jsx already calls `POST /api/visits/{id}/recording` on stop.
- **SMS/email forms delivery** — `POST /api/forms/send` now accepts `{channel: 'link'|'email'|'sms', delivery_target}`. Stub-logs to `integration_log` (`service=sendgrid|twilio`), returns `delivery_status='sent_stub'|'skipped'`. UI: SendFormDialog has a 3-button channel selector + dynamic recipient input that auto-fills from the selected client.
- **Last-login memory** — Login + StaffLogin pre-fill email from `localStorage.nms_last_login_email`, persisted on successful sign-in.
- **`coturn` deployment doc** — `/app/COTURN_DEPLOYMENT.md` (8-section ops guide: provisioning → TLS → conf → backend env wire-up → verification → cost guidance).

### Quality Gates
- iter12: 12/12 backend pytest ✅ + 11/11 frontend UI ✅. Tester caught a `react-hooks/rules-of-hooks` regression in SendFormDialog (4-line refactor applied).
- iter11: Logo + Protocol AI 13+10/13+10 ✅
- iter10: SOAP + Protocols 22/22 ✅
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

_Last updated: May 5, 2026 (Phase 13 — Document Library + Forms delivery + Recordings)_
