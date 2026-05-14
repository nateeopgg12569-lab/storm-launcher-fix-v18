"""
license_server.py — Storm Launcher License API (PostgreSQL version)
สำหรับ deploy บน Railway
"""

from flask import Flask, request, jsonify
import psycopg2
import psycopg2.pool
import hashlib
import hmac
import os

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
API_SECRET   = os.environ.get("LICENSE_SECRET", "CHANGE_THIS_SECRET")
PORT         = int(os.environ.get("PORT", 7749))

pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)

def get_db():
    return pool.getconn()

def put_db(conn):
    pool.putconn(conn)

def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                key      TEXT PRIMARY KEY,
                used     INTEGER DEFAULT 0,
                used_by  TEXT DEFAULT NULL,
                hwid     TEXT DEFAULT NULL
            )
        """)
        conn.commit()
    finally:
        put_db(conn)

def verify_signature(body: bytes, sig_header: str) -> bool:
    expected = hmac.new(API_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header or "")

def error(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


@app.route("/verify", methods=["POST"])
def verify():
    raw = request.get_data()
    if not verify_signature(raw, request.headers.get("X-Signature", "")):
        return error("unauthorized", 401)

    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip().upper()
    hwid = (data.get("hwid") or "").strip()

    if not key or not hwid:
        return error("missing key or hwid")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT used, used_by, hwid FROM keys WHERE key = %s", (key,))
        row = c.fetchone()

        if row is None:          return error("invalid_key")
        if not row[0]:           return error("not_redeemed")

        existing_hwid = row[2]

        if existing_hwid is None:
            c.execute("UPDATE keys SET hwid = %s WHERE key = %s", (hwid, key))
            conn.commit()
            return jsonify({"ok": True, "message": "hwid_bound"})

        if existing_hwid == hwid:
            return jsonify({"ok": True, "message": "ok"})

        return error("hwid_mismatch")
    finally:
        put_db(conn)


@app.route("/check", methods=["POST"])
def check():
    raw = request.get_data()
    if not verify_signature(raw, request.headers.get("X-Signature", "")):
        return error("unauthorized", 401)

    data = request.get_json(silent=True) or {}
    key  = (data.get("key") or "").strip().upper()
    hwid = (data.get("hwid") or "").strip()

    if not key or not hwid:
        return error("missing key or hwid")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT used, hwid FROM keys WHERE key = %s", (key,))
        row = c.fetchone()

        if row is None:     return error("invalid_key")
        if not row[0]:      return error("not_redeemed")
        if row[1] != hwid:  return error("hwid_mismatch")

        return jsonify({"ok": True})
    finally:
        put_db(conn)


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
