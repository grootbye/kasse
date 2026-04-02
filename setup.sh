#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Kasse Setup Script — Ubuntu/Debian VM
# Ausführen als root: bash setup.sh
# ─────────────────────────────────────────────────────────────
set -e

echo "══════════════════════════════════════"
echo "  Kasse — Setup"
echo "══════════════════════════════════════"

# 1. Pakete
apt-get update -q
apt-get install -y python3 python3-venv python3-pip nginx

# 2. Verzeichnisse
mkdir -p /opt/kasse/backend
mkdir -p /opt/kasse/frontend
mkdir -p /data/kasse
mkdir -p /var/log/kasse

# 3. Dateien kopieren (aus dem gleichen Verzeichnis wie dieses Script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/backend/app.py"           /opt/kasse/backend/
cp "$SCRIPT_DIR/backend/requirements.txt" /opt/kasse/backend/
cp "$SCRIPT_DIR/frontend/index.html"      /opt/kasse/frontend/
cp "$SCRIPT_DIR/nginx/kasse.conf"         /etc/nginx/sites-available/kasse

# 4. Python venv + dependencies
python3 -m venv /opt/kasse/venv
/opt/kasse/venv/bin/pip install -q -r /opt/kasse/backend/requirements.txt

# 5. Datenbank initialisieren
DB_PATH=/data/kasse/kasse.db /opt/kasse/venv/bin/python3 -c "
import sys; sys.path.insert(0, '/opt/kasse/backend')
from app import init_db; init_db()
print('  ✓ Datenbank erstellt: /data/kasse/kasse.db')
"

# 6. Berechtigungen
chown -R www-data:www-data /data/kasse /var/log/kasse /opt/kasse

# 7. systemd service
cp "$SCRIPT_DIR/kasse.service" /etc/systemd/system/kasse.service
systemctl daemon-reload
systemctl enable kasse
systemctl start kasse
sleep 2
systemctl is-active --quiet kasse && echo "  ✓ Flask Service läuft" || echo "  ✗ Service Fehler — check: journalctl -u kasse"

# 8. nginx
ln -sf /etc/nginx/sites-available/kasse /etc/nginx/sites-enabled/kasse
nginx -t && systemctl reload nginx && echo "  ✓ nginx neu geladen"

echo ""
echo "══════════════════════════════════════"
echo "  Fertig!"
echo ""
echo "  → http://kasse.local  (nach DNS/hosts Eintrag)"
echo "  → oder direkt: http://$(hostname -I | awk '{print $1}')"
echo ""
echo "  Shortcut API URL:"
echo "  http://$(hostname -I | awk '{print $1}')/api/shortcut?name=Rewe&amount=12.50&cat=einkauf&pay=karte"
echo "══════════════════════════════════════"
