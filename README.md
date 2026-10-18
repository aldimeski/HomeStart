# HomeStart

HomeStart is a local web portal that gives quick access to the applications and devices used every day
(smart home, local servers, Tasmota devices, car). It runs on a Debian server in the local network.

Current version: **0.1** — base application and the **ShoLink** module (phases 1 and 2 of the specification).
The TasmoSiz and Škoda modules are shown in the menu as "Coming soon".

## Features

- Mandatory login (Argon2id password hashes, HttpOnly session cookie, inactivity timeout, lockout after repeated failed logins)
- Roles: administrator (manages users and links) and user
- Light / dark theme and a side menu that collapses to icons; both are remembered per user
- Responsive layout: on phones the menu becomes a slide-out drawer
- **ShoLink**: shared links opened inside the app (iframe) or optionally in a new tab, Material Design Icons
  (served locally) or uploaded icons (SVG/PNG/WebP/ICO, up to 256 KB; SVG files are cleaned of scripts)
- Clear message with an "Open in new tab" button when a page cannot be embedded

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
| `[storage]` | `icons_dir` | `data/icons` | Uploaded link icons |

The database and its folder are created automatically. Schema changes are applied at start-up with Alembic.

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
   sudo mkdir -p /opt/homestart /var/lib/homestart
   sudo chown homestart:homestart /var/lib/homestart
   sudo chmod 750 /var/lib/homestart
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
6. Create `/opt/homestart/homestart.ini` with permanent paths:
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

   [storage]
   icons_dir = /var/lib/homestart/icons
   ```
   Make it readable for the service: `sudo chmod 644 /opt/homestart/homestart.ini`.
7. Install and start the service:
   ```sh
   sudo cp /opt/homestart/deploy/homestart.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now homestart
   sudo journalctl -u homestart -f        # shows which ini file and database were loaded
   ```
8. Allow port 8000 only from the local network, e.g. with ufw:
   ```sh
   sudo ufw allow from 192.168.1.0/24 to any port 8000 proto tcp
   ```

Open `http://<server-address>:8000` in a browser.

### Updating

Copy the new files, run `pip install -r backend/requirements.txt` in the venv again and
`sudo systemctl restart homestart`. Database migrations run automatically.

### Backups

The database is a single file. A safe copy while the service is running:

```sh
sqlite3 /var/lib/homestart/homestart.db ".backup '/var/backups/homestart-$(date +%F).db'"
```

Also back up `/var/lib/homestart/icons/` and `/opt/homestart/homestart.ini`.

## ShoLink notes

- Enter link addresses as the **browser** sees them (e.g. `http://<server-ip>:8080`), not `localhost`.
- Some sites forbid being shown inside another page (`X-Frame-Options` or CSP `frame-ancestors`).
  HomeStart checks this and shows a message with an "Open in new tab" button. For such sites enable
  *Open in new tab* on the link.
- Serve HomeStart over plain HTTP in the local network; an HTTPS page cannot embed HTTP pages.
