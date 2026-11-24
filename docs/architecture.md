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
| `radio_stations` | id, slug (unique), name, sub, urls_json (list), content_type, sort_order |
| `music_sources` | id, name (unique), kind (`local` or `smb`), path (local), host, share, subpath (SMB), domain (unused), username_enc, password_enc (encrypted), enabled, last_scan_at, last_scan_status |
| `music_albums` | id, album_key (unique), title, artist, year, genre, cover_file, cover_source (`embedded`, `folder`, `online`), cover_checked, meta_status (`pending`, `found`, `not_found`, `error`), meta_checked_at, mb_release_id |
| `music_tracks` | id, source_id, rel_path (unique per source, `/` separators), folder, size, mtime, format, duration_s, bitrate, title, artist, album_artist, album_id, track_no, disc_no, year, genre, tags_derived, available, missing_since, search_text |
| `playlists` | id, user_id (NULL = panel playlist), name, created_at |
| `playlist_tracks` | id, playlist_id, track_id (both cascade), position |
| `panel_items` | id, section (`favorites`, `suggestions`), kind (`track`, `album`, `folder`, `playlist`), ref, title, sort_order; unique per section, kind and ref |
| `music_scans` | id, source_id, started_at, finished_at, started_by, status, added, changed, removed, errors, error_message, details_json (new, changed, removed files; new and removed folders) |
| `vehicles_cache` | id, account_id, vin, name, data_json (normalized vehicle data), image_file, updated_at |

## Player (library)

- **Scan** (`services/player/scanner.py`): `ScanService` runs one scan at a time in a background thread (several
  locations are done one after the other; the administrator can cancel). A scan walks the folder without following
  links (a link that leads out of the location is skipped), compares size and modification time with the database, and
  reads the tags only of new and changed files. Files that are gone are marked `available = false` with
  `missing_since`; they are deleted only after `[player] missing_keep_days` or by "remove missing". A location that
  cannot be read fails the scan and marks nothing as removed. After a restart, scans left as `running` are marked failed.
- **Report**: every scan writes a `music_scans` row; the new and removed folders are the folders (with their parents)
  that hold music before and after the scan.
- **Tags** (`services/player/tags.py`, mutagen): ID3v2 with ID3v1 as the fallback, MP4 and Vorbis through mutagen's
  easy interface. Text declared as Latin-1 is repaired: valid UTF-8 first, then `[player] legacy_encoding`. Missing
  title, artist and track number come from the file name (`Artist - Album - 01 - Title`, `Artist - 01 - Title`,
  `01 - Title`), the album from the folder name; such tracks have `tags_derived`.
- **Albums**: tracks share an album by album and album artist; without an album artist tag, or without an album
  tag, by album and folder. The album's artist is its album artist, the track artist when all tracks share it, else
  "Various artists".
- **Search**: `music_tracks.search_text` holds title, artist and album without case and accents; the query is folded the
  same way (`fold()`), so "sto" finds "što".
- **Locations** (`services/player/files.py`): `make_location()` gives a `LocalLocation` or an `SmbLocation` with the same
  four operations – `check`, `walk`, `open_for_tags`, `open_stream` – so scanning and streaming do not know which one
  they read. The SMB location uses `smbclient` (smbprotocol), NTLM on port 445, the user name and password passed with every
  call (no global session); with no user name it reads as `Guest`. Credentials are AES-256-GCM encrypted in
  `username_enc` / `password_enc` (key file as for Škoda), decrypted only for the length of a call, and never written to
  a log or an answer. Library errors are turned into short messages (`smb_error`) without any secret. Only servers whose
  addresses are all private, loopback or link-local are accepted (checked when saved, tested and scanned). Tags are read
  from a file object, so only the parts of a remote file the tag reader asks for are transferred; the bytes of a track are
  read at the offsets the Range request names. Links on a share are not followed.
- **Playlists and the openpanel content** (`api/player_playlists.py`): the list is the `position` of `playlist_tracks`
  entries (ids, so a track can be there twice and one entry can be removed). `selected_tracks()` turns what a request
  names – a track, tracks, an album, a folder, a playlist – into track ids and is shared by the playlists and the listening
  session; it only gives tracks that can be played now. Access is decided in one place: `visible_playlist()` (own or panel)
  and `can_edit()` (the owner, or an administrator for a panel playlist). `panel_content()` is what the openpanel will
  read: favourites, suggestions (each item resolved to a name and an `available` flag) and the panel playlists.
- **Openpanel** (`api/player_panel.py`, `static/openpanel/music.js`): a router under `/openpanel/player` with the same access
  rule as the radio (`require_local_or_user`) that re-uses the handlers of the app's library and the cores of the stream and
  the session (`serve_track`, `session_state`, `run_command`) with a session key `panel:<client_id>` and no user. A dependency
  narrows `api.player.visible_formats` (a `ContextVar` read by `_live()`) to `[player] openpanel_formats` for the request, so
  every query of the tablet already leaves out what it cannot play; it is `async` so that it runs in the task that handles the
  request. Non-GET requests need the `X-HomeStart` header. The page (`music.js`) is plain ES5 for Safari on iOS 9
  (a test keeps ES6 syntax out of it): it mirrors the browser store of the app – two `<audio>` elements, preload of the next
  track `PRELOAD_SECONDS` before the end, change-over on `ended` – and unlocks both elements during the first tap by playing a
  short silence, since iOS only allows sound that starts from a tap. Starting the radio pauses the music and the other way
  round (`window.HomeStartPanel` hooks in `panel.js`). Text from the library is only written with `textContent`.
- **Pictures and online data** (`services/player/metadata.py`, `covers.py`): `MetadataService` works through the albums that
  need it in a background thread (started at start-up, after every scan, and by the administrator). For each album it
  looks for a picture first in the files (ID3 APIC, MP4 `covr`, FLAC pictures; the first three tracks), then in the folder
  (`cover`, `folder`, `front`, `albumart`, `album` as jpg, jpeg or png), then – when the online lookup is on – on
  MusicBrainz (`release:"title" AND artist:"name"`, a hit needs score 80+, the same title and a matching artist; the one
  with the same track count wins) and the Cover Art Archive (`front-500` of the release found). Year and genre are only
  filled where the tags have none. At most one MusicBrainz request a second, with `User-Agent: HomeStart/1.0 ( contact )`.
  Only artist, album and the number of tracks leave the server. Every picture is checked with Pillow (JPEG, PNG or
  WebP, at least 16 px, at most 40 megapixels and 10 MB), made a JPEG of at most 600 px and kept in `cache_dir/covers`;
  the smaller sizes are made when first asked for. `not_found` is asked again after `metadata_recheck_days`, `error`
  after an hour. A scan that touches an album without a picture looks again. The on/off switch is kept in `app_settings`.
- **Streaming** (`api/player_stream.py`, `services/player/files.py`): the server opens the file (`open_track_file`: the
  path is built from the database entry only and must stay inside the location, links leading out are refused) and
  sends it in 64 KiB parts read in a thread, with Range support. The listener is counted in `PlayerHub.acquire_stream` and
  released when the client leaves; the user and the track are looked up with short database sessions, so no connection
  stays open during the audio. `max_listeners` counts listeners (sessions with a stream), not connections.
- **Sessions** (`services/player/hub.py`): `Session` holds the queue (`queue` in play order, `base` in the order added, for
  shuffle off), index, status, shuffle and repeat; `PlayerHub` holds the sessions, the stream counts and wakes the
  server-sent events when a session changes. Commands are applied in `api/player_stream.py`; tracks that left the
  library are taken out of the queue whenever the state is built.
- **Browser** (`stores/player.ts`, `components/player-bar.vue`): one store for the whole app with two `<audio>` elements.
  The second one loads the next track `PRELOAD_SECONDS` before the end; when the track ends, the ready one is started at
  once and the server is told (`ended`), so there is no loading between tracks. The sound goes on while other pages are open;
  starting the player stops the radio and the other way round. A reloaded page comes back paused, with the queue.
- Listings only show available tracks of locations that are switched on. Paths never leave the server: the library
  API gives location names and folder paths relative to the location.

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

## Radiopanel

- **Relay** (`services/radio/hub.py`): `RadioHub.subscribe()` joins or starts the relay of a station. A `Stream` owns
  the one upstream connection (httpx, IPv4, certificates checked, at most 5 redirects) and pushes every chunk into
  a bounded queue per listener; a slow listener loses its oldest audio instead of holding the others back. The
  connection is closed when the last listener leaves. Source addresses are tried in order (10 s each; a text or
  image answer counts as failure). A source that drops or is silent for 15 s is reconnected up to 3 times
  (the counter restarts after a connection that lasted 30 s), then the listeners' streams end. `max_listeners`
  is checked and the slot taken before waiting for the station, so parallel requests cannot exceed it.
- **ICY** (`services/radio/icy.py`): the request asks for metadata; when the answer has `icy-metaint`, the
  demultiplexer removes the metadata blocks, so the browser gets clean audio, and keeps `StreamTitle` for
  `/openpanel/status`. The title is decoded as UTF-8, else Latin-1, and written by the browsers as text only.
- **Access** (`access.py`): `require_local_or_user` lets in clients from `[radio] allowed_networks` and valid
  sessions. `X-Forwarded-For` is ignored. It opens its own short database session so that a long audio stream
  does not hold a connection.
- **openHAB** (`api/openhab.py`): routes are registered at start for each path in `openhab_paths`. Requests go to
  `openhab_url` and the answer is streamed back unchanged (no read timeout, so Basic UI's live updates arrive
  immediately); `Location` is made relative, `X-Frame-Options` removed, HomeStart's session cookie not passed on.
  The responses keep openHAB's own security headers: HomeStart's content security policy is skipped for them.
- **Compression**: the gzip middleware skips responses that already have a `Content-Encoding`, so audio and
  proxied responses are sent with `Content-Encoding: identity` and are not buffered.
- **Panel for old tablets** (`static/openpanel/`): plain ES5 without a build step, for Safari on iOS 9, served at
  `/openpanel/` (the Vue app cannot run there). Scripts and styles are separate files because of the content
  security policy. The audio element is outside the tabs, so the sound goes on when the Home tab is opened. The Vue
  module keeps one `Audio` in the store, so the sound goes on while other pages are open.

## Backups

`homestart.backup` is a separate entry point run by `homestart-backup.timer` (daily, `Persistent=true`). It uses
`sqlite3.Connection.backup`, switches the copy to `journal_mode=DELETE` so it is one self-contained file, checks
it with `PRAGMA integrity_check`, writes it under a temporary name and renames it (mode 0600, folders 0700).
The first copy of a month is also stored as the monthly copy. Retention is by file name: daily copies whose
date lies within the last `daily_keep` days, and the newest `monthly_keep` monthly copies. A failed run exits
with status 1, which systemd records.
