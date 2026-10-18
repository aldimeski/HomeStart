# HomeStart – REST API

Interactive documentation is available at `/api/docs` (Swagger UI) while the application runs.

All endpoints except `POST /api/auth/login` require a session cookie. Every non-GET request must send
the header `X-HomeStart: 1`.

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/api/auth/login` | – | `{username, password}` → current user and settings; sets the session cookie |
| POST | `/api/auth/logout` | user | Ends the session |
| GET | `/api/auth/me` | user | Current user and settings |
| POST | `/api/users/me/password` | user | `{current_password, new_password}` |
| PUT | `/api/users/me/settings` | user | `{theme?, sidebar_collapsed?, sholink_expanded?}` |
| GET | `/api/users` | admin | List users |
| POST | `/api/users` | admin | `{username, password, role, is_active}` |
| PUT | `/api/users/{id}` | admin | `{username?, role?, is_active?}` |
| POST | `/api/users/{id}/password` | admin | `{new_password}` – reset password |
| DELETE | `/api/users/{id}` | admin | Delete user |
| GET | `/api/links` | user | Links in menu order |
| POST | `/api/links` | admin | `{title, url, icon, open_in_new_tab}` |
| PUT | `/api/links/{id}` | admin | Update link |
| DELETE | `/api/links/{id}` | admin | Delete link |
| PUT | `/api/links/order` | admin | `{ids: [...]}` – full new order |
| GET | `/api/links/{id}/embed-check` | user | `{reachable, embeddable, reason}` |
| GET | `/api/icons` | admin | Uploaded icons |
| POST | `/api/icons` | admin | multipart `file` (SVG/PNG/WebP/ICO, ≤ 256 KB) → `{icon: "upload:…"}` |
| GET | `/api/icons/{name}` | user | Icon file |
| DELETE | `/api/icons/{name}` | admin | Delete an icon that no link uses |

Errors are returned as `{"detail": "message"}` with the matching HTTP status
(401 not logged in, 403 not allowed / missing CSRF header, 409 conflict, 422 invalid input, 429 locked out).
