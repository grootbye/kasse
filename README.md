# Kasse — Ausgaben Tracker

Flask + SQLite + nginx · Für Proxmox VM (Ubuntu/Debian)

## Struktur

```
kasse/
├── backend/
│   ├── app.py              # Flask API
│   └── requirements.txt
├── frontend/
│   └── index.html          # Single-Page App
├── nginx/
│   └── kasse.conf          # nginx config
├── kasse.service           # systemd
└── setup.sh                # Einmal-Setup
```

## Setup (auf der VM als root)

```bash
scp -r ./kasse root@DEINE-VM-IP:/tmp/
ssh root@DEINE-VM-IP
bash /tmp/kasse/setup.sh
```

## API Endpoints

| Method | URL | Beschreibung |
|--------|-----|---|
| GET | `/api/transactions?month=2026-04` | Alle Buchungen im Monat |
| GET | `/api/transactions?year=2026` | Alle Buchungen im Jahr |
| POST | `/api/transactions` | Neue Buchung (JSON body) |
| DELETE | `/api/transactions/<id>` | Buchung löschen |
| GET | `/api/stats/months` | Alle Monate mit Summen |
| GET | `/api/stats/categories?month=2026-04` | Kategorien-Breakdown |
| GET | `/api/export?month=2026-04` | CSV Download |
| GET | `/api/shortcut?name=X&amount=X&cat=X&pay=X` | Apple Shortcut kompatibel |

## Apple Shortcut URL

```
http://DEINE-IP/api/shortcut?name=Rewe&amount=12.50&cat=einkauf&pay=karte
```

Parameter:
- `name` — Beschreibung (required)
- `amount` — Betrag, Komma oder Punkt (required)
- `cat` — essen | transport | einkauf | unterhaltung | gesundheit | wohnen | kleidung | sonstiges
- `pay` — karte | bar
- `date` — YYYY-MM-DD (optional, default: heute)

## Kategorien

`essen` · `transport` · `einkauf` · `unterhaltung` · `gesundheit` · `wohnen` · `kleidung` · `sonstiges`

## Wartung

```bash
# Service status
systemctl status kasse

# Logs
journalctl -u kasse -f

# Datenbank direkt
sqlite3 /data/kasse/kasse.db "SELECT * FROM transactions ORDER BY date DESC LIMIT 20;"

# Backup
cp /data/kasse/kasse.db /backup/kasse_$(date +%Y%m%d).db
```

## nginx Domain anpassen

In `/etc/nginx/sites-available/kasse`:
```nginx
server_name kasse.local;  # ← auf deine interne Domain ändern
```

Dann in deinem Router / Pi-hole / /etc/hosts einen DNS-Eintrag setzen:
```
192.168.x.x    kasse.local
```
