from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_PATH = os.environ.get("DB_PATH", "/data/kasse/kasse.db")

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
                type      TEXT    NOT NULL DEFAULT 'ausgabe',
                created   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # type Spalte nachrüsten falls DB schon existiert
        try:
            conn.execute("ALTER TABLE transactions ADD COLUMN type TEXT NOT NULL DEFAULT 'ausgabe'")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS gehalt (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                amount      REAL    NOT NULL DEFAULT 0,
                gueltig_ab  TEXT    NOT NULL DEFAULT '2000-01-01',
                updated     TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # gueltig_ab nachrüsten falls Tabelle schon existiert
        try:
            conn.execute("ALTER TABLE gehalt ADD COLUMN gueltig_ab TEXT NOT NULL DEFAULT '2000-01-01'")
            # Bestehenden Eintrag auf Anfang setzen damit er immer greift
            conn.execute("UPDATE gehalt SET gueltig_ab='2000-01-01' WHERE gueltig_ab IS NULL OR gueltig_ab=''")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fixkosten (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    NOT NULL,
                amount    REAL    NOT NULL,
                category  TEXT    NOT NULL DEFAULT 'sonstiges',
                active    INTEGER NOT NULL DEFAULT 1,
                frequency TEXT    NOT NULL DEFAULT 'monthly',
                due_month INTEGER DEFAULT NULL,
                created   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # migrate existing fixkosten table
        for col, definition in [
            ('frequency', "TEXT NOT NULL DEFAULT 'monthly'"),
            ('due_month', 'INTEGER DEFAULT NULL'),
        ]:
            try:
                conn.execute(f'ALTER TABLE fixkosten ADD COLUMN {col} {definition}')
            except Exception:
                pass
        conn.commit()

# ─── HEALTH ───────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "db": DB_PATH})

# ─── TRANSACTIONS ─────────────────────────────────────────────
@app.route("/api/transactions", methods=["GET"])
def get_transactions():
    month   = request.args.get("month")
    year    = request.args.get("year")
    tx_type = request.args.get("type")

    base    = "SELECT * FROM transactions"
    filters = []
    params  = []

    if month:
        filters.append("strftime('%Y-%m', date) = ?")
        params.append(month)
    elif year:
        filters.append("strftime('%Y', date) = ?")
        params.append(year)
    if tx_type:
        filters.append("type = ?")
        params.append(tx_type)

    query = base
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY date DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/transactions", methods=["POST"])
def add_transaction():
    data     = request.json or {}
    name     = data.get("name")   or request.args.get("name")
    amount   = data.get("amount") or request.args.get("amount")
    date     = data.get("date")   or request.args.get("date")   or datetime.today().strftime("%Y-%m-%d")
    category = data.get("cat")    or request.args.get("cat")    or "sonstiges"
    payment  = data.get("pay")    or request.args.get("pay")    or "karte"
    tx_type  = data.get("type")   or request.args.get("type")   or "ausgabe"

    if not name or amount is None:
        return jsonify({"error": "name and amount required"}), 400
    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO transactions (name, amount, date, category, payment, type) VALUES (?,?,?,?,?,?)",
            (name, amount, date, category, payment, tx_type)
        )
        conn.commit()
    return jsonify({"id": cur.lastrowid, "name": name, "amount": amount,
                    "date": date, "category": category, "payment": payment, "type": tx_type}), 201


@app.route("/api/transactions/<int:tx_id>", methods=["PATCH"])
def update_transaction(tx_id):
    data     = request.json or {}
    with get_db() as conn:
        row = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        name    = data.get("name",    row["name"])
        amount  = data.get("amount",  row["amount"])
        date    = data.get("date",    row["date"])
        category= data.get("cat",     row["category"])
        payment = data.get("pay",     row["payment"])
        tx_type = data.get("type",    row["type"])
        try:
            amount = float(str(amount).replace(",", "."))
        except ValueError:
            return jsonify({"error": "invalid amount"}), 400
        conn.execute(
            "UPDATE transactions SET name=?,amount=?,date=?,category=?,payment=?,type=? WHERE id=?",
            (name, amount, date, category, payment, tx_type, tx_id)
        )
        conn.commit()
    return jsonify({"id": tx_id, "name": name, "amount": amount,
                    "date": date, "category": category, "payment": payment, "type": tx_type})


@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def delete_transaction(tx_id):
    with get_db() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
    return jsonify({"deleted": tx_id})

# ─── GEHALT ───────────────────────────────────────────────────

# GET /api/gehalt?month=2026-04  → Gehalt für diesen Monat
# GET /api/gehalt/verlauf        → alle Einträge
@app.route("/api/gehalt", methods=["GET"])
def get_gehalt():
    month = request.args.get("month")  # "2026-04"
    with get_db() as conn:
        if month:
            # Letzter Eintrag dessen gueltig_ab <= erster Tag des Monats
            month_start = month + "-01"
            row = conn.execute("""
                SELECT * FROM gehalt
                WHERE gueltig_ab <= ?
                ORDER BY gueltig_ab DESC LIMIT 1
            """, (month_start,)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM gehalt ORDER BY gueltig_ab DESC LIMIT 1"
            ).fetchone()
    return jsonify({"amount": row["amount"] if row else 0,
                    "gueltig_ab": row["gueltig_ab"] if row else None})


@app.route("/api/gehalt/verlauf", methods=["GET"])
def get_gehalt_verlauf():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM gehalt ORDER BY gueltig_ab DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# POST /api/gehalt  → neuen Eintrag hinzufügen
@app.route("/api/gehalt", methods=["POST"])
def set_gehalt():
    data       = request.json or {}
    amount     = data.get("amount", 0)
    gueltig_ab = data.get("gueltig_ab") or datetime.today().strftime("%Y-%m-01")

    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    # Sicherstellen dass gueltig_ab immer der 1. des Monats ist
    if len(gueltig_ab) == 7:  # "2026-04" → "2026-04-01"
        gueltig_ab = gueltig_ab + "-01"

    with get_db() as conn:
        # Doppelten Eintrag für gleichen Monat verhindern — überschreiben
        existing = conn.execute(
            "SELECT id FROM gehalt WHERE gueltig_ab = ?", (gueltig_ab,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE gehalt SET amount=?, updated=datetime('now') WHERE gueltig_ab=?",
                (amount, gueltig_ab)
            )
        else:
            conn.execute(
                "INSERT INTO gehalt (amount, gueltig_ab) VALUES (?,?)",
                (amount, gueltig_ab)
            )
        conn.commit()
    return jsonify({"amount": amount, "gueltig_ab": gueltig_ab})


# DELETE /api/gehalt/<id>
@app.route("/api/gehalt/<int:g_id>", methods=["DELETE"])
def delete_gehalt(g_id):
    with get_db() as conn:
        conn.execute("DELETE FROM gehalt WHERE id=?", (g_id,))
        conn.commit()
    return jsonify({"deleted": g_id})

# ─── FIXKOSTEN ────────────────────────────────────────────────
@app.route("/api/fixkosten", methods=["GET"])
def get_fixkosten():
    only_active = request.args.get("active", "false").lower() == "true"
    with get_db() as conn:
        if only_active:
            rows = conn.execute("SELECT * FROM fixkosten WHERE active=1 ORDER BY amount DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM fixkosten ORDER BY active DESC, amount DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/fixkosten", methods=["POST"])
def add_fixkosten():
    data     = request.json or {}
    name      = data.get("name")
    amount    = data.get("amount")
    category  = data.get("category", "sonstiges")
    frequency = data.get("frequency", "monthly")
    due_month = data.get("due_month", None)
    if not name or amount is None:
        return jsonify({"error": "name and amount required"}), 400
    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400
    if frequency == "yearly" and due_month:
        try:
            due_month = int(due_month)
        except (ValueError, TypeError):
            due_month = None
    else:
        due_month = None
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO fixkosten (name, amount, category, frequency, due_month) VALUES (?,?,?,?,?)",
            (name, amount, category, frequency, due_month)
        )
        conn.commit()
    return jsonify({"id": cur.lastrowid, "name": name, "amount": amount,
                    "category": category, "frequency": frequency, "due_month": due_month}), 201


@app.route("/api/fixkosten/<int:fk_id>", methods=["PATCH"])
def update_fixkosten(fk_id):
    data = request.json or {}
    with get_db() as conn:
        row = conn.execute("SELECT * FROM fixkosten WHERE id=?", (fk_id,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        name      = data.get("name",      row["name"])
        amount    = data.get("amount",    row["amount"])
        category  = data.get("category",  row["category"])
        active    = data.get("active",    row["active"])
        frequency = data.get("frequency", row["frequency"] if row["frequency"] else "monthly")
        due_month = data.get("due_month", row["due_month"])
        try:
            amount = float(str(amount).replace(",", "."))
        except ValueError:
            return jsonify({"error": "invalid amount"}), 400
        conn.execute(
            "UPDATE fixkosten SET name=?, amount=?, category=?, active=?, frequency=?, due_month=? WHERE id=?",
            (name, amount, category, active, frequency, due_month, fk_id)
        )
        conn.commit()
    return jsonify({"id": fk_id, "name": name, "amount": amount, "category": category,
                    "active": active, "frequency": frequency, "due_month": due_month})


@app.route("/api/fixkosten/<int:fk_id>", methods=["DELETE"])
def delete_fixkosten(fk_id):
    with get_db() as conn:
        conn.execute("DELETE FROM fixkosten WHERE id=?", (fk_id,))
        conn.commit()
    return jsonify({"deleted": fk_id})

# ─── STATS ────────────────────────────────────────────────────
@app.route("/api/stats/months")
def stats_months():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                strftime('%Y-%m', date) AS month,
                COUNT(*) AS count,
                ROUND(SUM(CASE WHEN type='ausgabe'  THEN amount ELSE 0 END), 2) AS total,
                ROUND(SUM(CASE WHEN type='einnahme' THEN amount ELSE 0 END), 2) AS einnahmen,
                ROUND(SUM(CASE WHEN payment='karte' AND type='ausgabe' THEN amount ELSE 0 END), 2) AS card,
                ROUND(SUM(CASE WHEN payment='bar'   AND type='ausgabe' THEN amount ELSE 0 END), 2) AS cash
            FROM transactions
            GROUP BY month ORDER BY month DESC
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats/categories")
def stats_categories():
    month = request.args.get("month")
    year  = request.args.get("year")
    with get_db() as conn:
        if month:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions WHERE strftime('%Y-%m', date)=? AND type='ausgabe'
                GROUP BY category ORDER BY total DESC
            """, (month,)).fetchall()
        elif year:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions WHERE strftime('%Y', date)=? AND type='ausgabe'
                GROUP BY category ORDER BY total DESC
            """, (year,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT category, ROUND(SUM(amount),2) AS total, COUNT(*) AS count
                FROM transactions WHERE type='ausgabe'
                GROUP BY category ORDER BY total DESC
            """).fetchall()
    return jsonify([dict(r) for r in rows])

# ─── EXPORT ───────────────────────────────────────────────────
@app.route("/api/export")
def export_csv():
    month = request.args.get("month")
    year  = request.args.get("year")
    with get_db() as conn:
        if month:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y-%m', date)=? ORDER BY type, date DESC", (month,)
            ).fetchall()
        elif year:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE strftime('%Y', date)=? ORDER BY type, date DESC", (year,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM transactions ORDER BY type, date DESC").fetchall()

        month_start = (month + "-01") if month else datetime.today().strftime("%Y-%m-01")
        gehalt_row = conn.execute("""
            SELECT amount FROM gehalt WHERE gueltig_ab <= ?
            ORDER BY gueltig_ab DESC LIMIT 1
        """, (month_start,)).fetchone()
        gehalt = gehalt_row["amount"] if gehalt_row else 0
        fixkosten  = conn.execute("SELECT * FROM fixkosten WHERE active=1 ORDER BY amount DESC").fetchall()

    ausgaben  = [r for r in rows if r["type"] == "ausgabe"]
    einnahmen = [r for r in rows if r["type"] == "einnahme"]
    label     = month or year or "gesamt"

    lines = ["\ufeffDatum,Beschreibung,Betrag,Kategorie,Zahlungsart,Typ"]
    for r in ausgaben:
        lines.append(f'{r["date"]},"{r["name"]}",-{r["amount"]},{r["category"]},{r["payment"]},Ausgabe')

    if einnahmen:
        lines.append("")
        lines.append(",EINNAHMEN,,,,")
        for r in einnahmen:
            lines.append(f'{r["date"]},"{r["name"]}",+{r["amount"]},{r["category"]},,Einnahme')

    if fixkosten:
        lines.append("")
        lines.append(",FIXKOSTEN,,,,")
        fk_total = 0
        for fk in fixkosten:
            lines.append(f'fix,"{fk["name"]}",-{fk["amount"]},{fk["category"]},,Fix')
            fk_total += fk["amount"]
        lines.append(f',,{-fk_total:.2f},TOTAL FIXKOSTEN,,')

    total_ausgaben  = sum(r["amount"] for r in ausgaben)
    total_einnahmen = sum(r["amount"] for r in einnahmen)
    total_fix       = sum(fk["amount"] for fk in fixkosten)
    verfuegbar      = gehalt + total_einnahmen - total_fix - total_ausgaben

    lines.append("")
    lines.append(",ZUSAMMENFASSUNG,,,,")
    lines.append(f',Fixgehalt,+{gehalt:.2f},,,,')
    lines.append(f',Variable Einnahmen,+{total_einnahmen:.2f},,,,')
    lines.append(f',Fixkosten,-{total_fix:.2f},,,,')
    lines.append(f',Variable Ausgaben,-{total_ausgaben:.2f},,,,')
    lines.append(f',Verfügbar,{verfuegbar:.2f},,,,')

    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="kasse_{label}.csv"'}
    )

# ─── SHORTCUT ─────────────────────────────────────────────────
@app.route("/api/shortcut")
def shortcut_add():
    name     = request.args.get("name")
    amount   = request.args.get("amount")
    date     = request.args.get("date") or datetime.today().strftime("%Y-%m-%d")
    category = request.args.get("cat")  or "sonstiges"
    payment  = request.args.get("pay")  or "karte"

    if not name or not amount:
        return jsonify({"error": "name and amount required"}), 400
    try:
        amount = float(str(amount).replace(",", "."))
    except ValueError:
        return jsonify({"error": "invalid amount"}), 400

    with get_db() as conn:
        conn.execute(
            "INSERT INTO transactions (name, amount, date, category, payment, type) VALUES (?,?,?,?,?,?)",
            (name, amount, date, category, payment, "ausgabe")
        )
        conn.commit()
    return f"✓ {name} {amount:.2f}€ ({payment}) erfasst", 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
