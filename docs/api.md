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
| DELETE | `/api/icons/{name}` | admin | Delete an icon that no link, device or switch uses |
| GET | `/api/tasmota/devices` | user | `{mqtt_connected, devices: [...]}` with live state |
| POST | `/api/tasmota/devices` | admin | `{host, port, name?, group_name?}` – manual add, tests the connection |
| GET | `/api/tasmota/devices/{id}/status` | user | One device with live state |
| PUT | `/api/tasmota/devices/{id}` | admin | `{name, group_name, icon?, relay_names?, relay_icons?}` – lists by relay position; empty name = device name; omitted = unchanged; `icon` null/"" removes it |
| DELETE | `/api/tasmota/devices/{id}` | admin | Remove device |
| POST | `/api/tasmota/devices/{id}/power` | user | `{channel, action: on\|off\|toggle}` → device after confirmation; 423 if the switch is locked |
| POST | `/api/tasmota/devices/{id}/zigbee/{short}/power` | user | `{action: on\|off\|toggle}` for a Zigbee light (`short` like `0x6D57`) → bridge after the device's report |
| PUT | `/api/tasmota/devices/{id}/zigbee/join` | admin | `{enabled}` – open Zigbee pairing for 60 s, or close it |
| POST | `/api/tasmota/devices/{id}/zigbee/map` | admin | Start a Zigbee network map scan; results arrive over the WebSocket |
| PUT | `/api/tasmota/devices/{id}/lock` | admin | `{channel, locked}` – lock or unlock a switch |
| POST | `/api/tasmota/refresh` | user | Ask all devices for current state (answers arrive over the WebSocket) |
| POST | `/api/tasmota/scan` | admin | HTTP scan of the subnet → `{subnet, found, new, auth_required}` |
| GET | `/api/tasmota/credentials` | admin | `{username, has_password}` (the password is never returned) |
| PUT | `/api/tasmota/credentials` | admin | `{username, password?}` – omitted password keeps the stored one |
| DELETE | `/api/tasmota/credentials` | admin | Remove the shared Tasmota login |
| GET | `/api/skoda/vehicles` | user | `{account: {connected, username, last_sync, last_error}, vehicles: [...]}` from the cache |
| PUT | `/api/skoda/account` | user | `{username, password}` – signs in to MyŠkoda, stores the login encrypted, loads the vehicles |
| DELETE | `/api/skoda/account` | user | Sign out: deletes the login, token and saved vehicle data |
| POST | `/api/skoda/refresh` | user | `{force}` → `{refreshed, account, vehicles}`; without force only when due (first visit after login, data older than 15 min) |
| GET | `/api/skoda/vehicles/{vin}/image` | user | Saved picture of the user's own vehicle |
| GET | `/api/map/tiles/{z}/{x}/{y}.png` | user | Map tile through the server cache |
| WS | `/ws/tasmota` | user | Live device updates: `snapshot`, `device`, `removed`, `mqtt` messages |
| WS | `/ws/tasmota/console/{id}` | user | Device console: `hello`, `source`, `lines`, `reset`; send `{"type":"command","command":"Status 0"}` (admin only) |

Errors are returned as `{"detail": "message"}` with the matching HTTP status
(401 not logged in, 403 not allowed / missing CSRF header, 409 conflict or device offline, 422 invalid input,
423 switch locked, 429 locked out, 502 Škoda or map server not reachable, 503 MQTT not connected, 504 device did not respond).
