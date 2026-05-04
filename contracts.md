# NatMedSol HIPAA-Aligned EMR — Phase 1 Contracts

## 🚨 Compliance Posture
Code is **HIPAA-READY** (technical safeguards in place) but deployment is **NOT HIPAA-COMPLIANT** until:
- Migrated to HIPAA-eligible cloud (AWS/GCP with signed BAA)
- BAAs signed with MongoDB Atlas, SendGrid, Twilio, hosting
- KMS encryption-at-rest enabled
- Pen-testing + workforce training + risk assessment complete

A persistent "DEMO — do not enter real PHI" banner is shown in every portal view.

## Roles
`admin`, `practitioner`, `staff`, `client`

## 🧬 Data Model (MongoDB collections)

### users
```
{ id, email (unique), password_hash, role, full_name, phone,
  mfa_enabled, mfa_secret, is_active, created_at, last_login_at }
```

### clients
```
{ id, user_id, dob, sex, address, emergency_contact,
  assigned_practitioner_id, intake_completed, created_at }
```

### intake_forms
```
{ id, client_id, sections: {demographics, health_history, symptoms, lifestyle, consent},
  signed_at, completed_at }
```

### visit_notes (SOAP, append-only)
```
{ id, client_id, practitioner_id,
  subjective, objective, assessment, plan,
  created_at, amendments: [{author_id, content, ts}] }
```

### files (GridFS + metadata doc)
```
{ id, gridfs_id, filename, mime, size, category (lab|intake|image|doc),
  client_id, uploaded_by, created_at }
```

### audit_logs (immutable)
```
{ id, user_id, action, resource_type, resource_id, ip, user_agent,
  metadata, ts }
```

### login_history
```
{ id, user_id, ip, user_agent, success, ts }
```

### appointment_requests (public, from marketing)
### vip_list (public, from marketing)

## 🔑 API (all prefixed with `/api`)

### Public (no auth)
- `POST /public/appointment-request`
- `POST /public/vip-signup`

### Auth
- `POST /auth/register` (client self-register → role=client)
- `POST /auth/login` → `{access_token, refresh_token, user}`
- `POST /auth/refresh`
- `POST /auth/logout`
- `GET /auth/me`
- `POST /auth/mfa/setup` → `{secret, qr_data_url}`
- `POST /auth/mfa/verify` `{token}`
- `POST /auth/mfa/disable`

### Clients (role-gated)
- `GET /clients` → practitioner/admin/staff
- `GET /clients/:id` → self OR practitioner/admin/staff
- `POST /clients` (staff/admin creates)
- `PUT /clients/:id`

### Intake (self OR practitioner)
- `POST /intake` (client saves their intake)
- `GET /intake/:client_id`

### SOAP Notes (practitioner only; clients can read their own)
- `GET /notes?client_id=...`
- `POST /notes`
- `POST /notes/:id/amend` (append amendment, never overwrite)

### Files (role-gated)
- `POST /files/upload` multipart → GridFS
- `GET /files/:id/download` (signed short-lived token)
- `GET /files?client_id=...`
- `DELETE /files/:id` (soft, admin only)

### Dashboard
- `GET /dashboard/stats` → role-scoped counts

### Admin
- `GET /admin/audit?limit=&user_id=&action=`
- `GET /admin/users`
- `POST /admin/users` (create practitioner/staff)
- `PUT /admin/users/:id/role`

## 🔒 Security
- `bcrypt` (passlib) password hash
- JWT HS256; access 15m; refresh 7d; refresh blacklist on logout
- Auto-logout idle 15min client-side
- MFA: TOTP (pyotp) — optional per-user, required for practitioner/admin roles
- Every privileged request → AuditLog
- RBAC via `require_roles(...)` dependency
- Files: signed short-TTL download URLs, no public paths
- PHI-free payment/SMS templates

## 🎭 Frontend Routes
Existing marketing preserved: `/`, `/request-appointment`, `/signup`, `/login`

New portal (after login):
- `/portal` — role-based redirect
- `/portal/patient` — dashboard (appts, intake status, labs, messages)
- `/portal/patient/intake` — multi-step intake
- `/portal/patient/labs`
- `/portal/provider` — dashboard (patient list, today)
- `/portal/provider/patients/:id` — full chart (profile, intake, notes, labs, files)
- `/portal/provider/patients/:id/note/new` — SOAP form
- `/portal/admin` — audit + users
- `/portal/admin/audit`
- `/portal/admin/users`

## 🔌 Integrations (stubbed with env vars)
- **Stripe**: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` — logged-only calls for now
- **Chase POS**: manual "Mark Paid in POS" workflow, records method=`chase_pos_manual`
- **SendGrid**: `SENDGRID_API_KEY`, `SENDGRID_FROM` — logged-only
- **Twilio**: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` — logged-only

All live stubs return success but write a `_stubbed: true` entry to `integration_log` collection.

## Phase 2 / 3 (not in this build)
appointments calendar UX, treatment plan builder, messaging UI, symptom trends, lab visualization, Stripe auto-bill memberships, SMS/email reminder cron.
