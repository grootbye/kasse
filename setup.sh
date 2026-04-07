#!/bin/bash
# ─────────────────────────────────────────────────────────────
# ka$se Setup Script — Ubuntu/Debian (Proxmox VM)
# Run as root: bash setup.sh
#
# Also works as an UPDATE — re-run anytime to deploy new files.
# Existing data in /data/kasse/kasse.db is never touched.
# ─────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VM_IP=$(hostname -I | awk '{print $1}')

echo "══════════════════════════════════════════"
echo "  ka\$se — Setup / Update"
echo "  $(date '+%Y-%m-%d %H:%M')"
echo "══════════════════════════════════════════"

# ─── 1. System packages ───────────────────────────────────────
echo ""
echo "▸ Installing packages..."
apt-get update -q
apt-get install -y python3 python3-venv python3-pip nginx sqlite3

# ─── 2. Directories ───────────────────────────────────────────
echo "▸ Creating directories..."
mkdir -p /opt/kasse/backend
mkdir -p /opt/kasse/frontend
mkdir -p /data/kasse
mkdir -p /data/kasse/backups
mkdir -p /var/log/kasse

# ─── 3. Copy files ────────────────────────────────────────────
echo "▸ Deploying files..."
cp "$SCRIPT_DIR/backend/app.py"           /opt/kasse/backend/
cp "$SCRIPT_DIR/backend/requirements.txt" /opt/kasse/backend/
cp "$SCRIPT_DIR/frontend/index.html"      /opt/kasse/frontend/
cp "$SCRIPT_DIR/nginx/kasse.conf"         /etc/nginx/sites-available/kasse
cp "$SCRIPT_DIR/kasse.service"            /etc/systemd/system/kasse.service

# Copy favicon if present
if [ -f "$SCRIPT_DIR/frontend/favicon.ico" ]; then
  cp "$SCRIPT_DIR/frontend/favicon.ico" /opt/kasse/frontend/
  echo "  ✓ favicon.ico deployed"
fi
if [ -f "$SCRIPT_DIR/frontend/favicon.svg" ]; then
  cp "$SCRIPT_DIR/frontend/favicon.svg" /opt/kasse/frontend/
  echo "  ✓ favicon.svg deployed"
fi

# ─── 4. Python venv ───────────────────────────────────────────
echo "▸ Setting up Python environment..."
if [ ! -d "/opt/kasse/venv" ]; then
  python3 -m venv /opt/kasse/venv
  echo "  ✓ venv created"
else
  echo "  ✓ venv exists, skipping"
fi
/opt/kasse/venv/bin/pip install -q -r /opt/kasse/backend/requirements.txt
echo "  ✓ dependencies installed"

# ─── 5. Database init / migrate ───────────────────────────────
echo "▸ Initializing database..."
chown -R www-data:www-data /data/kasse /var/log/kasse /opt/kasse

sudo -u www-data DB_PATH=/data/kasse/kasse.db /opt/kasse/venv/bin/python3 -c "
import sys; sys.path.insert(0, '/opt/kasse/backend')
from app import init_db; init_db()
print('  ✓ Database ready: /data/kasse/kasse.db')
"

# ─── 6. systemd service ───────────────────────────────────────
echo "▸ Configuring systemd service..."
systemctl daemon-reload
systemctl enable kasse

if systemctl is-active --quiet kasse; then
  systemctl restart kasse
  echo "  ✓ Service restarted"
else
  systemctl start kasse
  echo "  ✓ Service started"
fi

sleep 2
systemctl is-active --quiet kasse \
  && echo "  ✓ Flask running (port 5000)" \
  || echo "  ✗ Service error — check: journalctl -u kasse -n 20"

# ─── 7. nginx ─────────────────────────────────────────────────
echo "▸ Configuring nginx..."

# Disable default site if active
if [ -L /etc/nginx/sites-enabled/default ]; then
  rm /etc/nginx/sites-enabled/default
  echo "  ✓ Default site disabled"
fi

ln -sf /etc/nginx/sites-available/kasse /etc/nginx/sites-enabled/kasse

if nginx -t 2>/dev/null; then
  systemctl reload nginx
  echo "  ✓ nginx reloaded"
else
  echo "  ✗ nginx config error:"
  nginx -t
fi

# ─── 8. Health check ──────────────────────────────────────────
echo ""
echo "▸ Health check..."
sleep 1
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/api/health)
if [ "$HTTP" = "200" ]; then
  echo "  ✓ API responding (HTTP 200)"
else
  echo "  ✗ API not responding (HTTP $HTTP) — check logs"
fi

# ─── 9. Auto backup cronjob ───────────────────────────────────
if ! crontab -l 2>/dev/null | grep -q "kasse.db"; then
  (crontab -l 2>/dev/null; echo "0 3 * * * cp /data/kasse/kasse.db /data/kasse/backups/kasse_\$(date +\%Y\%m\%d).db 2>/dev/null") | crontab -
  echo "▸ Daily backup cronjob added (3am)"
fi

# ─── Done ─────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Done!"
echo ""
echo "  App:      http://$VM_IP"
echo "  API:      http://$VM_IP/api/health"
echo "  DB:       /data/kasse/kasse.db"
echo "  Logs:     journalctl -u kasse -f"
echo ""
echo "  Shortcut URL:"
echo "  http://$VM_IP/api/shortcut?name=Rewe&amount=12.50&cat=essen&pay=karte"
echo "══════════════════════════════════════════"
