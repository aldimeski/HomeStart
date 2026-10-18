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
| GET | `/api/tasmota/devices` | user | `{mqtt_connected, devices: [...]}` with live state |
| POST | `/api/tasmota/devices` | admin | `{host, port, name?, group_name?}` – manual add, tests the connection |
| GET | `/api/tasmota/devices/{id}/status` | user | One device with live state |
| PUT | `/api/tasmota/devices/{id}` | admin | `{name, group_name, relay_names?}` – `relay_names` by relay position, empty = device name, omitted = unchanged |
| DELETE | `/api/tasmota/devices/{id}` | admin | Remove device |
| POST | `/api/tasmota/devices/{id}/power` | user | `{channel, action: on\|off\|toggle}` → device after confirmation; 423 if the switch is locked |
| PUT | `/api/tasmota/devices/{id}/lock` | admin | `{channel, locked}` – lock or unlock a switch |
| POST | `/api/tasmota/refresh` | user | Ask all devices for current state (answers arrive over the WebSocket) |
| POST | `/api/tasmota/scan` | admin | HTTP scan of the subnet → `{subnet, found, new, auth_required}` |
| GET | `/api/tasmota/credentials` | admin | `{username, has_password}` (the password is never returned) |
| PUT | `/api/tasmota/credentials` | admin | `{username, password?}` – omitted password keeps the stored one |
| DELETE | `/api/tasmota/credentials` | admin | Remove the shared Tasmota login |
| WS | `/ws/tasmota` | user | Live device updates: `snapshot`, `device`, `removed`, `mqtt` messages |
| WS | `/ws/tasmota/console/{id}` | user | Device console: `hello`, `source`, `lines`, `reset`; send `{"type":"command","command":"Status 0"}` (admin only) |

Errors are returned as `{"detail": "message"}` with the matching HTTP status
(401 not logged in, 403 not allowed / missing CSRF header, 409 conflict or device offline, 422 invalid input,
423 switch locked, 429 locked out, 503 MQTT not connected, 504 device did not respond).
