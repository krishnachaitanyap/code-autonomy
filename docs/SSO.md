# SSO Authentication

`code-autonomy` supports three authentication modes via the `[auth].provider`
config key:

| Provider | When to use |
|---|---|
| `none` | Open access. Default. Best for local dev and POCs. |
| `oidc`  | Generic OpenID Connect — Okta, Azure AD, Keycloak, Ping. Backend-driven flow with httpOnly session cookies. |
| `adfs`  | On-prem Microsoft ADFS. Browser-driven flow with `Authorization: Bearer` headers and localStorage tokens. |

Both `oidc` and `adfs` share the same `User` model, the same role-mapping
logic, and the same admin user-management UI at `/admin/users`. They differ
only in the login flow shape and where the JWT lives in the browser.

---

## Architecture: ADFS browser-initiated flow

```
Browser/App                 Backend                          ADFS
    │                          │                              │
    │  GET /api/auth/sso/config│                              │
    │─────────────────────────►│                              │
    │  config JSON             │                              │
    │◄─────────────────────────│                              │
    │                          │                              │
    │  Browser builds authorize URL itself (client_id,        │
    │  redirect_uri, state, resource, response_mode=query,    │
    │  scope=openid). Stores state in sessionStorage.         │
    │                                                          │
    │  Redirect to authorize URL ─────────────────────────────►│
    │                          │                              │
    │  ◄────────── Redirect with ?code=... ────────────────────│
    │                          │                              │
    │  GET /api/auth/sso/callback?code=...&state=...          │
    │─────────────────────────►│                              │
    │                          │  POST /adfs/oauth2/token     │
    │                          │  (grant_type=authorization_code,
    │                          │   code, client_id, redirect_uri)
    │                          │  ── NO client_secret (public client)
    │                          │─────────────────────────────►│
    │                          │  access_token, expires_in    │
    │                          │◄─────────────────────────────│
    │                          │                              │
    │                          │  Decode SID/FirstName/LastName claims
    │                          │  from access_token (no signature verify)
    │                          │  Cache token in TokenCache (5-min buffer)
    │                          │  Upsert User row in DB
    │                          │  Issue HS256 internal JWT (sub=SID)
    │                          │                              │
    │  302 /?token=<jwt>&user=<json>                          │
    │◄─────────────────────────│                              │
    │                                                          │
    │  AuthProvider parses query, validates state from        │
    │  sessionStorage, stores in localStorage['jwt_token']    │
    │  and localStorage['user'], then history.replaceState()  │
    │  to scrub the URL.                                      │
    │                                                          │
    │  Subsequent API calls: Authorization: Bearer <jwt>      │
    │  WebSocket handshake: ws://.../stream?token=<jwt>       │
```

### Backend pieces

- **`src/services/auth_service.py`** — `AuthService` with both providers
  on the same class. The ADFS branch is gated by
  `provider == "adfs"` and exposes:
  `get_sso_config()`, `build_adfs_authorize_url(state)`,
  `exchange_code_for_token(code)`, `get_user_info(token_payload)`,
  `cache_token / get_cached_token / invalidate_token`,
  `create_internal_jwt(user_id, expires_in)`, and the high-level
  `handle_adfs_callback(code)` that orchestrates the whole pipeline.

- **`src/services/jwt_service.py`** — tiny HS256 helper module so the auth
  middleware and WebSocket route can encode/decode internal session JWTs
  without importing the full `AuthService`.

- **`src/api/routes/auth.py`** — FastAPI router with:
  - `GET /api/auth/sso/config` — public IdP config for the frontend
  - `GET /api/auth/sso/auth?state=...` — backend fallback redirect
  - `GET /api/auth/sso/callback?code=...` — browser callback (302 to `/?token=...&user=...`)
  - `POST /api/auth/sso/callback` — JSON variant for non-browser clients
  - `POST /api/auth/sso/logout?user_id=...` — invalidates server cache
  - `GET /api/auth/sso/validate?user_id=...` — cache check (ops/tests)

- **`src/api/app.py`** — `auth_middleware` reads `Authorization: Bearer`
  on every protected `/api/*` route, decodes via `jwt_service`, and
  attaches the user to `request.state.user`.

- **`src/api/routes/sessions.py`** — WebSocket route accepts `?token=...`
  on the handshake URL (browsers cannot send custom headers on WS upgrades).

- **`src/data/models.py`** — `User` model with `sid`, `first_name`,
  `last_name`, `full_name` columns for ADFS-specific claims.

### Frontend pieces

- **`webui/src/lib/auth.ts`** — `initiateSSOLogin()`, `authedFetch()`
  (Bearer-injecting fetch wrapper), `getStoredToken / getStoredUser /
  setStoredAuth / clearStoredAuth`, `withWsToken()` for WebSocket URL
  builders, and the existing user-management API calls.

- **`webui/src/lib/AuthProvider.tsx`** — top-level React context that runs
  the startup pipeline (Section 4.1): parse callback URL → store in
  localStorage → scrub URL → render children, or redirect to ADFS if no
  token and SSO is enabled.

- **`webui/src/lib/api.ts`** — typed REST client. Routes all calls
  through `authedFetch` so the Bearer header is added automatically.

---

## Setup: ADFS

### 1. Configure the Relying Party Trust in ADFS

In the ADFS Management console:

1. **Add Relying Party Trust** → Manual configuration.
2. **Display name**: `code-autonomy`
3. **Token-decryption certificate**: skip (not required for Authorization Code flow).
4. **Endpoints**: enable
   - **WS-Federation passive endpoint**: not needed
   - **OAuth 2.0 endpoint**: `https://code-autonomy.example.com/api/auth/sso/callback`
5. **Identifiers**:
   - Add the relying party identifier (this becomes `adfs_resource` in
     config — e.g. `urn:code-autonomy:api`).
6. **Issuance Authorization Rules**: Permit access to all users (or scope
   to specific AD groups).

### 2. Register the OAuth client (PowerShell on the ADFS server)

```powershell
Add-AdfsClient `
  -Name "code-autonomy" `
  -ClientId "code-autonomy-public" `
  -RedirectUri "https://code-autonomy.example.com/api/auth/sso/callback"
```

This is a **public client** (no client secret). The browser-initiated
flow does not use a client secret.

### 3. Configure claim issuance rules

In the RPT properties → **Issuance Transform Rules** → add a "Send LDAP
Attributes as Claims" rule:

| LDAP Attribute       | Outgoing Claim Type |
|----------------------|---------------------|
| Object-SID           | `SID` (required)    |
| Given-Name           | `FirstName`         |
| Surname              | `LastName`          |
| E-Mail-Addresses     | `email`             |
| Display-Name         | `name`              |
| memberOf             | `groups` (custom)   |

The `groups` claim is used for role mapping (admin / developer / viewer).
If your AD groups have CNs like `CN=code-autonomy-admins,OU=Groups,...`,
you can either:
- Configure ADFS to emit just the CN (recommended), or
- Use the full DN in `[auth].admin_groups` config.

### 4. Configure `code-autonomy`

In `config.ini`:

```ini
[auth]
provider = adfs

adfs_client_id = code-autonomy-public
adfs_authorization_url = https://adfs.example.com/adfs/oauth2/authorize
adfs_token_url = https://adfs.example.com/adfs/oauth2/token
adfs_resource = urn:code-autonomy:api
adfs_redirect_uri = https://code-autonomy.example.com/api/auth/sso/callback
adfs_frontend_url = https://code-autonomy.example.com/

admin_groups = code-autonomy-admins
developer_groups = developers, engineering

# Required: a stable HS256 signing secret
session_secret =
session_ttl_hours = 24
```

For production, set the secret via env var instead of in `config.ini`:

```bash
export AUTH_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

### 5. Install the JWT dependency

```bash
pip install 'python-jose[cryptography]>=3.3.0'
```

Add it to `requirements.txt` so every deploy picks it up.

### 6. Wire `AuthProvider` into the webui layout

Open `webui/src/app/layout.tsx` and wrap the app:

```tsx
import AuthProvider from '@/lib/AuthProvider';

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
```

---

## Setup: generic OIDC (Okta / Azure AD / Keycloak / Ping)

Use `provider = oidc` and the existing `oidc_*` config keys. The OIDC flow
uses the standard OpenID Connect discovery document, a confidential client
with a `client_secret`, and an httpOnly session cookie. See the **Enabling
SSO** section of the previous docs for the full walkthrough.

The two providers can not be active at the same time on a single
deployment — `provider` is a single value. Pick the one that matches your
IdP and stick with it.

---

## Database migration

The new `User` columns (`sid`, `first_name`, `last_name`, `full_name`) are
created automatically for fresh installs because `init_db()` calls
`Base.metadata.create_all`. For existing deployments with data already in
the `users` table, run these migrations before deploying:

### SQLite

```sql
ALTER TABLE users ADD COLUMN sid VARCHAR(256);
ALTER TABLE users ADD COLUMN first_name VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN last_name VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN full_name VARCHAR(256) NOT NULL DEFAULT '';
CREATE UNIQUE INDEX ix_users_sid ON users(sid);
```

### PostgreSQL

```sql
ALTER TABLE users
  ADD COLUMN sid VARCHAR(256),
  ADD COLUMN first_name VARCHAR(128) NOT NULL DEFAULT '',
  ADD COLUMN last_name VARCHAR(128) NOT NULL DEFAULT '',
  ADD COLUMN full_name VARCHAR(256) NOT NULL DEFAULT '';
CREATE UNIQUE INDEX ix_users_sid ON users(sid);
```

For existing OIDC users, you can backfill `sid` from `sso_subject`:

```sql
UPDATE users SET sid = sso_subject WHERE sid IS NULL AND sso_subject IS NOT NULL;
```

---

## Security trade-offs (read this before enabling ADFS)

The ADFS browser-initiated flow has three security regressions vs the
default httpOnly cookie approach. They are intentional — the spec was
designed to match an existing reference implementation — but you should
understand and document them.

### 1. Token in query string

The backend redirects the browser to `/?token=<jwt>&user=<json>` after a
successful callback. **Tokens in URLs are logged by:**

- ALB / nginx / CloudFront access logs
- CloudWatch Logs (if you log requests)
- Browser history
- Browser referrer headers (until cleared)
- Any analytics tools that capture full URLs

**Mitigation:** `AuthProvider.tsx` immediately calls
`history.replaceState()` to scrub the token from the URL bar. This
removes it from browser history but does **not** remove it from server
access logs.

**To make this safer**, configure your ALB / nginx to **strip the `token`
query param from access logs**, e.g. nginx:

```nginx
log_format scrubbed '$remote_addr - $request_method $uri ...';
# Note: $uri excludes query string, $request includes it
```

### 2. localStorage is XSS-vulnerable

Any JavaScript that runs on your origin can read `localStorage['jwt_token']`.
A single XSS bug = total session theft.

**Required mitigations:**

- **Strict Content Security Policy** — no inline scripts, no eval, no
  third-party scripts on the auth origin.
- **No `dangerouslySetInnerHTML`** anywhere user content can land.
- **Short JWT TTLs** — 1 hour matches the ADFS default and limits the
  blast radius of token theft. Re-login is automatic via the
  `authedFetch` 401 handler.
- **Subresource integrity** on any third-party CDN scripts.

If you cannot guarantee the above, switch to `provider = oidc` which uses
httpOnly cookies (immune to XSS).

### 3. CSRF protection is the frontend's job

httpOnly cookies have `SameSite=Lax` defense. Bearer tokens in
`Authorization` headers do not — but they also can't be sent
automatically by a malicious cross-origin form, so the practical CSRF
risk is lower. The bigger concern is the SSO callback itself, where the
spec uses `sessionStorage['sso_state']` to verify the state parameter
matches between the redirect and the callback. `AuthProvider.tsx` checks
this and rejects mismatches.

---

## Verification

### Smoke test (no IdP needed)

```bash
python -c "
from src.services.jwt_service import create_access_token, decode_access_token, set_secret
set_secret('test-secret')
t = create_access_token({'sub': 'user-123'}, 3600)
print('decoded:', decode_access_token(t))
assert decode_access_token(t)['sub'] == 'user-123'
print('OK')
"
```

### End-to-end against real ADFS

1. Configure `[auth].provider = adfs` and the four ADFS URLs in `config.ini`.
2. Restart `uvicorn src.api.app:app --port 8000`. Logs should say
   `SSO authentication enabled (provider=adfs)`.
3. Open `http://localhost:8000` in incognito. The browser should:
   - Call `GET /api/auth/sso/config` → receive the public config
   - Build the ADFS authorize URL with `client_id`, `redirect_uri`,
     `state`, `resource`, `response_mode=query`, `scope=openid`
   - Navigate to ADFS
4. Authenticate at the ADFS prompt.
5. ADFS redirects to `/api/auth/sso/callback?code=...&state=...`. Backend
   logs should show:
   - `Refreshing GitHub App installation token` (unrelated, can ignore)
   - `exchange_code_for_token` succeeds
   - `get_user_info` extracts SID
   - User upserted in DB
6. Browser lands on `/?token=...&user=...`. `AuthProvider` parses the
   URL, stores in localStorage, and the URL bar is scrubbed to just `/`.
7. Open dev tools → Application → Local Storage. You should see:
   - `jwt_token` — the HS256 internal JWT
   - `user` — JSON with id, email, role, etc.
8. Make any API call (e.g. open a session). The Network tab should show
   `Authorization: Bearer <jwt>` on every `/api/*` request.
9. Open a session detail page. The WebSocket connection URL should be
   `ws://localhost:8000/api/sessions/<id>/stream?token=<jwt>`.
10. Test logout: click logout in the UI. localStorage should clear, and
    the next API call should bounce you through SSO again.
11. Test cache eviction: `curl -X POST 'http://localhost:8000/api/auth/sso/logout?user_id=<sid>'`.
    Then `curl 'http://localhost:8000/api/auth/sso/validate?user_id=<sid>'`
    should return `{"valid": false, ...}`.

---

## Known limitations

- **In-memory token cache**: the `_TokenCache` in `AuthService` is
  process-local. If you run multiple uvicorn workers behind a load
  balancer, each worker has its own cache and `/sso/validate` results
  may be inconsistent. For multi-worker deployments, replace with Redis
  (out of scope for the current spec).
- **No refresh tokens**: when the JWT expires, the user is bounced
  through SSO again. ADFS supports refresh tokens but the spec doesn't
  use them.
- **No per-session WebSocket re-auth**: the WebSocket validates the JWT
  at handshake time. If the JWT expires mid-stream, the open connection
  is not torn down — only new connections are rejected.
- **Group claim parsing**: if ADFS emits groups as a single
  semicolon-delimited string instead of a multi-value claim, you'll need
  to add a custom split rule. The current code handles single-string and
  list-of-strings; everything else falls back to no groups (default
  `developer` role).
