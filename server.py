#!/usr/bin/env python3
"""TPY Inventory — ระบบเบิกสินค้าคลังโรงพยาบาลตาพระยา

ใช้แค่ Python standard library (http.server + sqlite3) ไม่ต้องติดตั้งไลบรารีเพิ่ม
รัน:  python server.py --open   แล้วเปิด http://127.0.0.1:8000
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import sys
import traceback
import webbrowser
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.environ.get("INVENTORY_DB", BASE_DIR / "data" / "inventory.db"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
SESSION_HOURS = 12
COOKIE_NAME = "tpy_session"
MAX_BODY = 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL COLLATE NOCASE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'dept')),
    department_id INTEGER REFERENCES departments(id),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    unit TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 0,
    min_qty REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS requisitions (
    id INTEGER PRIMARY KEY,
    doc_no TEXT UNIQUE NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    requester_name TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    approver_name TEXT,
    approved_at TEXT,
    reject_reason TEXT,
    issuer_name TEXT,
    receiver_name TEXT,
    issued_at TEXT
);
CREATE TABLE IF NOT EXISTS requisition_lines (
    id INTEGER PRIMARY KEY,
    requisition_id INTEGER NOT NULL REFERENCES requisitions(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id),
    qty_requested REAL NOT NULL,
    qty_approved REAL,
    qty_issued REAL
);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES items(id),
    delta REAL NOT NULL,
    balance REAL NOT NULL,
    reason TEXT NOT NULL,
    requisition_id INTEGER REFERENCES requisitions(id),
    user_id INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_req_status ON requisitions(status);
CREATE INDEX IF NOT EXISTS idx_req_dept ON requisitions(department_id);
CREATE INDEX IF NOT EXISTS idx_lines_req ON requisition_lines(requisition_id);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movements(item_id);
"""

STATUS = {
    "pending": "รออนุมัติ",
    "approved": "อนุมัติแล้ว รอจ่าย",
    "issued": "จ่ายแล้ว",
    "rejected": "ไม่อนุมัติ",
    "cancelled": "ยกเลิก",
}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Request:
    def __init__(self, conn, body, query, user):
        self.conn = conn
        self.body = body
        self.query = query
        self.user = user
        self.cookies = []

    def q(self, name, default=""):
        return (self.query.get(name) or [default])[0]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


# ---------- แปลงและตรวจค่าที่ส่งเข้ามา ----------

def to_str(value, label, required=False, max_len=200):
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise ApiError(400, f"กรุณาระบุ{label}")
        return None
    if len(text) > max_len:
        raise ApiError(400, f"{label}ยาวเกิน {max_len} ตัวอักษร")
    return text


def to_num(value, label, required=False, minimum=None):
    if value is None or value == "":
        if required:
            raise ApiError(400, f"กรุณาระบุ{label}")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{label}ต้องเป็นตัวเลข")
    if not math.isfinite(number):
        raise ApiError(400, f"{label}ต้องเป็นตัวเลข")
    if minimum is not None and number < minimum:
        raise ApiError(400, f"{label}ต้องไม่น้อยกว่า {minimum:g}")
    return number


def to_id(value, label, required=True):
    number = to_num(value, label, required)
    if number is None:
        return None
    if not number.is_integer():
        raise ApiError(400, f"{label}ไม่ถูกต้อง")
    return int(number)


def to_bool(value):
    return value in (True, 1, "1", "true", "on")


# ---------- บัญชีผู้ใช้และการล็อกอิน ----------

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, iterations, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, AttributeError):
        return False


def valid_password(password):
    password = "" if password is None else str(password)
    if len(password) < 6:
        raise ApiError(400, "รหัสผ่านต้องยาวอย่างน้อย 6 ตัวอักษร")
    return password


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(row):
    if row is None:
        return None
    user = dict(row)
    user.pop("password_hash", None)
    return user


USER_SELECT = """
    SELECT u.*, d.name AS department_name
    FROM users u LEFT JOIN departments d ON d.id = u.department_id
"""


def user_from_cookie(conn, header):
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    if COOKIE_NAME not in cookie:
        return None
    row = conn.execute(
        USER_SELECT + " JOIN sessions s ON s.user_id = u.id WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1",
        (token_hash(cookie[COOKIE_NAME].value), now())).fetchone()
    return public_user(row)


def start_session(req, user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=SESSION_HOURS)
    req.conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
    req.conn.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                     (token_hash(token), user_id, expires.isoformat(timespec="seconds")))
    req.cookies.append(f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_HOURS * 3600}")


def get_user(conn, user_id):
    row = conn.execute(USER_SELECT + " WHERE u.id = ?", (user_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ไม่พบผู้ใช้นี้")
    return public_user(row)


def setup_status(req):
    count = req.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"needs_setup": count == 0}


def setup(req):
    """สร้างบัญชีผู้ดูแลคลังคนแรก ทำได้ครั้งเดียวตอนยังไม่มีผู้ใช้"""
    if not setup_status(req)["needs_setup"]:
        raise ApiError(409, "ระบบตั้งค่าไปแล้ว")
    b = req.body
    username = to_str(b.get("username"), "ชื่อผู้ใช้", True, 50)
    full_name = to_str(b.get("full_name"), "ชื่อ-นามสกุล", True)
    password = valid_password(b.get("password"))
    user_id = req.conn.execute(
        "INSERT INTO users (username, full_name, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
        (username, full_name, hash_password(password), now())).lastrowid
    start_session(req, user_id)
    return get_user(req.conn, user_id)


def login(req):
    username = to_str(req.body.get("username"), "ชื่อผู้ใช้", True, 50)
    password = str(req.body.get("password") or "")
    row = req.conn.execute(USER_SELECT + " WHERE u.username = ?", (username,)).fetchone()
    if row is None or not check_password(password, row["password_hash"]):
        raise ApiError(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    if not row["active"]:
        raise ApiError(403, "บัญชีนี้ถูกปิดใช้งาน ติดต่อผู้ดูแลคลัง")
    start_session(req, row["id"])
    return public_user(row)


def logout(req):
    req.conn.execute("DELETE FROM sessions WHERE user_id = ?", (req.user["id"],))
    req.cookies.append(f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")
    return {"ok": True}


def me(req):
    return req.user


def change_password(req):
    row = req.conn.execute("SELECT password_hash FROM users WHERE id = ?", (req.user["id"],)).fetchone()
    if not check_password(str(req.body.get("old_password") or ""), row["password_hash"]):
        raise ApiError(400, "รหัสผ่านเดิมไม่ถูกต้อง")
    password = valid_password(req.body.get("new_password"))
    req.conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), req.user["id"]))
    return {"ok": True}


# ---------- หน่วยงาน ----------

def list_departments(req):
    where = "" if req.user["role"] == "admin" else "WHERE active = 1"
    return rows(req.conn.execute(f"SELECT * FROM departments {where} ORDER BY name"))


def save_department(req, dept_id=None):
    name = to_str(req.body.get("name"), "ชื่อหน่วยงาน", True)
    active = 1 if to_bool(req.body.get("active", True)) else 0
    try:
        if dept_id:
            if not req.conn.execute("UPDATE departments SET name = ?, active = ? WHERE id = ?",
                                    (name, active, dept_id)).rowcount:
                raise ApiError(404, "ไม่พบหน่วยงานนี้")
        else:
            dept_id = req.conn.execute("INSERT INTO departments (name, active) VALUES (?, ?)", (name, active)).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, f"มีหน่วยงานชื่อ {name} อยู่แล้ว")
    return dict(req.conn.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone())


def create_department(req):
    return save_department(req)


def update_department(req, dept_id):
    return save_department(req, dept_id)


# ---------- ผู้ใช้ ----------

def list_users(req):
    return [public_user(r) for r in req.conn.execute(USER_SELECT + " ORDER BY u.role, d.name, u.username")]


def save_user(req, user_id=None):
    b = req.body
    full_name = to_str(b.get("full_name"), "ชื่อ-นามสกุล", True)
    role = b.get("role")
    if role not in ("admin", "dept"):
        raise ApiError(400, "กรุณาเลือกสิทธิ์ผู้ใช้")
    department_id = to_id(b.get("department_id"), "หน่วยงาน", required=role == "dept")
    if department_id is not None and not req.conn.execute(
            "SELECT 1 FROM departments WHERE id = ?", (department_id,)).fetchone():
        raise ApiError(400, "ไม่พบหน่วยงานที่เลือก")
    active = 1 if to_bool(b.get("active", True)) else 0
    password = b.get("password")
    if user_id:
        if user_id == req.user["id"] and (role != "admin" or not active):
            raise ApiError(400, "ไม่สามารถลดสิทธิ์หรือปิดบัญชีของตัวเองได้")
        get_user(req.conn, user_id)
        req.conn.execute("UPDATE users SET full_name = ?, role = ?, department_id = ?, active = ? WHERE id = ?",
                         (full_name, role, department_id, active, user_id))
        if password:
            req.conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (hash_password(valid_password(password)), user_id))
            req.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        if not active:
            req.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    else:
        username = to_str(b.get("username"), "ชื่อผู้ใช้", True, 50)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", username):
            raise ApiError(400, "ชื่อผู้ใช้ใช้ได้เฉพาะตัวอักษรอังกฤษ ตัวเลข . _ -")
        try:
            user_id = req.conn.execute(
                "INSERT INTO users (username, full_name, password_hash, role, department_id, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, full_name, hash_password(valid_password(password)), role, department_id, active, now()),
            ).lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, f"ชื่อผู้ใช้ {username} มีอยู่แล้ว")
    return get_user(req.conn, user_id)


def create_user(req):
    return save_user(req)


def update_user(req, user_id):
    return save_user(req, user_id)


# ---------- สินค้าและสต็อก ----------

def get_item(conn, item_id):
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ไม่พบสินค้านี้")
    return dict(row)


def change_stock(req, item_id, delta, reason, requisition_id=None):
    req.conn.execute("UPDATE items SET qty = qty + ? WHERE id = ?", (delta, item_id))
    balance = req.conn.execute("SELECT qty FROM items WHERE id = ?", (item_id,)).fetchone()[0]
    req.conn.execute(
        "INSERT INTO movements (ts, item_id, delta, balance, reason, requisition_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now(), item_id, delta, balance, reason, requisition_id, req.user["id"]))


def list_items(req):
    if req.user["role"] == "admin" and req.q("all") == "1":
        return rows(req.conn.execute("SELECT * FROM items ORDER BY category, name"))
    return rows(req.conn.execute("SELECT * FROM items WHERE active = 1 ORDER BY category, name"))


def item_values(body):
    return {
        "code": to_str(body.get("code"), "รหัสสินค้า", True, 50),
        "name": to_str(body.get("name"), "ชื่อสินค้า", True),
        "category": to_str(body.get("category"), "หมวดหมู่"),
        "unit": to_str(body.get("unit"), "หน่วย", True, 30),
        "min_qty": to_num(body.get("min_qty"), "จุดสั่งซื้อ", minimum=0) or 0,
        "active": 1 if to_bool(body.get("active", True)) else 0,
    }


def create_item(req):
    values = item_values(req.body)
    initial = to_num(req.body.get("initial_qty"), "ยอดยกมา", minimum=0)
    try:
        item_id = req.conn.execute(
            f"INSERT INTO items ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            list(values.values())).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัสสินค้า {values['code']} มีอยู่แล้ว")
    if initial:
        change_stock(req, item_id, initial, "ยอดยกมา")
    return get_item(req.conn, item_id)


def update_item(req, item_id):
    get_item(req.conn, item_id)
    values = item_values(req.body)
    try:
        req.conn.execute(f"UPDATE items SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                         [*values.values(), item_id])
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัสสินค้า {values['code']} มีอยู่แล้ว")
    return get_item(req.conn, item_id)


def adjust_item(req, item_id):
    item = get_item(req.conn, item_id)
    delta = to_num(req.body.get("delta"), "จำนวน", True)
    if delta == 0:
        raise ApiError(400, "จำนวนต้องไม่เป็นศูนย์")
    if item["qty"] + delta < 0:
        raise ApiError(409, f"สต็อกไม่พอ (คงเหลือ {item['qty']:g} {item['unit']})")
    reason = to_str(req.body.get("reason"), "หมายเหตุ") or ("รับเข้า" if delta > 0 else "ปรับลด")
    change_stock(req, item_id, delta, reason)
    return get_item(req.conn, item_id)


def list_movements(req):
    params, where = [], []
    item_id = req.q("item_id")
    if item_id.isdigit():
        where.append("m.item_id = ?")
        params.append(int(item_id))
    limit = max(1, min(int(req.q("limit", "500")) if req.q("limit", "500").isdigit() else 500, 5000))
    return rows(req.conn.execute(
        f"""SELECT m.*, i.code, i.name, i.unit, u.full_name AS user_name, r.doc_no
            FROM movements m
            JOIN items i ON i.id = m.item_id
            LEFT JOIN users u ON u.id = m.user_id
            LEFT JOIN requisitions r ON r.id = m.requisition_id
            {'WHERE ' + ' AND '.join(where) if where else ''}
            ORDER BY m.id DESC LIMIT ?""", [*params, limit]))


# ---------- ใบเบิก ----------

REQ_SELECT = """
    SELECT r.*, d.name AS department_name, u.full_name AS created_by_name,
           (SELECT COUNT(*) FROM requisition_lines l WHERE l.requisition_id = r.id) AS line_count
    FROM requisitions r
    JOIN departments d ON d.id = r.department_id
    JOIN users u ON u.id = r.created_by
"""


def get_requisition(req, req_id):
    row = req.conn.execute(REQ_SELECT + " WHERE r.id = ?", (req_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ไม่พบใบเบิกนี้")
    doc = dict(row)
    if req.user["role"] != "admin" and doc["department_id"] != req.user["department_id"]:
        raise ApiError(404, "ไม่พบใบเบิกนี้")
    doc["lines"] = rows(req.conn.execute(
        """SELECT l.*, i.code, i.name, i.unit, i.qty AS stock
           FROM requisition_lines l JOIN items i ON i.id = l.item_id
           WHERE l.requisition_id = ? ORDER BY l.id""", (req_id,)))
    return doc


def list_requisitions(req):
    where, params = [], []
    if req.user["role"] != "admin":
        where.append("r.department_id = ?")
        params.append(req.user["department_id"])
    elif req.q("department_id").isdigit():
        where.append("r.department_id = ?")
        params.append(int(req.q("department_id")))
    if req.q("status") in STATUS:
        where.append("r.status = ?")
        params.append(req.q("status"))
    return rows(req.conn.execute(
        REQ_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT 1000", params))


def get_requisition_endpoint(req, req_id):
    return get_requisition(req, req_id)


def next_doc_no(conn):
    year = datetime.now().year + 543  # ปี พ.ศ.
    prefix = f"REQ{year}-"
    last = conn.execute("SELECT doc_no FROM requisitions WHERE doc_no LIKE ? ORDER BY doc_no DESC LIMIT 1",
                        (prefix + "%",)).fetchone()
    seq = int(last[0].rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def create_requisition(req):
    b = req.body
    if req.user["role"] == "admin":
        department_id = to_id(b.get("department_id"), "หน่วยงาน")
    else:
        department_id = req.user["department_id"]
    if not department_id or not req.conn.execute(
            "SELECT 1 FROM departments WHERE id = ? AND active = 1", (department_id,)).fetchone():
        raise ApiError(400, "บัญชีนี้ยังไม่ได้ผูกกับหน่วยงาน ติดต่อผู้ดูแลคลัง")
    requester = to_str(b.get("requester_name"), "ชื่อผู้เบิก", True)
    note = to_str(b.get("note"), "หมายเหตุ", max_len=500)
    lines = {}
    for entry in b.get("lines") or []:
        item_id = to_id(entry.get("item_id"), "สินค้า")
        qty = to_num(entry.get("qty"), "จำนวนที่เบิก", True)
        if qty <= 0:
            raise ApiError(400, "จำนวนที่เบิกต้องมากกว่า 0")
        item = get_item(req.conn, item_id)
        if not item["active"]:
            raise ApiError(400, f"สินค้า {item['name']} งดเบิกแล้ว")
        lines[item_id] = lines.get(item_id, 0) + qty
    if not lines:
        raise ApiError(400, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ")
    req_id = req.conn.execute(
        "INSERT INTO requisitions (doc_no, department_id, created_by, requester_name, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (next_doc_no(req.conn), department_id, req.user["id"], requester, note, now())).lastrowid
    req.conn.executemany("INSERT INTO requisition_lines (requisition_id, item_id, qty_requested) VALUES (?, ?, ?)",
                         [(req_id, item_id, qty) for item_id, qty in lines.items()])
    return get_requisition(req, req_id)


def require_status(doc, *allowed):
    if doc["status"] not in allowed:
        raise ApiError(409, f"ใบเบิกนี้อยู่ในสถานะ \"{STATUS[doc['status']]}\" ทำรายการนี้ไม่ได้")


def line_quantities(doc, entries, field, default_field):
    """อ่านจำนวนรายบรรทัดจากที่ส่งมา ถ้าไม่ส่งมาใช้ค่าจาก default_field"""
    given = {}
    for entry in entries or []:
        line_id = to_id(entry.get("line_id"), "รายการ")
        given[line_id] = to_num(entry.get(field), "จำนวน", True, minimum=0)
    result = {}
    for line in doc["lines"]:
        qty = given.get(line["id"], line[default_field])
        if qty > line["qty_requested"]:
            raise ApiError(400, f"{line['name']}: จำนวนต้องไม่เกินที่ขอเบิก ({line['qty_requested']:g} {line['unit']})")
        result[line["id"]] = qty
    return result


def approve_requisition(req, req_id):
    doc = get_requisition(req, req_id)
    require_status(doc, "pending")
    approver = to_str(req.body.get("approver_name"), "ชื่อผู้อนุมัติ", True)
    qtys = line_quantities(doc, req.body.get("lines"), "qty_approved", "qty_requested")
    if not any(qtys.values()):
        raise ApiError(400, "อนุมัติ 0 ทุกรายการ ให้ใช้ปุ่ม \"ไม่อนุมัติ\" แทน")
    for line_id, qty in qtys.items():
        req.conn.execute("UPDATE requisition_lines SET qty_approved = ? WHERE id = ?", (qty, line_id))
    req.conn.execute("UPDATE requisitions SET status = 'approved', approver_name = ?, approved_at = ? WHERE id = ?",
                     (approver, now(), req_id))
    return get_requisition(req, req_id)


def reject_requisition(req, req_id):
    doc = get_requisition(req, req_id)
    require_status(doc, "pending", "approved")
    approver = to_str(req.body.get("approver_name"), "ชื่อผู้อนุมัติ", True)
    reason = to_str(req.body.get("reason"), "เหตุผล", True, 500)
    req.conn.execute(
        "UPDATE requisitions SET status = 'rejected', approver_name = ?, approved_at = ?, reject_reason = ? WHERE id = ?",
        (approver, now(), reason, req_id))
    return get_requisition(req, req_id)


def issue_requisition(req, req_id):
    """จ่ายของ: ตัดสต็อกตามจำนวนที่จ่ายจริง"""
    doc = get_requisition(req, req_id)
    require_status(doc, "approved")
    issuer = to_str(req.body.get("issuer_name"), "ชื่อผู้จ่าย", True)
    receiver = to_str(req.body.get("receiver_name"), "ชื่อผู้รับ", True)
    qtys = line_quantities(doc, req.body.get("lines"), "qty_issued", "qty_approved")
    short = []
    for line in doc["lines"]:
        qty = qtys[line["id"]]
        if qty > line["qty_approved"]:
            raise ApiError(400, f"{line['name']}: จ่ายเกินจำนวนที่อนุมัติ ({line['qty_approved']:g} {line['unit']})")
        if qty > line["stock"]:
            short.append(f"{line['name']} ต้องจ่าย {qty:g} คงเหลือ {line['stock']:g} {line['unit']}")
    if short:
        raise ApiError(409, "สต็อกไม่พอ: " + ", ".join(short))
    for line in doc["lines"]:
        qty = qtys[line["id"]]
        req.conn.execute("UPDATE requisition_lines SET qty_issued = ? WHERE id = ?", (qty, line["id"]))
        if qty:
            change_stock(req, line["item_id"], -qty, f"จ่ายตามใบเบิก {doc['doc_no']} ({doc['department_name']})", req_id)
    req.conn.execute(
        "UPDATE requisitions SET status = 'issued', issuer_name = ?, receiver_name = ?, issued_at = ? WHERE id = ?",
        (issuer, receiver, now(), req_id))
    return get_requisition(req, req_id)


def cancel_requisition(req, req_id):
    doc = get_requisition(req, req_id)
    require_status(doc, "pending")
    req.conn.execute("UPDATE requisitions SET status = 'cancelled' WHERE id = ?", (req_id,))
    return get_requisition(req, req_id)


# ---------- ภาพรวม ----------

def summary(req):
    conn = req.conn
    return {
        "status_counts": {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM requisitions GROUP BY status")},
        "item_count": conn.execute("SELECT COUNT(*) FROM items WHERE active = 1").fetchone()[0],
        "department_count": conn.execute("SELECT COUNT(*) FROM departments WHERE active = 1").fetchone()[0],
        "low_stock": rows(conn.execute(
            "SELECT * FROM items WHERE active = 1 AND min_qty > 0 AND qty <= min_qty ORDER BY qty / min_qty, name")),
        "waiting": rows(conn.execute(
            REQ_SELECT + " WHERE r.status IN ('pending', 'approved') ORDER BY r.id")),
        "top_items": rows(conn.execute(
            """SELECT i.code, i.name, i.unit, SUM(-m.delta) AS issued
               FROM movements m JOIN items i ON i.id = m.item_id
               WHERE m.requisition_id IS NOT NULL AND m.ts >= ?
               GROUP BY m.item_id ORDER BY issued DESC LIMIT 10""",
            ((datetime.now() - timedelta(days=30)).isoformat(timespec="seconds"),))),
    }


# ---------- เส้นทาง API ----------

ROUTES = []


def route(method, pattern, handler, access="user"):
    """access: public = ไม่ต้องล็อกอิน, user = ผู้ใช้ทุกคน, admin = ผู้ดูแลคลังเท่านั้น"""
    ROUTES.append((method, re.compile(f"^/api{pattern}$"), handler, access))


ID = r"(\d+)"
route("GET", "/setup", setup_status, "public")
route("POST", "/setup", setup, "public")
route("POST", "/login", login, "public")
route("POST", "/logout", logout)
route("GET", "/me", me)
route("POST", "/me/password", change_password)
route("GET", "/departments", list_departments)
route("POST", "/departments", create_department, "admin")
route("PUT", f"/departments/{ID}", update_department, "admin")
route("GET", "/users", list_users, "admin")
route("POST", "/users", create_user, "admin")
route("PUT", f"/users/{ID}", update_user, "admin")
route("GET", "/items", list_items)
route("POST", "/items", create_item, "admin")
route("PUT", f"/items/{ID}", update_item, "admin")
route("POST", f"/items/{ID}/adjust", adjust_item, "admin")
route("GET", "/movements", list_movements, "admin")
route("GET", "/requisitions", list_requisitions)
route("POST", "/requisitions", create_requisition)
route("GET", f"/requisitions/{ID}", get_requisition_endpoint)
route("POST", f"/requisitions/{ID}/cancel", cancel_requisition)
route("POST", f"/requisitions/{ID}/approve", approve_requisition, "admin")
route("POST", f"/requisitions/{ID}/reject", reject_requisition, "admin")
route("POST", f"/requisitions/{ID}/issue", issue_requisition, "admin")
route("GET", "/summary", summary, "admin")

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TPYInventory/2.0"

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def dispatch(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self.send_json(405, {"error": "Method not allowed"})
            return self.serve_static(url.path)
        cookies = []
        try:
            if method != "GET" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                raise ApiError(415, "ต้องส่งข้อมูลเป็น JSON")
            body = self.read_json() if method != "GET" else {}
            for route_method, pattern, handler, access in ROUTES:
                match = pattern.match(url.path)
                if route_method != method or not match:
                    continue
                conn = connect()
                try:
                    with conn:
                        req = Request(conn, body, parse_qs(url.query), user_from_cookie(conn, self.headers.get("Cookie")))
                        if access != "public" and req.user is None:
                            raise ApiError(401, "กรุณาเข้าสู่ระบบ")
                        if access == "admin" and req.user["role"] != "admin":
                            raise ApiError(403, "เฉพาะผู้ดูแลคลังเท่านั้น")
                        result = handler(req, *[int(g) for g in match.groups()])
                        cookies = req.cookies
                finally:
                    conn.close()
                return self.send_json(200, result, cookies)
            raise ApiError(404, "ไม่พบ API นี้")
        except ApiError as err:
            self.send_json(err.status, {"error": err.message})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"error": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "ข้อมูลใหญ่เกินไป")
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "ข้อมูลที่ส่งมาไม่ใช่ JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "ข้อมูลที่ส่งมาต้องเป็น JSON object")
        return data

    def send_json(self, status, payload, cookies=()):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path):
        target = (STATIC_DIR / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(STATIC_DIR) or not target.is_file():
            return self.send_json(404, {"error": "ไม่พบหน้านี้"})
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        if "--quiet" not in sys.argv:
            super().log_message(fmt, *args)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PORT}"
    print(f"TPY Inventory กำลังทำงานที่ {url}  (กด Ctrl+C เพื่อหยุด)")
    print(f"ฐานข้อมูล: {DB_PATH}")
    if "--open" in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nหยุดระบบแล้ว")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
