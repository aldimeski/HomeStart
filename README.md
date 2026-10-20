# HomeStart

HomeStart is a local web portal that gives quick access to the applications and devices used every day
(smart home, local servers, Tasmota devices, car). It runs on a Debian server in the local network.

User guide: [docs/user-guide.md](docs/user-guide.md).

Current version: **1.0** — all phases of the specification: base application, **ShoLink**, **TasmoSiz**
(devices, consoles, Zigbee), **Škoda**, and installation on the Debian server with daily backups.

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
docs/                   user guide, architecture and API notes
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

On the server, where the installed HomeStart uses port 8000, the development copy gets a `homestart.ini` in
the project folder (ignored by git) with `[server] port = 8001`; start Vite with `HOMESTART_PORT=8001 npm run dev`.

Tests:

```sh
(cd backend && ../../../dev/homestart-venv/bin/python -m pytest)
```

New database migration after changing `models.py`:

```sh
(cd backend && ../../../dev/homestart-venv/bin/alembic revision --autogenerate -m "describe the change")
```

## Installation on the Debian server (systemd)

HomeStart runs directly on Debian 13 as a systemd service, without Docker. The frontend is built on the
development machine; the server needs only Python 3.13 (and `sqlite3` for importing data).

1. On the development machine: build the frontend (`cd frontend && npm install && npm run build`) and copy
   the project folder to the server, or work in a checkout on the server itself.
2. On the server, from the project folder:
   ```sh
   sudo apt install python3.13-venv sqlite3
   sudo bash deploy/install.sh --firewall
   ```
   Add `--import data` to take over the database, uploaded icons and encryption key of a development
   installation (first installation only; an existing production database is never replaced).

The script is safe to run again and is also used for updates. It:

- creates the service account `homestart` and the folders

  | Folder | Contents | Owner, mode |
  |---|---|---|
  | `/opt/homestart` | program (`backend/`, `deploy/`, `frontend/dist/`), `venv/`, `homestart.ini` | root, read-only for the service |
  | `/var/lib/homestart` | `homestart.db`, `icons/`, `cache/` | homestart, 750 |
  | `/etc/homestart` | `homestart.key`, `firewall.nft` | root:homestart, 750 (key 640) |
  | `/var/backups/homestart` | `daily/`, `monthly/` database copies | homestart, 700 |

- installs the Python dependencies into `/opt/homestart/venv` and compiles the bytecode;
- writes `/opt/homestart/homestart.ini` with these paths when it does not exist yet (later edits are kept);
- creates the encryption key when there is none;
- installs and starts `homestart.service` and the daily `homestart-backup.timer`, makes a first backup and
  checks that HomeStart answers on port 8000;
- with `--firewall`: `homestart-firewall.service` loads its own nftables table (`inet homestart`) that allows
  ports 8000 and 1883 only from the server's local network (detected from its address) and from the server
  itself. Rules of other programs are not touched; `sudo systemctl disable --now homestart-firewall` removes it.

Useful commands:

```sh
sudo systemctl status homestart            # state of the service
sudo journalctl -u homestart -f            # log; shows which ini file and database were loaded
sudo systemctl restart homestart           # after editing homestart.ini
sudo journalctl -u homestart-backup        # result of each backup
sudo nft list table inet homestart         # firewall rules
```

Open `http://<server-address>:8000` and change the `admin` password under Configuration → My account.

### Updating

Build the frontend, update the project folder on the server and run `sudo bash deploy/install.sh` again.
Database migrations run automatically when the service starts.

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
