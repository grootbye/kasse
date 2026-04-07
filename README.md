ka$se — Personal Expense Tracker
> **groot's first major AI project** — built entirely with Claude, April 2026.
>
> A self-hosted expense tracker running on a VM. No cloud, no subscriptions, no ads. Just a Flask API, a SQLite database, nginx, and a single HTML file that does everything.
---
Tech Stack
```
iPhone (Apple Shortcuts)
  │
  │  HTTP GET → /api/shortcut?name=Rewe&amount=12.50&cat=essen&pay=karte
  ▼
Heimnetzwerk
  │
  ▼
Proxmox VM
  │
  ▼
nginx (Port 80)
  ├── /        → /opt/kasse/frontend/index.html  (static SPA)
  └── /api/    → Flask Backend (127.0.0.1:5000)
                      │
                      ▼
                  SQLite DB
                  /data/kasse/kasse.db
```
Stack: Python · Flask · gunicorn · SQLite · nginx · Vanilla JS · Apple Shortcuts
---
Features
Tracker — log expenses and income with category, payment method, date
Budget — monthly budget overview with salary history, fixed costs (monthly & yearly), variable income
Analytics — monthly bar chart, per-month category breakdown, year overview
Apple Shortcuts — automatic tracking via Sparkasse push notifications, manual shortcut for card/cash/online
Settings — manage categories, set defaults, switch themes (Default, Monochrome, Amber, Blue & Coral)
Edit / Delete — tap the pencil icon on any transaction to edit
CSV Export — per month or full year, includes fixed costs and budget summary
---
Project Structure
```
/opt/kasse/
├── backend/
│   ├── app.py              # Flask REST API
│   └── requirements.txt
├── frontend/
│   └── index.html          # Complete SPA — one file, no framework
└── venv/                   # Python virtual environment

/data/kasse/
└── kasse.db                # SQLite database — all data lives here

/var/log/kasse/
├── access.log
└── error.log

/etc/nginx/sites-available/kasse
/etc/systemd/system/kasse.service
```
---
Setup (on the VM as root)
```bash
scp -r ./kasse root@DEINE-VM-IP:/tmp/
ssh root@DEINE-VM-IP
bash /tmp/kasse/setup.sh
```
After setup, init or migrate the database:
```bash
sudo -u www-data DB_PATH=/data/kasse/kasse.db /opt/kasse/venv/bin/python3 -c "
import sys; sys.path.insert(0, '/opt/kasse/backend')
from app import init_db; init_db()
print('Done')
"
```
Deploy updated files:
```bash
scp app.py root@IP:/opt/kasse/backend/app.py
scp index.html root@IP:/opt/kasse/frontend/index.html
ssh root@IP "systemctl restart kasse"
```
---
How It Works
Request flow
iPhone or browser sends HTTP request to `http://192.168.178.107`
nginx receives it on port 80
nginx routes:
`/api/*` → proxied to Flask on `127.0.0.1:5000`
everything else → static file from `/opt/kasse/frontend/`
Frontend → Backend
The frontend (`index.html`) runs in the browser and makes `fetch()` calls to `/api/...` using relative paths — works regardless of IP or domain.
Backend → Database
Flask opens a SQLite connection per request, reads/writes `/data/kasse/kasse.db`, then closes it. SQLite is a file, not a server — no daemon, no port, backup = copy the file.
Apple Shortcut → Backend (direct)
The shortcut calls `/api/shortcut` via GET — no JSON body needed. Flask returns plain text so Siri can read it aloud.
---
Components
Component	Role	Port
nginx	Reverse proxy + static file server	80 (public)
Flask + gunicorn	REST API, 2 workers	5000 (localhost only)
SQLite	Database	— (file)
index.html	Single Page App	— (static)
Why gunicorn instead of `flask run`? Production-grade multi-threading and crash recovery. `flask run` is dev-only.
Why SQLite instead of PostgreSQL? One file, trivial backup, zero overhead. More than enough for a single-user personal tracker.
---
Database
Tables
`transactions`
Column	Type	Description
`id`	INTEGER	Auto-increment PK
`name`	TEXT	Description (e.g. "Rewe")
`amount`	REAL	Amount as decimal
`date`	TEXT	`YYYY-MM-DD`
`category`	TEXT	Category id (e.g. `essen`)
`payment`	TEXT	`karte` · `bar` · `online` · `sonstiges`
`type`	TEXT	`ausgabe` or `einnahme`
`created`	TEXT	Insert timestamp
`gehalt` — salary history with `gueltig_ab` date. Budget uses the most recent entry on or before the viewed month.
`fixkosten` — fixed costs with `frequency` (monthly/yearly) and `due_month` (1–12). Only counted in the budget for their due month.
Direct DB access
```bash
sqlite3 /data/kasse/kasse.db

SELECT * FROM transactions ORDER BY date DESC;
SELECT * FROM transactions WHERE strftime('%Y-%m', date) = '2026-04';
UPDATE transactions SET category='essen' WHERE category='Essen';
.tables
.quit
```
---
API Reference
Base URL: `http://192.168.178.107`
Transactions
Method	Endpoint	Description
GET	`/api/transactions?month=2026-04`	List by month
GET	`/api/transactions?year=2026`	List by year
POST	`/api/transactions`	Add transaction
PATCH	`/api/transactions/<id>`	Edit transaction
DELETE	`/api/transactions/<id>`	Delete transaction
Budget
Method	Endpoint	Description
GET	`/api/gehalt?month=2026-04`	Salary for given month
GET	`/api/gehalt/verlauf`	Full salary history
POST	`/api/gehalt`	Add salary entry `{amount, gueltig_ab}`
DELETE	`/api/gehalt/<id>`	Remove salary entry
GET	`/api/fixkosten`	List fixed costs
POST	`/api/fixkosten`	Add fixed cost
PATCH	`/api/fixkosten/<id>`	Edit / pause fixed cost
DELETE	`/api/fixkosten/<id>`	Delete fixed cost
Stats & Export
Method	Endpoint	Description
GET	`/api/stats/months`	All months with totals
GET	`/api/stats/categories?month=`	Category breakdown
GET	`/api/export?month=`	CSV download
GET	`/api/shortcut?name=X&amount=X&cat=X&pay=X`	Apple Shortcut endpoint
GET	`/api/health`	Health check
Shortcut URL
```
http://192.168.178.107/api/shortcut?name=Rewe&amount=12.50&cat=essen&pay=karte
```
Param	Required	Values
`name`	✅	any text
`amount`	✅	`12.50` or `12,50`
`cat`	❌	category id (default: `sonstiges`)
`pay`	❌	`karte` · `bar` · `online` · `sonstiges`
`date`	❌	`YYYY-MM-DD` (default: today)
---
Apple Shortcuts
Manual Shortcut
```
1. Ask for Input  → Number → "Wieviel? (€)"     → Variable: betrag
2. Ask for Input  → Text   → "Wo? (z.B. Rewe)"  → Variable: desc
3. List           → essen, auto, einkauf, unterhaltung, gesundheit, wohnen, sonstiges
4. Choose from List → Input: step 3 list         → Set Variable: category
5. List           → karte, bar, online, sonstiges
6. Choose from List → Input: step 5 list         → Set Variable: zahlungsart
7. URL → http://192.168.178.107/api/shortcut?name=[desc]&amount=[betrag]&cat=[category]&pay=[zahlungsart]
8. Get Contents of URL → GET
```
> Always use `Set Variable` after `Choose from List` — otherwise the variable holds the entire list, not the selected item.
Automatic Shortcut (Sparkasse push)
Trigger: Automations → App → S-Banking → Is Opened
```
1. Get Latest Message from App → S-Banking           → Variable: mitteilung
2. Match Text                  → Regex: \d+[.,]\d{2} → Variable: matches
3. Get Item from List          → First Item           → Variable: rohbetrag
4. Replace Text                → Find: ,  Replace: .  → Variable: betrag
5. URL → http://192.168.178.107/api/shortcut?name=Sparkasse&amount=[betrag]&cat=sonstiges&pay=karte
6. Get Contents of URL → GET
```
Turn off "Ask Before Running" — otherwise iOS prompts on every notification.
Prerequisite: Settings → Notifications → S-Banking → Allow + Show Previews: Always.
---
nginx Config
```nginx
server {
    listen 80;
    server_name kasse.local;

    root /opt/kasse/frontend;
    index index.html;

    location /api/ {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_read_timeout 30;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```
```bash
nginx -t && systemctl reload nginx
```
---
Maintenance
```bash
# Status
systemctl status kasse
systemctl status nginx
curl http://localhost/api/health

# Logs
journalctl -u kasse -f
tail -f /var/log/kasse/access.log

# Restart after code changes
systemctl restart kasse
```
Common problems
Problem	Fix
404 on `/api/`	`nginx -t` → `systemctl reload nginx`
502 Bad Gateway	`systemctl restart kasse`
Page stuck loading	Run `init_db()` as www-data (DB migration missing)
Category always `sonstiges`	Check Shortcut variable, must be lowercase
---
Backup
```bash
# Manual
cp /data/kasse/kasse.db /backup/kasse_$(date +%Y%m%d).db

# Automatic daily cronjob (crontab -e)
0 3 * * * cp /data/kasse/kasse.db /backup/kasse_$(date +\%Y\%m\%d).db

# Restore
systemctl stop kasse
cp /backup/kasse_20260401.db /data/kasse/kasse.db
chown www-data:www-data /data/kasse/kasse.db
systemctl start kasse
```
---
Adjustments
Categories — managed directly in the Settings modal in the UI. No code changes needed.
Change IP:
```bash
nano /etc/nginx/sites-available/kasse  # update server_name
systemctl reload nginx
# Update Shortcut URL on iPhone manually
```
More gunicorn workers:
```bash
nano /etc/systemd/system/kasse.service  # --workers 2 → --workers 4
systemctl daemon-reload && systemctl restart kasse
```
---
groot's first major AI project — built with Claude, April 2026
