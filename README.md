# HomeStart

HomeStart is a local web portal that gives quick access to the applications and devices used every day
(smart home, local servers, Tasmota devices, car). It runs on a Debian server in the local network.

Current version: **0.4** — base application, the **ShoLink** module, **TasmoSiz** with device overview and
consoles, and the **Škoda** vehicle overview (phases 1–5 of the specification).

## Features

- Mandatory login (Argon2id password hashes, HttpOnly session cookie, inactivity timeout, lockout after repeated failed logins)
- Roles: administrator (manages users and links) and user
- Light / dark theme and a side menu that collapses to icons; both are remembered per user
- Responsive layout: on phones the menu becomes a slide-out drawer
- **ShoLink**: shared links opened inside the app (iframe) or optionally in a new tab, Material Design Icons
  (served locally), device icons (Tasmota, Sonoff, ESP32) or uploaded icons (SVG/PNG/WebP/ICO, up to 256 KB; SVG files are cleaned of scripts)
- Clear message with an "Open in new tab" button when a page cannot be embedded
- **TasmoSiz**: Tasmota devices are found automatically over MQTT (retained LWT and discovery messages),
  with live relay state, sensors (temperature, humidity, pressure, energy …), WiFi signal, uptime and
  firmware; switching of every relay with confirmation from the device; "Scan network" over HTTP as a
  fallback; manual adding, renaming, grouping and removing of devices and naming of every switch (administrator)
- **Icons on devices and switches**: the same icons as ShoLink (library, device icons incl. a gas boiler,
  uploaded icons); a switch icon lights up while the switch is on (the glass of a bulb turns yellow, the flame
  of the gas boiler orange, other icons turn yellow; uploaded images are greyed out while off)
- **Zigbee**: a Tasmota Zigbee bridge is recognized automatically (by its firmware build or its Zigbee
  messages). Its devices appear in their own section: lights with an on/off switch, sensors with their values,
  remotes and sensors with battery level; link quality and last report for each. A network map (bridge,
  routers, end devices, link quality) and, for administrators, a *Join* switch that opens pairing for 60 s
  and a *Scan network* button for a new map
- **Switch locks**: an administrator can lock any switch; nobody (administrators included) can switch it until
  an administrator unlocks it; users see the lock but cannot change it
- **TasmoSiz consoles**: the live log of up to 4 devices at once in a column to the right of the devices
  (below them on narrow screens), one below the other, with pause, clear, auto-scroll and close;
  administrators can send commands, users can only read

- **Škoda** (read only): each user connects their own MyŠkoda account under *My account* and sees their
  vehicles: picture, model, licence plate and VIN, a top view with doors, windows, boot, bonnet and sunroof
  (green closed, red open), lock state, mileage, fuel or battery, range, and the parking position on an
  OpenStreetMap map. HomeStart never sends commands to a vehicle.

## Project layout

```
backend/                FastAPI application (package "homestart"), Alembic migrations, tests
frontend/               Vue 3 + Vite + TypeScript + Tailwind single-page app
deploy/                 systemd unit file
docs/                   architecture and API notes
homestart_default.ini   created by the application on first start (no secrets)
homestart.ini           your local settings (not in git)
data/                   database and uploaded icons in development (not in git)
```

## Configuration (`homestart.ini`)

On start the application looks in its folder (`HOMESTART_HOME`, by default the project root):

1. If `homestart.ini` exists, all settings are read from it. If it is invalid (bad format or missing
   `[database]` section) the application **does not start** and writes the reason to the log.
2. Otherwise `homestart_default.ini` is used; the application creates it when it is missing.

The log always states which ini file was loaded and which database is used. Relative paths are resolved
against the application folder. Create your own settings by copying the default file:

```sh
cp homestart_default.ini homestart.ini
```

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[database]` | `file` | `data/homestart.db` | SQLite database file (required) |
| `[server]` | `host`, `port` | `0.0.0.0`, `8000` | Listen address and port |
| `[security]` | `session_timeout_minutes` | `480` | Logout after this much inactivity |
| `[security]` | `max_failed_logins`, `lockout_minutes` | `5`, `15` | Login lockout |
| `[security]` | `key_file` | `data/homestart.key` | Key for encrypting stored device credentials |
| `[storage]` | `icons_dir` | `data/icons` | Uploaded link icons |
| `[storage]` | `cache_dir` | `data/cache` | Downloaded vehicle pictures and map tiles (safe to delete) |
| `[mqtt]` | `enabled`, `host`, `port` | `true`, `localhost`, `1883` | MQTT broker used by TasmoSiz |
| `[network]` | `scan_subnet` | empty | Subnet for "Scan network"; empty = the server's own /24 |
| `[backup]` | `dir` | `data/backups` | Database copies (`daily/` and `monthly/`) |
| `[backup]` | `daily_keep`, `monthly_keep` | `7`, `5` | Keep daily copies for 7 days and monthly copies for 5 months |
| `[map]` | `tile_url` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Map tiles for the Škoda page |

The database and its folder are created automatically. Schema changes are applied at start-up with Alembic.
`homestart_default.ini` belongs to the application and is rewritten when a new version changes it; put your
changes in `homestart.ini`.

The encryption key file is created automatically when it is missing. Keep it outside the database folder on
the server and back it up: without it, stored device credentials cannot be decrypted (they would have to be
entered again).

## First login

On the first start an administrator account **admin / admin** is created. Changing the password is not
forced, but you should change it under *Configuration → My account*.

## Development

Requirements: Python 3.13 with `python3.13-venv`, Node.js 20+. The commands below are run from the
project root and keep the virtual environment outside the repository (in the workspace `dev/` folder).

```sh
# Backend dependencies
python3 -m venv ../../dev/homestart-venv
../../dev/homestart-venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# Frontend build (writes frontend/dist, served by the backend)
(cd frontend && npm install && npm run build)

# Run on http://localhost:8000
(cd backend && ../../../dev/homestart-venv/bin/python -m homestart)
```

For frontend work with hot reload run `npm run dev` in `frontend/` (port 5173); API calls are proxied to
the backend on port 8000.

Tests:

```sh
(cd backend && ../../../dev/homestart-venv/bin/python -m pytest)
```

New database migration after changing `models.py`:

```sh
(cd backend && ../../../dev/homestart-venv/bin/alembic revision --autogenerate -m "describe the change")
```

## Installation on the Debian server (systemd)

The frontend is built once on a development machine; the server needs only Python 3.13.

1. Build the frontend on the development machine: `cd frontend && npm install && npm run build`.
2. Install system packages on the server:
   ```sh
   sudo apt install python3.13-venv
   ```
3. Create the service account and folders:
   ```sh
   sudo useradd --system --home /var/lib/homestart --shell /usr/sbin/nologin homestart
   sudo mkdir -p /opt/homestart /var/lib/homestart /var/backups/homestart
   sudo chown homestart:homestart /var/lib/homestart /var/backups/homestart
   sudo chmod 750 /var/lib/homestart
   sudo chmod 700 /var/backups/homestart
   ```
4. Copy the application to `/opt/homestart` (`backend/`, `deploy/` and `frontend/dist/`; `node_modules`
   and `data/` are not needed), for example:
   ```sh
   rsync -a --exclude node_modules --exclude data --exclude .git ./ server:/opt/homestart/
   ```
5. Create the virtual environment and install the dependencies:
   ```sh
   sudo python3 -m venv /opt/homestart/venv
   sudo /opt/homestart/venv/bin/pip install -r /opt/homestart/backend/requirements.txt
   ```
6. Create the encryption key, readable only by the service:
   ```sh
   sudo install -d -m 750 -o root -g homestart /etc/homestart
   head -c 32 /dev/urandom | base64 | sudo tee /etc/homestart/homestart.key > /dev/null
   sudo chown root:homestart /etc/homestart/homestart.key
   sudo chmod 640 /etc/homestart/homestart.key
   ```
7. Create `/opt/homestart/homestart.ini` with permanent paths:
   ```ini
   [database]
   file = /var/lib/homestart/homestart.db

   [server]
   host = 0.0.0.0
   port = 8000

   [security]
   session_timeout_minutes = 480
   max_failed_logins = 5
   lockout_minutes = 15
   key_file = /etc/homestart/homestart.key

   [storage]
   icons_dir = /var/lib/homestart/icons

   [mqtt]
   enabled = true
   host = localhost
   port = 1883

   [network]
   scan_subnet = 192.168.1.0/24

   [backup]
   dir = /var/backups/homestart
   daily_keep = 7
   monthly_keep = 5
   ```
   Make it readable for the service: `sudo chmod 644 /opt/homestart/homestart.ini`.
8. Install and start the service:
   ```sh
   sudo cp /opt/homestart/deploy/homestart.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now homestart
   sudo journalctl -u homestart -f        # shows which ini file and database were loaded
   ```
9. Install the daily database backup (see *Backups* below):
   ```sh
   sudo cp /opt/homestart/deploy/homestart-backup.service /opt/homestart/deploy/homestart-backup.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now homestart-backup.timer
   sudo systemctl start homestart-backup.service   # first copy right away
   sudo journalctl -u homestart-backup             # result of each run
   ```
10. Allow port 8000 only from the local network, e.g. with ufw:
   ```sh
   sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp
   ```

Open `http://<server-address>:8000` in a browser.

### Updating

Copy the new files, run `pip install -r backend/requirements.txt` in the venv again and
`sudo systemctl restart homestart`. Database migrations run automatically.

### Backups

`homestart-backup.timer` runs `python -m homestart.backup` every day at 03:00. It copies the database with
SQLite's backup API (safe while HomeStart runs), checks the copy (`PRAGMA integrity_check`) and keeps:

- **daily copies** of the last 7 days: `/var/backups/homestart/daily/homestart-YYYY-MM-DD.db`
- **monthly copies** of the last 5 months: `/var/backups/homestart/monthly/homestart-YYYY-MM.db`. The monthly
  copy is the first copy of the month, normally the one made on the 1st; if the server was off on the 1st,
  the timer catches up at the next start (`Persistent=true`), so no month is missing.

Older copies are deleted by the same run. The numbers can be changed with `daily_keep` and `monthly_keep`
in `[backup]`. Copies are readable only by the service account, because they contain password hashes and
encrypted logins. A copy can also be made at any time with `sudo systemctl start homestart-backup.service`.

The copies stay on the same disk as the database. To survive a disk failure, copy `/var/backups/homestart`
to another machine or disk from time to time, together with `/etc/homestart/homestart.key` (without the key,
stored Tasmota and Škoda logins in a copy cannot be read), `/opt/homestart/homestart.ini` and
`/var/lib/homestart/icons/`. The cache folder (`cache_dir`) does not need a backup.

Restoring a copy:

```sh
sudo systemctl stop homestart
sudo cp /var/backups/homestart/daily/homestart-2026-10-20.db /var/lib/homestart/homestart.db
sudo rm -f /var/lib/homestart/homestart.db-wal /var/lib/homestart/homestart.db-shm
sudo chown homestart:homestart /var/lib/homestart/homestart.db
sudo systemctl start homestart
```

## ShoLink notes

- Enter link addresses as the **browser** sees them (e.g. `http://<server-ip>:8080`), not `localhost`.
- Some sites forbid being shown inside another page (`X-Frame-Options` or CSP `frame-ancestors`).
  HomeStart checks this and shows a message with an "Open in new tab" button. For such sites enable
  *Open in new tab* on the link.
- Serve HomeStart over plain HTTP in the local network; an HTTPS page cannot embed HTTP pages.

## TasmoSiz notes

- Devices are discovered from the MQTT broker (Mosquitto on the same server, no authentication) using the
  standard Tasmota topics `tele/<topic>/LWT|STATE|SENSOR` and `stat/<topic>/…`, plus the retained
  `tasmota/discovery/…` messages of newer firmware. Old firmware (e.g. 8.1.0, which answers `Status 0` with
  separate STATUS…STATUS11 messages) and new firmware (one STATUS0 message) are both supported.
- At start-up HomeStart sends `cmnd/<topic>/STATE` to every known device so the current state appears
  immediately; "Refresh" asks all devices again. Sensors update when the device publishes (TelePeriod).
- A device that disappears stays in the list as offline. An administrator can remove it; a removed device
  reappears only if it publishes on MQTT again.
- "Scan network" checks every address of the subnet on port 80 with `/cm?cmnd=Status 0`. Devices with web
  login enabled are marked "login required" unless the shared Tasmota login is entered under
  *Configuration → Devices*. The login is stored encrypted (AES-256-GCM) and is not needed for MQTT.
- Switch names set in HomeStart are stored only in HomeStart; the device keeps its own FriendlyName, which is
  shown when the HomeStart name is empty.
- **Zigbee bridges** must use the default Zigbee2Tasmota topics: device data on `tele/<bridge>/SENSOR`
  (SetOption89 off). Names (SetOption83) and the `ZbReceived` wrapper (SetOption100) may be on or off.
  Zigbee data is kept in memory and read again with `ZbInfo` at start-up and on *Refresh*. Lights are switched
  with `ZbSend`; the switch waits up to 6 s for the device to report its new state. The Zigbee network key
  is never read or shown.
- **Switch locks** are enforced by the server for the switches in HomeStart and for `Power` commands in the
  console (also inside `Backlog`). They cannot stop the device's own button, the Tasmota web page, openHAB or
  other MQTT clients.
- **Consoles** read the device's web log (`/cs`, the same source as the console in the Tasmota web page) once
  per second while the console is open; several viewers of one device share a single poller. Devices with web
  login enabled need the shared Tasmota login from *Configuration → Devices*; without it, or when the web
  interface does not answer, the console shows the device's MQTT messages instead ("MQTT only").
  Commands are sent over MQTT (`cmnd/<topic>/<command>`), or over HTTP when MQTT is not available. Only the
  command name is written to the server log, because commands such as `WebPassword` contain secrets.
- The MQTT broker accepts anonymous clients, so allow port 1883 only from the local subnet in the firewall.

## Škoda notes

- Škoda has no official API for private customers. HomeStart uses the unofficial MyŠkoda API through the
  open-source library [`myskoda`](https://pypi.org/project/myskoda/) (the one used by the Home Assistant
  integration). When Škoda changes the API, the module may stop working until the library is updated:
  update `myskoda` in `backend/requirements.txt` and reinstall. The last saved data stays visible meanwhile.
- The server needs internet access to Škoda's servers and to the map tile server; the browser only talks to
  HomeStart.
- Data is fetched only on demand: the first time the Škoda page is opened after logging in to HomeStart,
  when the saved data is older than 15 minutes, and with the *Refresh* button. Nothing is polled in the
  background.
- The MyŠkoda email and password are stored encrypted (AES-256-GCM, the same key file as the Tasmota login),
  together with an encrypted session token so that later updates do not need the password.
  *Sign out of Škoda account* deletes the login, the token and all saved vehicle data of that user.
- If Škoda asks to accept new terms or a consent screen, open the MyŠkoda app once, accept it and try again.
- Map tiles are downloaded by the server (over IPv4, with an identifying User-Agent as the OpenStreetMap
  tile policy requires) and cached for 30 days in `cache_dir/tiles`.
