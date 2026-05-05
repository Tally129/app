# Emergent Auth Testing Playbook (NatMedSol)

## Test Identity
Test Google account: any real Google account (Emergent Auth handles the OAuth proxy).

## Setup
1. Click "Sign in with Google" on /login
2. Complete Google OAuth → returns to `${origin}/login#session_id=...`
3. Frontend AuthCallback exchanges the session_id with our backend at POST /api/auth/google/session
4. Backend calls `https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data` with `X-Session-ID`
5. Backend matches user by email (or auto-creates with role='client'), issues our internal JWT, sets httpOnly session_token cookie

## Backend curl test
```bash
curl -X POST $BACKEND_URL/api/auth/google/session -H "X-Session-ID: <id-from-fragment>"
# returns {access_token, refresh_token, user}
```

## Frontend test
1. Visit /login → click "Continue with Google"
2. After redirect, expect to land on /portal/{role}
3. Verify localStorage has `nms_at` set
4. Logout via sidebar → should clear cookie + JWT

## Notes
- Existing JWT login at /api/auth/login still works for staff/admin/practitioner without Google.
- Google sign-in defaults new accounts to role='client'.
- Admins can promote roles in Users & Roles.
