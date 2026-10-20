# HomeStart – architecture

```
Browser (Vue 3 SPA)
   │  HTTP: REST /api/*, static files
   ▼
FastAPI backend (python -m homestart, port 8000)
   ├─ config.py      homestart.ini / homestart_default.ini
   ├─ backup.py      python -m homestart.backup: daily and monthly database copies (homestart-backup.timer)
   ├─ security.py    Argon2id, server-side sessions, login lockout
   ├─ api/auth.py    login, logout, current user
   ├─ api/users.py   user management (admin), own password and settings
   ├─ api/links.py   ShoLink links, order, iframe embed check
   ├─ api/icons.py   uploaded icons (SVG sanitized)
   ├─ api/tasmota.py TasmoSiz REST API, /ws/tasmota live updates, /ws/tasmota/console/{id}
   ├─ api/skoda.py   Škoda account, vehicles, refresh, vehicle picture
   ├─ api/map_tiles.py  map tile proxy with disk cache
   ├─ services/tasmota/
   │    mqtt_link.py  permanent broker connection (aiomqtt), reconnects with back-off
   │    parsing.py    Tasmota payloads → state updates (old split STATUSn and combined STATUS0)
   │    manager.py    device registry, live state, power commands, scan, change notifications
   │    console.py    device consoles: web log polling (/cs), MQTT fallback, commands
   │    zigbee.py     Zigbee bridges: device objects, ZbState (pairing), ZbMap pages → network map
   │    http_api.py   Tasmota /cm and /cs HTTP interface, subnet scan
   ├─ services/skoda/
   │    client.py     the only user of the myskoda library: read-only calls, data → plain dicts
   │    service.py    accounts per user, vehicle cache, refresh rules, picture download
   └─ services/secret_box.py  AES-256-GCM for stored credentials (key in a separate file)
   └─ static         frontend/dist (SPA fallback to index.html)
   ▼
SQLite (WAL) – path from the ini file; schema managed by Alembic
   ▲
Mosquitto (localhost:1883) ◀──▶ Tasmota devices
MyŠkoda API, tile.openstreetmap.org ◀── server only (internet)
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
- `builtin:<name>` — HomeStart's own device icons (`tasmota`, `sonoff`, `esp32`) defined in
  `frontend/src/icons/builtin-icons.ts`; `tasmota` uses the same symbol as the TasmoSiz menu item.
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
| `tasmota_devices` | id, name, mqtt_topic (unique), host, port, mac, hostname, friendly_names, firmware, model, group_name, source, auth_required, removed, created_at, last_seen |
| `app_settings` | key, value_enc (encrypted), updated_at – shared Tasmota login |
| `skoda_accounts` | id, user_id (unique), username_enc, password_enc, refresh_token_enc, last_sync, last_attempt, last_error |
| `vehicles_cache` | id, account_id, vin, name, data_json (normalized vehicle data), image_file, updated_at |

## TasmoSiz

- **Discovery**: the backend stays subscribed to `tele/+/+` (LWT, STATE, SENSOR are used; the rest feeds consoles), `stat/+/+`
  and `tasmota/discovery/+/config|sensors`. A retained LWT creates the device; for each device found this way
  `cmnd/<topic>/Status 0` is sent once (spaced 150 ms apart) to read IP, MAC, firmware, sensors and WiFi.
  Group topics are not used because devices use different ones (`sonoffs` / `tasmotas`).
- **Live state** (relays, sensors, WiFi, online) is kept in memory; only static data is stored. Changes are
  pushed to browsers over the WebSocket `/ws/tasmota` (snapshot on connect, then `device`, `removed` and
  `mqtt` messages). Updates are coalesced for 150 ms, because one Status 0 answer is many messages.
- **Switching** publishes `cmnd/<topic>/POWER<n>` and waits up to 4 s for `stat/<topic>/RESULT` or
  `stat/<topic>/POWER<n>`; the API returns an error if the device is offline or does not confirm.
  Without MQTT the HTTP interface is used when the device address and login are known.
- **Removed devices** are kept with `removed = 1`, so retained broker messages do not restore them after a
  restart; a live (non-retained) message brings them back.
- **Switch names**: `relay_names` (JSON list by relay position) overrides the device's FriendlyName per relay;
  an empty entry falls back to it. The device itself is not changed.
- **Icons**: `icon` and `relay_icons` (JSON list by relay position) use the ShoLink icon references; uploaded
  icons in use by a device or switch cannot be deleted. Switch icons get the class `icon-on` while on: builtin
  icons mark glowing parts with `lit`, `lit-line` or `flame`; MDI icons are split into glowing and plain layers
  by `frontend/src/icons/switch-icons.ts` (bulbs and lamps glow in part, other icons completely).
- **Zigbee bridges**: a device whose firmware build contains "zigbee"/"zbbrdg", or which sends Zigbee device
  objects (`{"<name or 0xSHORT>": {"Device": "0x…", …}}`, optionally inside `ZbReceived`), gets a
  `ZigbeeNetwork` in memory and is asked `ZbInfo` (also on MQTT connect and Refresh). SENSOR and RESULT
  payloads with Zigbee content are not treated as the bridge's own sensors. Kinds: *light* when ZbInfo lists an
  on/off or light cluster in `Config` (O../L..), *sensor* when known measurements are present, *remote* for
  battery devices without either. `ZbSend {"Device","Send":{"Power"}}` waits for a report with the requested state (a bulb first repeats its old state).
  `ZbPermitJoin 1/0` (admin) opens pairing for 60 s; ZbState 20/21/22 keep the state in sync and ZbState 30/34
  (device announced) triggers a new ZbInfo. `ZbMap` (admin) collects the result pages for 30 s into nodes
  (coordinator, routers, end devices) and links with the best link quality of both directions. The bridge's
  view carries all of this in its `zigbee` field, so the existing WebSocket updates cover it.
- **Firmware**: discovery reports only the version ("15.1.0"); it no longer replaces a full build name from
  Status 0 ("15.1.0(release-zbbrdgpro)").
- **Switch locks**: `locked_relays` (JSON list of channel numbers) is set by administrators
  (`PUT /api/tasmota/devices/{id}/lock`). `set_power` refuses a locked channel with 423 for every role, and
  the console refuses `Power<n>` / `Power0` commands with a payload (also inside `Backlog`) for locked
  channels; a bare `Power<n>` only reads the state and is allowed. Physical buttons and other MQTT clients
  are outside HomeStart's control.
- **Consoles**: a browser opens `/ws/tasmota/console/{id}` per console (the page allows at most 4, shown in a right-hand column on wide screens). The first
  viewer of a device starts a poller that reads `/cs?c2=<index>` every second with HTTP Basic auth; the index
  returned by Tasmota makes each read incremental (same format from 7.x to 15.x). The last 300 lines are kept
  so a new viewer sees recent history; the poller stops when the last viewer leaves. If HTTP is not possible
  (login missing or refused, device unreachable) the console shows live MQTT messages of that topic and retries
  HTTP every 15 s. Messages: `hello` (history, source, `can_write`), `source`, `lines`, `reset`. Commands
  (`{"type":"command","command":"…"}`) are accepted only from administrators; the command word must be
  alphanumeric so it cannot alter the MQTT topic.
- **WebSocket security**: the session cookie is checked and the `Origin` header must match the host.
- **Address validation**: manually added devices must resolve to a private IPv4 address; the scan subnet
  must be private and at most /22.

## Škoda

- **Library boundary**: `services/skoda/client.py` is the only module importing `myskoda`. It logs in (stored
  refresh token first, password as fallback), lists the VINs and reads info, status, parking position,
  driving range and health per vehicle. A part a vehicle does not provide is listed in `unavailable` instead
  of failing the refresh. Library objects become plain dicts, so the cache survives library upgrades. The
  library's MQTT push channel is disabled and no command method is called.
- **Doors and windows**: the API reports each door as closed / door open / window open / both through the
  render URL; the library decodes it and `client.py` splits it into `doors` and `windows` per side.
- **Refresh rules** (`service.py`): `POST /api/skoda/refresh {force:false}` asks Škoda when the current HomeStart
  login (session) has not fetched yet or the last attempt is older than 15 minutes; `force:true` always asks.
  Refreshes of one user are serialized with a lock. No database transaction is open while waiting for Škoda.
- **Errors**: a rejected login or unreachable/changed API is stored in `last_error`; the page shows it above
  the last saved data. A rejected login also drops the stored refresh token.
- **Pictures**: the official render URL is downloaded once by the server (https, public addresses only,
  PNG/JPEG/WebP, ≤ 5 MB) into `cache_dir/skoda` and served only to the owner.
- **Map**: Leaflet (bundled, no CDN) loads tiles from `/api/map/tiles/{z}/{x}/{y}.png`; the server fetches them
  from `[map] tile_url`, at most two at a time, and caches them for 30 days. In dark mode tiles are inverted
  with a CSS filter.

## Backups

`homestart.backup` is a separate entry point run by `homestart-backup.timer` (daily, `Persistent=true`). It uses
`sqlite3.Connection.backup`, switches the copy to `journal_mode=DELETE` so it is one self-contained file, checks
it with `PRAGMA integrity_check`, writes it under a temporary name and renames it (mode 0600, folders 0700).
The first copy of a month is also stored as the monthly copy. Retention is by file name: daily copies whose
date lies within the last `daily_keep` days, and the newest `monthly_keep` monthly copies. A failed run exits
with status 1, which systemd records.
