# HomeStart – architecture

```
Browser (Vue 3 SPA)
   │  HTTP: REST /api/*, static files
   ▼
FastAPI backend (python -m homestart, port 8000)
   ├─ config.py      homestart.ini / homestart_default.ini
   ├─ security.py    Argon2id, server-side sessions, login lockout
   ├─ api/auth.py    login, logout, current user
   ├─ api/users.py   user management (admin), own password and settings
   ├─ api/links.py   ShoLink links, order, iframe embed check
   ├─ api/icons.py   uploaded icons (SVG sanitized)
   └─ static         frontend/dist (SPA fallback to index.html)
   ▼
SQLite (WAL) – path from the ini file; schema managed by Alembic
```

## Sessions and CSRF

- Login creates a random token stored in the `homestart_session` cookie (HttpOnly, SameSite=Strict,
  Secure when served over HTTPS). The database stores only its SHA-256 digest (`sessions` table).
- A session expires after `session_timeout_minutes` of inactivity. Changing or resetting a password and
  deactivating a user end the user's other sessions.
- Every non-GET `/api/*` request must carry the header `X-HomeStart: 1`. Cross-site pages cannot send
  custom headers without CORS (which is not enabled), so forged requests are rejected.

## Login lockout

Failed logins are recorded in `login_attempts`. After `max_failed_logins` failures for the same
username and IP within `lockout_minutes`, further attempts are refused with HTTP 429 until the window
passes. An IP is also locked after four times that many failures across all usernames.

## Icons

- `mdi:<name>` — Material Design Icons. `frontend/scripts/build-mdi-icons.mjs` builds
  `/mdi-icons.json` from the `@mdi/svg` package at build time; the browser loads it lazily (≈780 KB gzip),
  so no CDN is used. Fixed menu icons are bundled directly from `@mdi/js`.
- `upload:<32 hex>.<ext>` — uploaded files in `icons_dir`. Type is detected from content; SVG is rebuilt
  from an allowlist of elements and attributes (no scripts, event handlers, external references).

## Embedding check

Cross-origin iframes fire `load` even when the target refuses to be framed, so the browser cannot detect
it reliably. `GET /api/links/{id}/embed-check` lets the server request the stored link URL and inspect
`X-Frame-Options` and CSP `frame-ancestors`. Only URLs saved by an administrator are fetched. The frontend
also shows the message if the frame has not loaded within 15 seconds.

## Database tables

| Table | Purpose |
|---|---|
| `users` | id, username (unique), password_hash, role, is_active, created_at, last_login |
| `user_settings` | user_id, theme (system/light/dark), sidebar_collapsed, sholink_expanded |
| `sessions` | token_hash, user_id, created_at, last_seen |
| `links` | id, created_by, title, url, icon, open_in_new_tab, sort_order |
| `login_attempts` | id, username, ip, success, created_at |
