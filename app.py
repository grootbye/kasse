from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("DB_PATH", "/data/kasse.db")

# ─── DB INIT ──────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    NOT NULL,
                amount    REAL    NOT NULL,
                date      TEXT    NOT NULL,
                category  TEXT    NOT NULL DEFAULT 'sonstiges',
                payment   TEXT    NOT NULL DEFAULT 'karte',
                created   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

# ─── ROUTES ───────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "db": DB_PATH})


# GET  /api/transactions?month=2026-04        → alle im Monat
# GET  /api/transactions?year=2026            → alle im Jahr
# GET  /api/transactions                      → alle
@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    month = request.args.get("month")   # "2026-04"
    year  = request.args.get("year")    # "2026"

    with get_db() as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y-%m', date) = ? ORDER BY date DESC",
                (month,)
            ).fetchall()
        elif year:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y', date) = ? ORDER BY date DESC",
                (year,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY date DESC"
            ).fetchall()

    return jsonify([dict(r) for r in rows])


# POST /api/transactions
@app.route("/api/transactions", methods=["POST"])
def add_transaction():
    data = request.json or {}

    # auch URL-params supporten (für Apple Shortcut GET-Requests)
    name     = data.get("name")     or request.args.get("name")
    amount   = data.get("amount")   or request.args.get("amount")
    date     = data.get("date")     or request.args.get("date")     or datetime.today().strftime("%Y-%m-%d")
    category = data.get("cat")      or request.args.get("cat")      or "sonstiges"
    payment  = data.get("pay")      or request.args.get("pay")      or "karte"

    if not name or amount is None:
        return jsonify({"error": "name and amount required"}), 400

    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (name, amount, date, category, payment) VALUES (?,?,?,?,?)",
            (name, amount, date, category, payment)
        )
        conn.commit()
        tx_id = cur.lastrowid

    return jsonify({"id": tx_id, "name": name, "amount": amount,
                    "date": date, "category": category, "payment": payment}), 201


# DELETE /api/transactions/<id>
@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def delete_transaction(tx_id):
    with get_db() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
    return jsonify({"deleted": tx_id})


# GET /api/stats/months  → Übersicht aller Monate mit Summen
@app.route("/api/stats/months")
def stats_months():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                strftime('%Y-%m', date)  AS month,
                COUNT(*)                 AS count,
                ROUND(SUM(amount), 2)    AS total,
                ROUND(SUM(CASE WHEN payment='karte' THEN amount ELSE 0 END), 2) AS card,
                ROUND(SUM(CASE WHEN payment='bar'   THEN amount ELSE 0 END), 2) AS cash
            FROM transactions
            GROUP BY month
            ORDER BY month DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


# GET /api/stats/categories?month=2026-04  → Kategorie-Breakdown
@app.route("/api/stats/categories")
def stats_categories():
    month = request.args.get("month")
    year  = request.args.get("year")

    with get_db() as conn:
        if month:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions
                WHERE strftime('%Y-%m', date) = ?
                GROUP BY category ORDER BY total DESC
            """, (month,)).fetchall()
        elif year:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions
                WHERE strftime('%Y', date) = ?
                GROUP BY category ORDER BY total DESC
            """, (year,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions
                GROUP BY category ORDER BY total DESC
            """).fetchall()

    return jsonify([dict(r) for r in rows])


# GET /api/export?month=2026-04  → CSV download
@app.route("/api/export")
def export_csv():
    month = request.args.get("month")
    year  = request.args.get("year")

    with get_db() as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y-%m', date) = ? ORDER BY date DESC",
                (month,)
            ).fetchall()
        elif year:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y', date) = ? ORDER BY date DESC",
                (year,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM transactions ORDER BY date DESC").fetchall()

    lines = ["\ufeffDatum,Beschreibung,Betrag,Kategorie,Zahlungsart"]
    for r in rows:
        lines.append(f'{r["date"]},"{r["name"]}",{r["amount"]},{r["category"]},{r["payment"]}')

    label = month or year or "gesamt"
    from flask import Response
    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="kasse_{label}.csv"'}
    )


# GET /api/shortcut  → Apple Shortcut GET-kompatibel (kein JSON body nötig)
@app.route("/api/shortcut")
def shortcut_add():
    name     = request.args.get("name")
    amount   = request.args.get("amount")
    date     = request.args.get("date")     or datetime.today().strftime("%Y-%m-%d")
    category = request.args.get("cat")      or "sonstiges"
    payment  = request.args.get("pay")      or "karte"

    if not name or not amount:
        return jsonify({"error": "name and amount required"}), 400

    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (name, amount, date, category, payment) VALUES (?,?,?,?,?)",
            (name, amount, date, category, payment)
        )
        conn.commit()

    # Einfache Text-Antwort für Siri / Shortcuts
    return f"✓ {name} {amount:.2f}€ ({payment}) erfasst", 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
