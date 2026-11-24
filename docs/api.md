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
| GET | `/api/radio/stations` | admin | Stations with source addresses, in display order |
| POST | `/api/radio/stations` | admin | `{slug, name, sub?, urls[1..5], content_type?}` → station; 409 when the id is taken |
| PUT | `/api/radio/stations/{id}` | admin | Update a station |
| DELETE | `/api/radio/stations/{id}` | admin | Delete a station |
| PUT | `/api/radio/stations/order` | admin | `{ids: [...]}` – full new order |
| WS | `/ws/tasmota` | user | Live device updates: `snapshot`, `device`, `removed`, `mqtt` messages |
| WS | `/ws/tasmota/console/{id}` | user | Device console: `hello`, `source`, `lines`, `reset`; send `{"type":"command","command":"Status 0"}` (admin only) |

## Player – library (logged-in users)

Only tracks that exist now, on locations that are switched on, are listed. Lists are paged with `limit` (1–200)
and `offset`. Search (`q`) ignores case and accents and needs every word to be found.

| Method | Path | Description |
|---|---|---|
| GET | `/api/player/albums` | `{items: [{id, title, artist, year, genre, tracks, duration_s, has_cover}], total}`; `q`, `genre` or `no_genre=true`, `sort=title\|artist\|year` |
| GET | `/api/player/albums/{id}` | `{album, tracks: [...]}` in disc and track order; 404 unknown |
| GET | `/api/player/genres` | `[{name, tracks, albums}]`; `name` null = tracks without a genre; genres that differ only in case are one |
| GET | `/api/player/tracks` | `{items: [{id, title, artist, album_id, album, track_no, disc_no, year, genre, duration_s, format, has_cover}], total}`; `q`, `genre`, `no_genre` |
| GET | `/api/player/cover/{album_id}?size=96\|300\|600` | The album picture as a JPEG (`Cache-Control: private, no-cache`, so the browser revalidates with the ETag); 404 no picture, 400 other size |
| GET | `/api/player/locations` | `[{id, name, tracks}]` – names only, never paths |
| GET | `/api/player/folders?source_id=&path=` | `{source_id, source_name, path, folders: [{name, path, tracks}], tracks: [...]}`; 404 unknown location or folder |

## Player – locations and scans (administrators)

| Method | Path | Description |
|---|---|---|
| GET | `/api/config/player/sources` | `[{id, name, kind, path, network_path, username, has_password, enabled, last_scan_at, last_scan_status, tracks, missing}]`; `kind` is `local` or `smb`; the password is never sent |
| POST, PUT | `/api/config/player/sources[/{id}]` | `{name, kind, enabled}` plus `path` (local folder) or `network_path` (`\\server\share[\folder]`, also `//server/share/folder` and `smb://…`), `username` and `password` (SMB). On PUT a missing `password` keeps the saved one; an empty `username` means guest and drops the password; `kind` cannot change (400). 400 folder missing or not readable, or a server outside the local network; 409 name used, or the location is being scanned; 422 invalid network path |
| POST | `/api/config/player/sources/test` | The same body (and `source_id` to use the saved password) → `{ok, message, tracks}`. Connects, reads the location and counts the music files (up to 2000); nothing is saved. Failures are `ok: false` with a plain message (wrong user or password, share or folder not found, access denied, cannot reach the server, not a local server) |
| DELETE | `/api/config/player/sources/{id}` | Removes the location and its library entries; the files are never touched |
| POST | `/api/config/player/sources/{id}/scan` | Starts a scan in the background → 202 `{scan_id, sources}`; 409 a scan is running, 400 location switched off |
| POST | `/api/config/player/scan` | The same for every location that is switched on, one after the other |
| POST | `/api/config/player/scan/cancel` | 204; 409 when no scan is running |
| GET | `/api/config/player/status` | `{scanning, scan_id}` |
| GET | `/api/config/player/sources/{id}/scans?limit=` | Latest scans: `{id, started_at, finished_at, started_by, status, added, changed, removed, errors, error_message}` |
| GET | `/api/config/player/scans/{id}` | The same plus `added_files`, `changed_files`, `removed_files`, `new_folders`, `removed_folders`, `error_list` (at most 5000 entries per list; the counts are exact) |
| GET, PUT | `/api/config/player/metadata` | `{online_enabled, contact_set, running, pending, albums, with_cover, found, not_found, errors}`; PUT `{online_enabled}` switches the online lookup (kept in the database; the ini value is the default) |
| POST | `/api/config/player/metadata/run` | Starts the lookup of the albums that wait for a picture or online data (202, same body as GET) |
| POST | `/api/config/player/metadata/retry` | Marks the albums that were not found or failed as waiting again, and starts (202) |
| POST | `/api/config/player/albums/{id}/refresh` | Forgets the picture and online data of one album and looks again (202); 404 unknown |
| POST | `/api/config/player/sources/{id}/remove-missing` | `{removed}` – deletes the files that disappeared from the library for good |

## Player – audio and listening session (logged-in users)

The listening session (queue, shuffle, repeat, state) lives in the server's memory, one per user and `client_id`
(8–64 letters, digits, `-`, `_`; the browser makes one and keeps it). A restart of HomeStart empties the queues.

| Method | Path | Description |
|---|---|---|
| GET, HEAD | `/player/stream/{track_id}?sid={client_id}` | The file as it is (no transcoding). `Content-Type` by format, `Content-Length`, `Accept-Ranges: bytes`. A single `Range` is answered with 206 (`bytes=a-b`, `a-`, `-n`); 416 when it is outside the file; several ranges are ignored (200). 404 unknown, disabled or missing track, 502 the file cannot be read (also a link leading out of the location), 503 `[player] max_listeners` reached. A listener counts once however many streams it has open (the track playing and the one loaded ahead) |
| GET | `/api/player/session?client_id=` | The state: `{status, index, shuffle, repeat, version, current_id, next_id, queue: [track...]}`; `status` is `stopped`, `playing` or `paused`; `next_id` is the track playback reaches next (null at the end, or on repeat one) |
| POST | `/api/player/session/command` | `{client_id, action, ...}` answered with the new state. See below |
| GET | `/api/player/session/events?client_id=` | The state as server-sent events: one at once, then one for every change; a comment line every 15 s |

Actions: `play`, `enqueue` and `play_next` take what to play – `track_id`, `track_ids` (up to 500, order kept),
`album_id`, `source_id` with `path` (the folder and everything below it), or `playlist_id` (its tracks that can be played now) – and `play` also `start_track_id` (start
there) and `shuffle` (switches shuffle on or off first); `enqueue` and `play_next` on an empty queue start playing.
`pause`, `resume`, `stop` (the queue stays), `next`, `prev`, `jump` (`index`), `shuffle` (`on`), `repeat`
(`mode`: `off`, `all`, `one`), `clear`. The browser reports `ended` when a track finishes (the server moves on; at the end
of the queue playback stops, or starts again with repeat all) and `error` when a track cannot be played (the server skips
it; after three in a row playback stops). 400 for a missing argument, 404 when nothing playable was named.

## Player – playlists (logged-in users)

A user's playlists are private; a *panel playlist* (`panel: true`, no owner) is seen and played by everybody and changed by
administrators only. Another user's playlist answers 404. An entry is a track in a playlist; the same track may be there twice.
An entry whose file is missing, or whose location is switched off, stays (`available: false`) and is skipped when played; when
the track is removed from the library the entry goes too. At most 100 playlists per user and 2000 entries per playlist (409).

| Method | Path | Description |
|---|---|---|
| GET | `/api/player/playlists` | `[{id, name, panel, editable, tracks, playable, duration_s}]`: own first, then panel playlists |
| POST | `/api/player/playlists` | `{name, panel?}` → 201; `panel: true` is for administrators (403) |
| GET | `/api/player/playlists/{id}` | `{playlist, tracks: [track + entry_id, available]}` in list order |
| PUT, DELETE | `/api/player/playlists/{id}` | Rename (`{name}`) or delete; 403 for a panel playlist of a non-administrator. Deleting a panel playlist also takes it off the openpanel suggestions |
| POST | `/api/player/playlists/{id}/tracks` | Adds at the end what the body names (`track_id`, `track_ids`, `album_id`, `source_id` + `path`, `playlist_id`); answers the playlist; 404 nothing to add, 409 too big |
| DELETE | `/api/player/playlists/{id}/tracks/{entry_id}` | Removes one entry; answers the playlist |
| PUT | `/api/player/playlists/{id}/order` | `{entry_ids: [...]}` – every entry exactly once (400); answers the playlist |
| GET | `/api/player/panel` | What the openpanel offers: `{favorites, suggestions, playlists}`; items `{id, section, kind, ref, title, name, available, sort_order}` |

## Player – the openpanel content (administrators)

*Favourites* are tracks; *suggestions* are albums, folders or panel playlists. `ref` is the id (for a folder
`"<location id>:<folder path>"`). An item that is gone or cannot be played is kept, with `available: false`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/config/player/panel` | The same as `GET /api/player/panel` |
| POST | `/api/config/player/panel/items` | `{section: favorites\|suggestions, kind: track\|album\|folder\|playlist, ref, title?}` → 201; 400 wrong kind for the section or unknown location, 404 unknown item or not a panel playlist, 409 already there |
| PUT, DELETE | `/api/config/player/panel/items/{id}` | Set the title (`{title}`, empty = the name) or take the item off |
| PUT | `/api/config/player/panel/{favorites\|suggestions}/order` | `{ids: [...]}` – every item of the section exactly once |

## Player on the openpanel (open to the local network)

Same access rule as the Radiopanel below (`[radio] allowed_networks`, loopback, or a logged-in user; `X-Forwarded-For` is
ignored). The tablet is a listener of its own: its session is the `client_id` it makes up, independent of any user and of the
sessions of the app. Everything here shows only the file types of `[player] openpanel_formats` (default mp3, m4a, aac): a FLAC
or OGG track does not exist for the tablet (404 on the stream, absent from lists, marked `available: false` in a playlist).
Requests other than GET and HEAD must carry the header `X-HomeStart: 1` (403 without), so a page of another site cannot steer a
tablet. Paths and addresses of locations are never given.

| Method | Path | Description |
|---|---|---|
| GET | `/openpanel/player/albums`, `/albums/{id}`, `/genres`, `/tracks`, `/locations`, `/folders`, `/cover/{album_id}` | The library, exactly as under `/api/player/` |
| GET | `/openpanel/player/content` | `{favorites, suggestions, playlists}` set by the administrator; every item has a `selector` – what to give the player to play it (`{track_id}`, `{album_id}`, `{source_id, path}` or `{playlist_id}`) |
| GET | `/openpanel/player/playlists`, `/playlists/{id}` | The panel playlists only; a user's own playlist is 404 |
| GET | `/openpanel/player/session?client_id=` | The state of the tablet's session (as under `/api/player/session`) |
| POST | `/openpanel/player/session/command` | The same commands; `playlist_id` can only be a panel playlist |
| GET, HEAD | `/openpanel/player/stream/{track_id}?sid={client_id}` | The track, with Range, as under `/player/stream/`; counts as a listener against `[player] max_listeners` |
| GET | `/openpanel/music.js` | The script of the Music tab (the page is `/openpanel/`) |

## Radiopanel (open to the local network)

These need no session when the client is in `[radio] allowed_networks` (or loopback); otherwise a logged-in user
is required and anyone else gets 403. They are not under `/api`, so the CSRF header is not needed.

| Method | Path | Description |
|---|---|---|
| GET | `/openpanel/` | The panel for old tablets (HTML; `panel.js` and `panel.css` next to it) |
| GET | `/openpanel/stations` | `{openhab_enabled, openhab_start, stations: [{id, name, sub}]}` |
| GET, HEAD | `/openpanel/radio/{id}` | Endless audio stream of a station. 404 unknown id, 503 `max_listeners` reached, 502 no source answered. Headers: `Cache-Control: no-store`, no `Content-Length`; a `Range` request is answered with the whole stream (200) |
| GET | `/openpanel/status` | `{uptime_seconds, total_listeners, max_listeners, stations: [{id, name, listeners, title}]}` |
| GET | `/openpanel/health` | `ok` |
| GET, HEAD, POST, PUT, DELETE | paths from `[radio] openhab_paths` (e.g. `/basicui/…`, `/rest/…`) | Forwarded to `openhab_url` and answered as received; 502 when openHAB does not answer. Other paths are not forwarded |

Errors are returned as `{"detail": "message"}` with the matching HTTP status
(401 not logged in, 403 not allowed / missing CSRF header, 409 conflict or device offline, 422 invalid input,
423 switch locked, 429 locked out, 502 Škoda or map server not reachable, 503 MQTT not connected, 504 device did not respond).
