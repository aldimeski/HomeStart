#!/usr/bin/env bash
# Installs or updates HomeStart on this Debian server. Run from the project folder:
#
#   sudo bash deploy/install.sh [--import DATA_DIR] [--firewall]
#
#   --import DATA_DIR  first installation only: take over homestart.db, icons/ and homestart.key from a
#                      development data folder (e.g. data/). An existing production database is never replaced.
#   --firewall         allow ports 8000 and 1883 only from this server's local network (own nft table).
#
# Running it again updates the program files and dependencies and restarts the service; data and
# homestart.ini stay as they are.
set -euo pipefail

APP=/opt/homestart
DATA=/var/lib/homestart
CONF=/etc/homestart
BACKUPS=/var/backups/homestart
SERVICE_USER=homestart
PYTHON=python3.13

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMPORT=""
FIREWALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --import) IMPORT="$(cd "$2" && pwd)"; shift 2 ;;
    --firewall) FIREWALL=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { echo; echo "==> $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "run with sudo"
[[ -f "$SRC/frontend/dist/index.html" ]] || fail "frontend is not built; run 'npm run build' in frontend/ first"
[[ -f "$SRC/backend/requirements.txt" ]] || fail "run the script from the HomeStart project ($SRC)"
command -v "$PYTHON" > /dev/null || fail "$PYTHON is missing (apt install python3.13-venv)"
if [[ -n "$IMPORT" ]]; then
  [[ -f "$IMPORT/homestart.db" ]] || fail "$IMPORT/homestart.db not found"
  command -v sqlite3 > /dev/null || fail "sqlite3 is needed for --import (apt install sqlite3)"
fi

step "Service account and folders"
id "$SERVICE_USER" > /dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin "$SERVICE_USER"
install -d -m 755 -o root -g root "$APP"
install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA" "$DATA/icons" "$DATA/cache"
install -d -m 700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$BACKUPS"
install -d -m 750 -o root -g "$SERVICE_USER" "$CONF"

step "Program files"
rm -rf "$APP/backend" "$APP/deploy" "$APP/frontend"
cp -a "$SRC/backend" "$SRC/deploy" "$APP/"
mkdir -p "$APP/frontend" && cp -a "$SRC/frontend/dist" "$APP/frontend/"
find "$APP/backend" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root "$APP/backend" "$APP/deploy" "$APP/frontend"

step "Python environment"
[[ -x "$APP/venv/bin/python" ]] || "$PYTHON" -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet --upgrade pip
"$APP/venv/bin/pip" install --quiet -r "$APP/backend/requirements.txt"
# The service cannot write below /opt, so the bytecode is compiled now.
"$APP/venv/bin/python" -m compileall -q "$APP/backend/homestart" "$APP/backend/migrations"

step "Settings ($APP/homestart.ini)"
if [[ -f "$APP/homestart.ini" ]]; then
  echo "kept the existing homestart.ini"
else
  cat > "$APP/homestart.ini" <<EOF
# HomeStart settings for this server (written by deploy/install.sh; edit as needed).
[database]
file = $DATA/homestart.db

[server]
host = 0.0.0.0
port = 8000

[security]
session_timeout_minutes = 480
max_failed_logins = 5
lockout_minutes = 15
key_file = $CONF/homestart.key

[storage]
icons_dir = $DATA/icons
cache_dir = $DATA/cache

[mqtt]
enabled = true
host = localhost
port = 1883

[network]
# Empty = the server's own /24 network.
scan_subnet =

[map]
tile_url = https://tile.openstreetmap.org/{z}/{x}/{y}.png

[radio]
# Networks that may use /openpanel and the openHAB pass-through without logging in (comma separated).
allowed_networks = 192.168.1.0/24
max_listeners = 3
# openHAB address for the Home tab of the Radiopanel (empty = no Home tab), e.g. http://127.0.0.1:8080
openhab_url =

[backup]
dir = $BACKUPS
daily_keep = 7
monthly_keep = 5
EOF
  chmod 644 "$APP/homestart.ini"
fi

step "Data"
if [[ -n "$IMPORT" ]]; then
  if [[ -f "$DATA/homestart.db" ]]; then
    echo "a production database already exists; --import is ignored so it is not replaced"
  else
    # .backup gives a consistent copy even if the development instance still had the file open.
    sqlite3 "$IMPORT/homestart.db" ".backup '$DATA/homestart.db'"
    chown "$SERVICE_USER:$SERVICE_USER" "$DATA/homestart.db"
    chmod 640 "$DATA/homestart.db"
    if [[ -d "$IMPORT/icons" ]]; then
      cp -a "$IMPORT/icons/." "$DATA/icons/"
    fi
    echo "imported the database and icons from $IMPORT"
    if [[ -f "$IMPORT/homestart.key" && ! -f "$CONF/homestart.key" ]]; then
      # Stored Tasmota and Škoda logins can only be read with the key they were encrypted with.
      install -m 640 -o root -g "$SERVICE_USER" "$IMPORT/homestart.key" "$CONF/homestart.key"
      echo "imported the encryption key"
    fi
  fi
fi
if [[ ! -f "$CONF/homestart.key" ]]; then
  head -c 32 /dev/urandom | base64 > "$CONF/homestart.key"
  chown root:"$SERVICE_USER" "$CONF/homestart.key"
  chmod 640 "$CONF/homestart.key"
  echo "created a new encryption key in $CONF/homestart.key"
fi

if [[ $FIREWALL -eq 1 ]]; then
  step "Firewall (ports 8000 and 1883 from the local network only)"
  # The network of the address used for the default route, e.g. 192.168.x.0/24.
  LAN="$("$APP/venv/bin/python" - <<'PY'
import ipaddress, subprocess
route = subprocess.run(["ip", "-4", "route", "get", "192.0.2.1"], capture_output=True, text=True, check=True).stdout.split()
source = route[route.index("src") + 1]
for line in subprocess.run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True, check=True).stdout.splitlines():
    fields = line.split()
    address = fields[fields.index("inet") + 1]
    if address.split("/")[0] == source:
        print(ipaddress.ip_interface(address).network)
PY
)"
  [[ -n "$LAN" ]] || fail "could not determine the local network"
  cat > "$CONF/firewall.nft" <<EOF
#!/usr/sbin/nft -f
# HomeStart: web (8000) and MQTT (1883) only from the local network $LAN.
# A separate table, so rules of other programs are not touched. Loaded by homestart-firewall.service.
table inet homestart
delete table inet homestart
table inet homestart {
  chain input {
    type filter hook input priority filter - 10; policy accept;
    iif "lo" accept
    tcp dport { 8000, 1883 } ip saddr $LAN accept
    tcp dport { 8000, 1883 } ip6 saddr fe80::/10 accept
    tcp dport { 8000, 1883 } drop
  }
}
EOF
  chmod 644 "$CONF/firewall.nft"
  nft -c -f "$CONF/firewall.nft"
  cp "$APP/deploy/homestart-firewall.service" /etc/systemd/system/
  echo "allowed network: $LAN"
fi

# Imported files keep the modes of the development folder; only the service account needs them.
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA/icons" "$DATA/cache"
chmod -R u=rwX,g=rX,o= "$DATA/icons" "$DATA/cache"

step "systemd services"
cp "$APP/deploy/homestart.service" "$APP/deploy/homestart-backup.service" "$APP/deploy/homestart-backup.timer" /etc/systemd/system/
systemctl daemon-reload
if [[ $FIREWALL -eq 1 ]]; then
  systemctl enable homestart-firewall.service
  systemctl restart homestart-firewall.service
fi
systemctl enable homestart.service homestart-backup.timer
systemctl restart homestart.service
systemctl start homestart-backup.timer

step "Check"
for _ in $(seq 1 30); do
  if curl -fs -o /dev/null http://127.0.0.1:8000/login; then
    echo "HomeStart answers on port 8000"
    systemctl start homestart-backup.service && echo "first database backup made in $BACKUPS"
    journalctl -u homestart -n 6 --no-pager -o cat
    echo
    echo "Done. Open http://$(hostname -I | awk '{print $1}'):8000"
    exit 0
  fi
  sleep 1
done
journalctl -u homestart -n 40 --no-pager -o cat
fail "HomeStart did not start; see the log above (journalctl -u homestart)"
