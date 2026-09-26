#!/usr/bin/env python3
"""งานบริหารเวชภัณฑ์ (คลังกลาง) รพ.ตาพระยา — ระบบเบิกยา เวชภัณฑ์ และพัสดุ

ใช้แค่ Python standard library (http.server + sqlite3) ไม่ต้องติดตั้งไลบรารีเพิ่ม
รัน:      python server.py --open      แล้วเปิด http://127.0.0.1:8000
สำรองข้อมูล: python server.py --backup
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import traceback
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.environ.get("CENTRAL_STORE_DB", BASE_DIR / "data" / "central-store.db"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", DB_PATH.parent / "backups"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# ตั้งเป็น 1 เมื่อเปิดผ่าน HTTPS (เช่นหลัง reverse proxy) คุกกี้จะถูกส่งเฉพาะทาง HTTPS
COOKIE_SECURE = os.environ.get("HTTPS", "0") == "1"
SESSION_HOURS = float(os.environ.get("SESSION_HOURS", "12"))
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
PBKDF2_ROUNDS = 200_000
MAX_BODY = 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS warehouses (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    initials TEXT NOT NULL,
    hue INTEGER NOT NULL DEFAULT 175,
    description TEXT
);
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    group_name TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,          -- เลขบัตรประชาชน 13 หลัก
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'dept')),
    department_id INTEGER REFERENCES departments(id),
    active INTEGER NOT NULL DEFAULT 1,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
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
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    unit TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 0 CHECK (qty >= 0),
    min_qty REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
-- ทะเบียนผู้เกี่ยวข้อง: requester = ผู้เบิกสินค้า, receiver = ผู้รับสินค้า, central = เจ้าหน้าที่คลังกลาง
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('requester', 'receiver', 'central')),
    full_name TEXT NOT NULL,
    position TEXT,
    department_id INTEGER REFERENCES departments(id)
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('dept', 'central')),
    UNIQUE (name, scope)
);
CREATE TABLE IF NOT EXISTS requisitions (
    id INTEGER PRIMARY KEY,
    doc_no TEXT UNIQUE NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    created_by INTEGER NOT NULL REFERENCES users(id),
    req_type TEXT NOT NULL CHECK (req_type IN ('emergency', 'routine')),
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    requester_name TEXT NOT NULL, requester_position TEXT,
    approver_name TEXT, approver_position TEXT,
    issuer_name TEXT, issuer_position TEXT,
    receiver_name TEXT, receiver_position TEXT,
    reject_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    approved_at TEXT,
    issued_at TEXT
);
CREATE TABLE IF NOT EXISTS lines (
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
    reason TEXT,
    requisition_id INTEGER REFERENCES requisitions(id),
    user_id INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_req_dept ON requisitions(department_id, status);
CREATE INDEX IF NOT EXISTS idx_req_created ON requisitions(created_at);
CREATE INDEX IF NOT EXISTS idx_lines_req ON lines(requisition_id);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movements(item_id);
"""

DEFAULT_WAREHOUSES = [
    ("DRG", "คลังยา", "ยา", 175, "ยาเม็ด ยาน้ำ ยาฉีด และยาใช้ภายนอก"),
    ("MED", "คลังเวชภัณฑ์มิใช่ยา", "วช", 172, "ถุงมือ สำลี ผ้าก๊อซ กระบอกฉีดยา และวัสดุการแพทย์"),
    ("HRB", "คลังยาสมุนไพร", "สม", 145, "ยาสมุนไพรและผลิตภัณฑ์แพทย์แผนไทย"),
    ("LAB", "คลังเทคนิคการแพทย์", "ทน", 220, "น้ำยาตรวจ และวัสดุห้องปฏิบัติการ"),
    ("DEN", "คลังทันตกรรม", "ทต", 260, "วัสดุและอุปกรณ์สิ้นเปลืองงานทันตกรรม"),
    ("SUP", "คลังพัสดุ", "พด", 40, "วัสดุสำนักงาน วัสดุงานบ้าน และวัสดุทั่วไป"),
]
DEFAULT_POSITIONS = {
    "dept": ["พยาบาลวิชาชีพชำนาญการ", "พยาบาลวิชาชีพปฏิบัติการ", "หัวหน้างาน", "เจ้าพนักงานธุรการ",
             "ผู้ช่วยเหลือคนไข้", "นักเทคนิคการแพทย์", "ทันตแพทย์", "ผู้ช่วยทันตแพทย์", "พนักงานทั่วไป"],
    "central": ["เภสัชกรชำนาญการพิเศษ", "เภสัชกรชำนาญการ", "เภสัชกรปฏิบัติการ", "เจ้าพนักงานเภสัชกรรม", "เจ้าพนักงานพัสดุ"],
}
STATUS = {"pending": "รออนุมัติ", "approved": "อนุมัติแล้ว รอจ่าย", "issued": "จ่ายแล้ว", "rejected": "ไม่อนุมัติ", "cancelled": "ยกเลิก"}
ROLE_FIELDS = ["requester_position", "approver_name", "approver_position", "issuer_name", "issuer_position",
               "receiver_name", "receiver_position"]


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Ctx:
    """ข้อมูลของคำขอหนึ่งครั้ง: ฐานข้อมูล ผู้ใช้ที่ล็อกอิน และคุกกี้ที่จะส่งกลับ"""

    def __init__(self, conn, user, token=None):
        self.conn = conn
        self.user = user
        self.token = token
        self.cookie = None
        self.commit_on_error = False  # เช่น บันทึกจำนวนครั้งที่ใส่รหัสผิดแม้จะตอบ error

    @property
    def admin(self):
        return bool(self.user) and self.user["role"] == "admin"

    def require_admin(self):
        if not self.admin:
            raise ApiError(403, "หน้านี้สำหรับผู้ดูแลคลังกลางเท่านั้น")


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM warehouses").fetchone():
            conn.executemany("INSERT INTO warehouses (code, name, initials, hue, description) VALUES (?, ?, ?, ?, ?)",
                             DEFAULT_WAREHOUSES)
        if not conn.execute("SELECT 1 FROM positions").fetchone():
            conn.executemany("INSERT INTO positions (name, scope) VALUES (?, ?)",
                             [(n, s) for s, names in DEFAULT_POSITIONS.items() for n in names])
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    finally:
        conn.close()


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def one(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


# ---------- ตรวจข้อมูลที่ส่งมา ----------

def text(value, label, required=False):
    s = str(value if value is not None else "").strip()
    if required and not s:
        raise ApiError(400, f"กรุณาระบุ{label}")
    return s or None


def number(value, label, required=False, minimum=None):
    if value is None or value == "":
        if required:
            raise ApiError(400, f"กรุณาระบุ{label}")
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{label}ต้องเป็นตัวเลข")
    if n != n or n in (float("inf"), float("-inf")):
        raise ApiError(400, f"{label}ต้องเป็นตัวเลข")
    if minimum is not None and n < minimum:
        raise ApiError(400, f"{label}ต้องไม่น้อยกว่า {minimum:g}")
    return n


def flag(value):
    return 0 if value is False or value in (0, "0", "false") else 1


def national_id(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 13:
        raise ApiError(400, "เลขบัตรประชาชนต้องมี 13 หลัก")
    check = (11 - sum(int(d) * (13 - i) for i, d in enumerate(digits[:12])) % 11) % 10
    if check != int(digits[12]):
        raise ApiError(400, "เลขบัตรประชาชนไม่ถูกต้อง (ตรวจหลักสุดท้ายไม่ผ่าน)")
    return digits


# ---------- รหัสผ่านและ session ----------

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, AttributeError):
        return False


# รหัสผ่านตามนโยบาย: เลข 5 ตัวท้ายของบัตรประชาชน
def default_password(username):
    return username[-5:]


DUMMY_HASH = hash_password("00000")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(conn, token):
    if not token:
        return None
    user = one(conn, """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                        WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""", (token_hash(token), now()))
    return user


def public_user(conn, u):
    d = one(conn, "SELECT name, code FROM departments WHERE id = ?", (u["department_id"],)) if u["department_id"] else None
    return {"id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"],
            "department_id": u["department_id"], "active": u["active"],
            "department_name": d["name"] if d else None, "department_code": d["code"] if d else None}


def start_session(ctx, user):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    ctx.conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (token_hash(token), user["id"], expires))
    ctx.cookie = session_cookie(token, int(SESSION_HOURS * 3600))


def session_cookie(value, max_age):
    return (f"sid={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
            + ("; Secure" if COOKIE_SECURE else ""))


# ---------- เข้าสู่ระบบ ----------

def setup_status(ctx, body, query):
    return {"needs_setup": not ctx.conn.execute("SELECT 1 FROM users").fetchone()}


def setup(ctx, body, query):
    if ctx.conn.execute("SELECT 1 FROM users").fetchone():
        raise ApiError(409, "ตั้งค่าระบบไปแล้ว")
    username = national_id(body.get("username"))
    full_name = text(body.get("full_name"), "ชื่อ-นามสกุล", True)
    cur = ctx.conn.execute("INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                           (username, hash_password(default_password(username)), full_name))
    ctx.conn.execute("INSERT INTO people (kind, full_name, position) VALUES ('central', ?, NULL)", (full_name,))
    user = one(ctx.conn, "SELECT * FROM users WHERE id = ?", (cur.lastrowid,))
    start_session(ctx, user)
    return public_user(ctx.conn, user)


def login(ctx, body, query):
    username = re.sub(r"\D", "", str(body.get("username") or ""))
    password = str(body.get("password") or "")
    user = one(ctx.conn, "SELECT * FROM users WHERE username = ?", (username,))
    fail = ApiError(401, "เลขบัตรประชาชนหรือรหัสผ่านไม่ถูกต้อง")
    if not user:
        check_password(password, DUMMY_HASH)  # ใช้เวลาเท่ากันไม่ว่าจะมีบัญชีหรือไม่
        raise fail
    if user["locked_until"] and user["locked_until"] > now():
        raise ApiError(429, f"ใส่รหัสผ่านผิดหลายครั้ง บัญชีถูกล็อกชั่วคราว ลองใหม่หลัง {user['locked_until'][11:16]} น. หรือติดต่อเจ้าหน้าที่คลังกลาง")
    if not check_password(password, user["password_hash"]):
        failed = user["failed_logins"] + 1
        locked = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds") if failed >= MAX_FAILED_LOGINS else None
        ctx.conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                         (0 if locked else failed, locked, user["id"]))
        ctx.commit_on_error = True
        raise fail
    if not user["active"]:
        raise ApiError(403, "บัญชีนี้ถูกปิดใช้งาน ติดต่อเจ้าหน้าที่คลังกลาง")
    ctx.conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    start_session(ctx, user)
    return public_user(ctx.conn, user)


def logout(ctx, body, query):
    if ctx.token:
        ctx.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(ctx.token),))
    ctx.cookie = session_cookie("", 0)
    return {"ok": True}


def get_me(ctx, body, query):
    return public_user(ctx.conn, ctx.user)


# ---------- คลัง หน่วยงาน ผู้ใช้ ----------

def list_warehouses(ctx, body, query):
    return rows(ctx.conn.execute("SELECT * FROM warehouses ORDER BY id"))


def list_departments(ctx, body, query):
    return rows(ctx.conn.execute(f"""SELECT d.*,
        (SELECT COUNT(*) FROM people p WHERE p.kind = 'requester' AND p.department_id = d.id) AS requester_count,
        (SELECT COUNT(*) FROM people p WHERE p.kind = 'receiver' AND p.department_id = d.id) AS receiver_count
        FROM departments d {"" if ctx.admin else "WHERE d.active = 1"} ORDER BY d.code"""))


def dept_values(body):
    return (text(body.get("code"), "รหัสหน่วย", True).upper(), text(body.get("name"), "ชื่อหน่วยเบิก", True),
            text(body.get("group_name"), "กลุ่มงาน"), flag(body.get("active", True)))


def save_department(ctx, body, query, dept_id=None):
    ctx.require_admin()
    v = dept_values(body)
    try:
        if dept_id:
            if not ctx.conn.execute("UPDATE departments SET code = ?, name = ?, group_name = ?, active = ? WHERE id = ?", (*v, dept_id)).rowcount:
                raise ApiError(404, "ไม่พบหน่วยเบิกนี้")
        else:
            dept_id = ctx.conn.execute("INSERT INTO departments (code, name, group_name, active) VALUES (?, ?, ?, ?)", v).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัสหน่วย {v[0]} มีอยู่แล้ว")
    return one(ctx.conn, "SELECT * FROM departments WHERE id = ?", (dept_id,))


def list_users(ctx, body, query):
    ctx.require_admin()
    return [public_user(ctx.conn, u) for u in rows(ctx.conn.execute("SELECT * FROM users ORDER BY role, full_name"))]


def user_values(ctx, body):
    role = body.get("role")
    if role not in ("admin", "dept"):
        raise ApiError(400, "สิทธิ์ไม่ถูกต้อง")
    dept_id = int(body["department_id"]) if str(body.get("department_id") or "").isdigit() else None
    if role == "dept" and not dept_id:
        raise ApiError(400, "บัญชีหน่วยงานต้องระบุหน่วยงาน")
    if dept_id and not ctx.conn.execute("SELECT 1 FROM departments WHERE id = ?", (dept_id,)).fetchone():
        raise ApiError(400, "ไม่พบหน่วยงานนี้")
    return text(body.get("full_name"), "ชื่อ-นามสกุล", True), role, dept_id


def create_user(ctx, body, query):
    ctx.require_admin()
    username = national_id(body.get("username"))
    full_name, role, dept_id = user_values(ctx, body)
    try:
        uid = ctx.conn.execute("INSERT INTO users (username, password_hash, full_name, role, department_id) VALUES (?, ?, ?, ?, ?)",
                               (username, hash_password(default_password(username)), full_name, role, dept_id)).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, "มีบัญชีของเลขบัตรนี้แล้ว")
    return public_user(ctx.conn, one(ctx.conn, "SELECT * FROM users WHERE id = ?", (uid,)))


def update_user(ctx, body, query, user_id):
    ctx.require_admin()
    full_name, role, dept_id = user_values(ctx, body)
    active = flag(body.get("active", True))
    if not one(ctx.conn, "SELECT id FROM users WHERE id = ?", (user_id,)):
        raise ApiError(404, "ไม่พบผู้ใช้นี้")
    others = ctx.conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (user_id,)).fetchone()[0]
    if not others and (role != "admin" or not active):
        raise ApiError(409, "ต้องมีผู้ดูแลคลังกลางที่ใช้งานอยู่อย่างน้อย 1 บัญชี")
    # ปลดล็อกบัญชีไปด้วยเมื่อผู้ดูแลบันทึก
    ctx.conn.execute("UPDATE users SET full_name = ?, role = ?, department_id = ?, active = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                     (full_name, role, dept_id, active, user_id))
    if not active:
        ctx.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return public_user(ctx.conn, one(ctx.conn, "SELECT * FROM users WHERE id = ?", (user_id,)))


# ---------- ทะเบียนผู้เกี่ยวข้องและตำแหน่ง ----------

def list_people(ctx, body, query):
    sql = """SELECT p.*, d.name AS department_name FROM people p LEFT JOIN departments d ON d.id = p.department_id WHERE 1 = 1"""
    params = []
    kind = query.get("kind", [None])[0]
    dept = query.get("department_id", [None])[0]
    if kind:
        sql += " AND p.kind = ?"
        params.append(kind)
    if dept and dept.isdigit():
        sql += " AND (p.kind = 'central' OR p.department_id = ?)"
        params.append(int(dept))
    if not ctx.admin:
        sql += " AND (p.kind = 'central' OR p.department_id = ?)"
        params.append(ctx.user["department_id"])
    return rows(ctx.conn.execute(sql + " ORDER BY p.kind, d.code, p.full_name", params))


def ensure_position(conn, name, scope):
    if name:
        conn.execute("INSERT OR IGNORE INTO positions (name, scope) VALUES (?, ?)", (name, scope))


def person_values(ctx, body, kind):
    if kind not in ("requester", "receiver", "central"):
        raise ApiError(400, "ประเภททะเบียนไม่ถูกต้อง")
    if kind == "central":
        ctx.require_admin()
        dept_id = None
    else:
        dept_id = (int(body["department_id"]) if str(body.get("department_id") or "").isdigit() else None) if ctx.admin else ctx.user["department_id"]
        if not dept_id or not ctx.conn.execute("SELECT 1 FROM departments WHERE id = ?", (dept_id,)).fetchone():
            raise ApiError(400, "กรุณาเลือกหน่วยงาน")
    position = text(body.get("position"), "ตำแหน่ง")
    ensure_position(ctx.conn, position, "central" if kind == "central" else "dept")
    return text(body.get("full_name"), "ชื่อ-นามสกุล", True), position, dept_id


def get_person(ctx, person_id):
    p = one(ctx.conn, "SELECT * FROM people WHERE id = ?", (person_id,))
    if not p or (not ctx.admin and (p["kind"] == "central" or p["department_id"] != ctx.user["department_id"])):
        raise ApiError(404, "ไม่พบรายชื่อนี้")
    return p


def create_person(ctx, body, query):
    kind = body.get("kind")
    v = person_values(ctx, body, kind)
    pid = ctx.conn.execute("INSERT INTO people (kind, full_name, position, department_id) VALUES (?, ?, ?, ?)", (kind, *v)).lastrowid
    return one(ctx.conn, "SELECT * FROM people WHERE id = ?", (pid,))


def update_person(ctx, body, query, person_id):
    p = get_person(ctx, person_id)
    v = person_values(ctx, body, p["kind"])
    ctx.conn.execute("UPDATE people SET full_name = ?, position = ?, department_id = ? WHERE id = ?", (*v, person_id))
    return one(ctx.conn, "SELECT * FROM people WHERE id = ?", (person_id,))


def delete_person(ctx, body, query, person_id):
    p = get_person(ctx, person_id)
    if p["kind"] == "central":
        ctx.require_admin()
    ctx.conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
    return {"ok": True}


def list_positions(ctx, body, query):
    scope = query.get("scope", [None])[0]
    if scope:
        return rows(ctx.conn.execute("SELECT * FROM positions WHERE scope = ? ORDER BY name", (scope,)))
    return rows(ctx.conn.execute("SELECT * FROM positions ORDER BY scope, name"))


def create_position(ctx, body, query):
    scope = "central" if body.get("scope") == "central" else "dept"
    if scope == "central":
        ctx.require_admin()
    name = text(body.get("name"), "ชื่อตำแหน่ง", True)
    ensure_position(ctx.conn, name, scope)
    return one(ctx.conn, "SELECT * FROM positions WHERE name = ? AND scope = ?", (name, scope))


# ---------- สินค้าและสต็อก ----------

ITEM_SQL = "SELECT i.*, w.name AS warehouse_name FROM items i JOIN warehouses w ON w.id = i.warehouse_id"


def get_item(conn, item_id):
    item = one(conn, ITEM_SQL + " WHERE i.id = ?", (item_id,))
    if not item:
        raise ApiError(404, "ไม่พบสินค้านี้")
    return item


def list_items(ctx, body, query):
    show_all = ctx.admin and query.get("all", ["0"])[0] == "1"
    return rows(ctx.conn.execute(ITEM_SQL + ("" if show_all else " WHERE i.active = 1") + " ORDER BY i.warehouse_id, i.code"))


def item_values(ctx, body):
    wh = body.get("warehouse_id")
    if not str(wh or "").isdigit() or not ctx.conn.execute("SELECT 1 FROM warehouses WHERE id = ?", (int(wh),)).fetchone():
        raise ApiError(400, "กรุณาเลือกคลัง")
    return (text(body.get("code"), "รหัสสินค้า", True), text(body.get("name"), "ชื่อสินค้า", True), int(wh),
            text(body.get("unit"), "หน่วยนับ", True), number(body.get("min_qty"), "จุดสั่งซื้อ", minimum=0) or 0,
            flag(body.get("active", True)))


def change_stock(ctx, item_id, delta, reason, requisition_id=None):
    item = get_item(ctx.conn, item_id)
    balance = round(item["qty"] + delta, 4)
    if balance < 0:
        raise ApiError(409, f"สต็อกไม่พอ: {item['name']} คงเหลือ {item['qty']:g} {item['unit']}")
    ctx.conn.execute("UPDATE items SET qty = ? WHERE id = ?", (balance, item_id))
    ctx.conn.execute("INSERT INTO movements (ts, item_id, delta, balance, reason, requisition_id, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (now(), item_id, delta, balance, reason, requisition_id, ctx.user["id"]))


def create_item(ctx, body, query):
    ctx.require_admin()
    v = item_values(ctx, body)
    try:
        item_id = ctx.conn.execute("INSERT INTO items (code, name, warehouse_id, unit, min_qty, active) VALUES (?, ?, ?, ?, ?, ?)", v).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัสสินค้า {v[0]} มีอยู่แล้ว")
    initial = number(body.get("initial_qty"), "ยอดคงเหลือ", minimum=0)
    if initial:
        change_stock(ctx, item_id, initial, "ยอดยกมา")
    return get_item(ctx.conn, item_id)


def update_item(ctx, body, query, item_id):
    ctx.require_admin()
    get_item(ctx.conn, item_id)
    v = item_values(ctx, body)
    try:
        ctx.conn.execute("UPDATE items SET code = ?, name = ?, warehouse_id = ?, unit = ?, min_qty = ?, active = ? WHERE id = ?", (*v, item_id))
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัสสินค้า {v[0]} มีอยู่แล้ว")
    return get_item(ctx.conn, item_id)


def adjust_item(ctx, body, query, item_id):
    ctx.require_admin()
    delta = number(body.get("delta"), "จำนวน", True)
    if not delta:
        raise ApiError(400, "จำนวนต้องไม่เป็นศูนย์")
    change_stock(ctx, item_id, delta, text(body.get("reason"), "หมายเหตุ") or ("รับเข้า" if delta > 0 else "ปรับลด"))
    return get_item(ctx.conn, item_id)


def list_movements(ctx, body, query):
    ctx.require_admin()
    sql = """SELECT m.*, i.code, i.name, i.unit, u.full_name AS user_name, r.doc_no FROM movements m
             JOIN items i ON i.id = m.item_id LEFT JOIN users u ON u.id = m.user_id LEFT JOIN requisitions r ON r.id = m.requisition_id"""
    params = []
    item_id = query.get("item_id", [""])[0]
    if item_id.isdigit():
        sql += " WHERE m.item_id = ?"
        params.append(int(item_id))
    limit = query.get("limit", ["1000"])[0]
    params.append(min(int(limit), 5000) if limit.isdigit() else 1000)
    return rows(ctx.conn.execute(sql + " ORDER BY m.id DESC LIMIT ?", params))


# ---------- ใบเบิก ----------

def with_summary(conn, docs):
    """เติมชื่อหน่วยงาน จำนวนรายการ และชื่อคลังในใบเบิกให้แต่ละใบ"""
    if not docs:
        return docs
    ids = [d["id"] for d in docs]
    info = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for r in conn.execute(f"""SELECT l.requisition_id AS rid, w.id AS wid, w.name AS wname FROM lines l
                JOIN items i ON i.id = l.item_id JOIN warehouses w ON w.id = i.warehouse_id
                WHERE l.requisition_id IN ({",".join("?" * len(part))})""", part):
            entry = info.setdefault(r["rid"], {"count": 0, "wh": {}})
            entry["count"] += 1
            entry["wh"][r["wid"]] = r["wname"]
    for d in docs:
        entry = info.get(d["id"], {"count": 0, "wh": {}})
        d["line_count"] = entry["count"]
        d["warehouses"] = [entry["wh"][k] for k in sorted(entry["wh"])]
    return docs


REQ_SQL = """SELECT r.*, d.name AS department_name, d.code AS department_code, u.full_name AS created_by_name
             FROM requisitions r JOIN departments d ON d.id = r.department_id LEFT JOIN users u ON u.id = r.created_by"""


def get_req(ctx, req_id):
    doc = one(ctx.conn, REQ_SQL + " WHERE r.id = ?", (req_id,))
    if not doc or (not ctx.admin and doc["department_id"] != ctx.user["department_id"]):
        raise ApiError(404, "ไม่พบใบเบิกนี้")
    doc["lines"] = rows(ctx.conn.execute("""SELECT l.*, i.code, i.name, i.unit, i.qty AS stock, i.warehouse_id, w.name AS warehouse_name
        FROM lines l JOIN items i ON i.id = l.item_id JOIN warehouses w ON w.id = i.warehouse_id
        WHERE l.requisition_id = ? ORDER BY i.warehouse_id, i.code""", (req_id,)))
    with_summary(ctx.conn, [doc])
    return doc


def require_status(doc, *allowed):
    if doc["status"] not in allowed:
        raise ApiError(409, f'ใบเบิกนี้อยู่ในสถานะ "{STATUS[doc["status"]]}" ทำรายการนี้ไม่ได้')


def list_requisitions(ctx, body, query):
    sql, params = REQ_SQL + " WHERE 1 = 1", []
    if not ctx.admin:
        sql += " AND r.department_id = ?"
        params.append(ctx.user["department_id"])
    status = query.get("status", [""])[0]
    if status:
        sql += " AND r.status = ?"
        params.append(status)
    limit = query.get("limit", ["500"])[0]
    params.append(min(int(limit), 5000) if limit.isdigit() else 500)
    return with_summary(ctx.conn, rows(ctx.conn.execute(sql + " ORDER BY r.id DESC LIMIT ?", params)))


def board(ctx, body, query):
    ctx.require_admin()
    ids = [r[0] for r in ctx.conn.execute("SELECT id FROM requisitions WHERE status IN ('pending', 'approved') ORDER BY created_at")]
    return [get_req(ctx, i) for i in ids]


def req_values(ctx, body):
    if body.get("req_type") not in ("emergency", "routine"):
        raise ApiError(400, "กรุณาเลือกประเภทการเบิก (ฉุกเฉิน หรือ ตามรอบปกติ)")
    lines = body.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ApiError(400, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ")
    clean, seen = [], set()
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(400, "รายการสินค้าไม่ถูกต้อง")
        item = get_item(ctx.conn, line.get("item_id"))
        if not item["active"]:
            raise ApiError(400, f"{item['name']} งดเบิกอยู่")
        if item["id"] in seen:
            raise ApiError(400, f"{item['name']} ซ้ำในใบเบิก")
        seen.add(item["id"])
        qty = number(line.get("qty"), f"จำนวน{item['name']}", True)
        if qty <= 0:
            raise ApiError(400, f"{item['name']}: จำนวนต้องมากกว่า 0")
        clean.append((item["id"], qty))
    values = {"req_type": body["req_type"], "note": text(body.get("note"), "หมายเหตุ"),
              "requester_name": text(body.get("requester_name"), "ชื่อผู้เบิก", True)}
    for k in ROLE_FIELDS:
        values[k] = text(body.get(k), k)
    return values, clean


def write_lines(conn, req_id, lines):
    conn.execute("DELETE FROM lines WHERE requisition_id = ?", (req_id,))
    conn.executemany("INSERT INTO lines (requisition_id, item_id, qty_requested) VALUES (?, ?, ?)",
                     [(req_id, item_id, qty) for item_id, qty in lines])


def next_doc_no(conn):
    prefix = f"RQ{(datetime.now().year + 543) % 100:02d}-"
    last = conn.execute("SELECT doc_no FROM requisitions WHERE doc_no LIKE ? ORDER BY doc_no DESC LIMIT 1", (prefix + "%",)).fetchone()
    return f"{prefix}{(int(last[0][len(prefix):]) + 1 if last else 1):04d}"


def create_requisition(ctx, body, query):
    if ctx.admin:
        dept_id = int(body["department_id"]) if str(body.get("department_id") or "").isdigit() else None
    else:
        dept_id = ctx.user["department_id"]
    if not dept_id or not ctx.conn.execute("SELECT 1 FROM departments WHERE id = ? AND active = 1", (dept_id,)).fetchone():
        raise ApiError(400, "กรุณาเลือกหน่วยงาน")
    values, lines = req_values(ctx, body)
    values.update(doc_no=next_doc_no(ctx.conn), department_id=dept_id, created_by=ctx.user["id"], status="pending", created_at=now())
    cols = list(values)
    req_id = ctx.conn.execute(f"INSERT INTO requisitions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                              [values[c] for c in cols]).lastrowid
    write_lines(ctx.conn, req_id, lines)
    return get_req(ctx, req_id)


def update_requisition(ctx, body, query, req_id):
    require_status(get_req(ctx, req_id), "pending")
    values, lines = req_values(ctx, body)
    values["updated_at"] = now()
    ctx.conn.execute(f"UPDATE requisitions SET {', '.join(f'{c} = ?' for c in values)} WHERE id = ?", [*values.values(), req_id])
    write_lines(ctx.conn, req_id, lines)
    return get_req(ctx, req_id)


def get_requisition(ctx, body, query, req_id):
    return get_req(ctx, req_id)


def cancel_requisition(ctx, body, query, req_id):
    require_status(get_req(ctx, req_id), "pending")
    ctx.conn.execute("UPDATE requisitions SET status = 'cancelled' WHERE id = ?", (req_id,))
    return get_req(ctx, req_id)


def line_qty(doc, entries, field, fallback):
    given = {}
    for e in entries or []:
        if isinstance(e, dict) and str(e.get("line_id", "")).isdigit():
            given[int(e["line_id"])] = number(e.get(field), "จำนวน", minimum=0)
    result = {}
    for l in doc["lines"]:
        qty = given.get(l["id"])
        qty = l[fallback] if qty is None else qty
        if qty is None or qty < 0 or qty > l["qty_requested"]:
            raise ApiError(400, f"{l['name']}: จำนวนต้องอยู่ระหว่าง 0 ถึง {l['qty_requested']:g}")
        result[l["id"]] = qty
    return result


def approve_requisition(ctx, body, query, req_id):
    ctx.require_admin()
    doc = get_req(ctx, req_id)
    require_status(doc, "pending")
    approver = text(body.get("approver_name"), "ชื่อผู้อนุมัติ", True)
    qty = line_qty(doc, body.get("lines"), "qty_approved", "qty_requested")
    ctx.conn.executemany("UPDATE lines SET qty_approved = ? WHERE id = ?", [(q, lid) for lid, q in qty.items()])
    ctx.conn.execute("UPDATE requisitions SET status = 'approved', approver_name = ?, approver_position = ?, approved_at = ? WHERE id = ?",
                     (approver, text(body.get("approver_position"), "ตำแหน่ง"), now(), req_id))
    return get_req(ctx, req_id)


def unapprove_requisition(ctx, body, query, req_id):
    ctx.require_admin()
    require_status(get_req(ctx, req_id), "approved")
    ctx.conn.execute("UPDATE lines SET qty_approved = NULL WHERE requisition_id = ?", (req_id,))
    ctx.conn.execute("UPDATE requisitions SET status = 'pending', approved_at = NULL WHERE id = ?", (req_id,))
    return get_req(ctx, req_id)


def reject_requisition(ctx, body, query, req_id):
    ctx.require_admin()
    require_status(get_req(ctx, req_id), "pending", "approved")
    ctx.conn.execute("""UPDATE requisitions SET status = 'rejected', approver_name = ?, approver_position = ?, reject_reason = ?, approved_at = ?
                        WHERE id = ?""", (text(body.get("approver_name"), "ชื่อผู้พิจารณา", True), text(body.get("approver_position"), "ตำแหน่ง"),
                                         text(body.get("reason"), "เหตุผล", True), now(), req_id))
    return get_req(ctx, req_id)


def issue_requisition(ctx, body, query, req_id):
    ctx.require_admin()
    doc = get_req(ctx, req_id)
    require_status(doc, "approved")
    issuer = text(body.get("issuer_name"), "ชื่อผู้จ่าย", True)
    receiver = text(body.get("receiver_name"), "ชื่อผู้รับ", True)
    qty = line_qty(doc, body.get("lines"), "qty_issued", "qty_approved")
    short = [f"{l['name']} ต้องจ่าย {qty[l['id']]:g} คงเหลือ {l['stock']:g} {l['unit']}" for l in doc["lines"] if qty[l["id"]] > l["stock"]]
    if short:
        raise ApiError(409, "สต็อกไม่พอ: " + ", ".join(short))
    for l in doc["lines"]:
        ctx.conn.execute("UPDATE lines SET qty_issued = ? WHERE id = ?", (qty[l["id"]], l["id"]))
        if qty[l["id"]]:
            change_stock(ctx, l["item_id"], -qty[l["id"]], f"จ่ายตามใบเบิก {doc['doc_no']} ({doc['department_name']})", req_id)
    ctx.conn.execute("""UPDATE requisitions SET status = 'issued', issuer_name = ?, issuer_position = ?, receiver_name = ?, receiver_position = ?,
                        issued_at = ? WHERE id = ?""", (issuer, text(body.get("issuer_position"), "ตำแหน่ง"), receiver,
                                                       text(body.get("receiver_position"), "ตำแหน่ง"), now(), req_id))
    return get_req(ctx, req_id)


# ---------- สรุปและ Dashboard ----------

def summary(ctx, body, query):
    ctx.require_admin()
    counts = {r["status"]: r["n"] for r in ctx.conn.execute("SELECT status, COUNT(*) AS n FROM requisitions GROUP BY status")}
    return {
        "status_counts": counts,
        "low_stock": rows(ctx.conn.execute(ITEM_SQL + " WHERE i.active = 1 AND (i.qty <= 0 OR (i.min_qty > 0 AND i.qty <= i.min_qty)) ORDER BY i.qty > 0, i.qty / i.min_qty")),
        "waiting": with_summary(ctx.conn, rows(ctx.conn.execute(REQ_SQL + " WHERE r.status IN ('pending', 'approved') ORDER BY r.created_at"))),
    }


def analytics(ctx, body, query):
    weeks_n = 12
    end = datetime.now()
    start = end - timedelta(weeks=weeks_n)
    start_s = start.isoformat(timespec="seconds")
    docs = rows(ctx.conn.execute("""SELECT id, department_id, req_type, created_at, issued_at FROM requisitions
                                    WHERE created_at >= ? AND status NOT IN ('cancelled', 'rejected')""", (start_s,)))
    weeks = [{"start": (start + timedelta(weeks=i)).isoformat(timespec="seconds"), "emergency": 0, "routine": 0} for i in range(weeks_n)]
    for d in docs:
        w = min(weeks_n - 1, (datetime.fromisoformat(d["created_at"]) - start).days // 7)
        weeks[w][d["req_type"]] += 1
    issued = rows(ctx.conn.execute("""SELECT l.qty_issued, i.id AS item_id, i.name, i.unit, i.warehouse_id, w.name AS warehouse_name
        FROM lines l JOIN requisitions r ON r.id = l.requisition_id JOIN items i ON i.id = l.item_id JOIN warehouses w ON w.id = i.warehouse_id
        WHERE r.created_at >= ? AND r.status = 'issued' AND l.qty_issued > 0""", (start_s,)))
    by_wh = []
    for w in ctx.conn.execute("SELECT * FROM warehouses ORDER BY id"):
        by_wh.append({"warehouse_id": w["id"], "name": w["name"], "hue": w["hue"], "lines": sum(1 for l in issued if l["warehouse_id"] == w["id"])})
    by_wh.sort(key=lambda x: -x["lines"])
    by_dept = []
    for d in ctx.conn.execute("SELECT id, name FROM departments"):
        mine = [r for r in docs if r["department_id"] == d["id"]]
        if mine:
            by_dept.append({"name": d["name"], "total": len(mine), "emergency": sum(1 for r in mine if r["req_type"] == "emergency")})
    by_dept.sort(key=lambda x: -x["total"])
    totals = {}
    for l in issued:
        t = totals.setdefault(l["item_id"], {"name": l["name"], "unit": l["unit"], "warehouse_name": l["warehouse_name"], "qty": 0})
        t["qty"] += l["qty_issued"]
    top = sorted(totals.values(), key=lambda x: -x["qty"])[:5]

    def avg_hours(items):
        hours = [(datetime.fromisoformat(r["issued_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600 for r in items]
        return sum(hours) / len(hours) if hours else None

    done = [r for r in docs if r["issued_at"]]
    return {
        "from": start_s, "to": end.isoformat(timespec="seconds"), "weeks": weeks,
        "by_warehouse": by_wh, "by_department": by_dept[:6], "top_items": top,
        "totals": {
            "requisitions": len(docs),
            "emergency": sum(1 for r in docs if r["req_type"] == "emergency"),
            "lines_issued": len(issued),
            "avg_hours": avg_hours(done),
            "avg_hours_emergency": avg_hours([r for r in done if r["req_type"] == "emergency"]),
        },
    }


# ---------- เส้นทาง API ----------

ROUTES = []
PUBLIC = set()


def route(method, pattern, handler, public=False):
    ROUTES.append((method, re.compile(f"^/api{pattern}$"), handler))
    if public:
        PUBLIC.add(handler)


ID = r"(\d+)"
route("GET", "/setup", setup_status, public=True)
route("POST", "/setup", setup, public=True)
route("POST", "/login", login, public=True)
route("POST", "/logout", logout, public=True)
route("GET", "/me", get_me)
route("GET", "/warehouses", list_warehouses)
route("GET", "/departments", list_departments)
route("POST", "/departments", save_department)
route("PUT", f"/departments/{ID}", save_department)
route("GET", "/users", list_users)
route("POST", "/users", create_user)
route("PUT", f"/users/{ID}", update_user)
route("GET", "/people", list_people)
route("POST", "/people", create_person)
route("PUT", f"/people/{ID}", update_person)
route("DELETE", f"/people/{ID}", delete_person)
route("GET", "/positions", list_positions)
route("POST", "/positions", create_position)
route("GET", "/items", list_items)
route("POST", "/items", create_item)
route("PUT", f"/items/{ID}", update_item)
route("POST", f"/items/{ID}/adjust", adjust_item)
route("GET", "/movements", list_movements)
route("GET", "/requisitions", list_requisitions)
route("GET", "/requisitions/board", board)
route("POST", "/requisitions", create_requisition)
route("GET", f"/requisitions/{ID}", get_requisition)
route("PUT", f"/requisitions/{ID}", update_requisition)
route("POST", f"/requisitions/{ID}/cancel", cancel_requisition)
route("POST", f"/requisitions/{ID}/approve", approve_requisition)
route("POST", f"/requisitions/{ID}/unapprove", unapprove_requisition)
route("POST", f"/requisitions/{ID}/reject", reject_requisition)
route("POST", f"/requisitions/{ID}/issue", issue_requisition)
route("GET", "/summary", summary)
route("GET", "/analytics", analytics)

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "CentralStore/1.0"

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sid" and value:
                return value
        return None

    def check_origin(self):
        # ป้องกันเว็บอื่นส่งคำสั่งแทนผู้ใช้ (CSRF) นอกเหนือจากคุกกี้ SameSite=Strict
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ApiError(403, "คำขอมาจากเว็บอื่น")

    def dispatch(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self.send_json(405, {"error": "Method not allowed"})
            return self.serve_static(url.path)
        ctx = None
        conn = None
        try:
            if method != "GET":
                self.check_origin()
            body = self.read_json() if method in ("POST", "PUT") else {}
            for route_method, pattern, handler in ROUTES:
                match = pattern.match(url.path)
                if route_method != method or not match:
                    continue
                args = [int(g) for g in match.groups()]
                conn = connect()
                token = self.cookie_token()
                ctx = Ctx(conn, session_user(conn, token), token)
                if not ctx.user and handler not in PUBLIC:
                    raise ApiError(401, "กรุณาเข้าสู่ระบบ")
                # ล็อกฐานข้อมูลตั้งแต่ต้นสำหรับคำสั่งที่เขียนข้อมูล กันการตัดสต็อกซ้อนกัน
                conn.execute("BEGIN IMMEDIATE" if method != "GET" else "BEGIN")
                result = handler(ctx, body, parse_qs(url.query), *args)
                conn.execute("COMMIT")
                return self.send_json(200, result, ctx.cookie)
            raise ApiError(404, "ไม่พบ API นี้")
        except ApiError as err:
            self.finish_tx(conn, ctx)
            self.send_json(err.status, {"error": err.message}, ctx.cookie if ctx else None)
        except Exception:
            traceback.print_exc()
            self.finish_tx(conn, None)
            self.send_json(500, {"error": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"})
        finally:
            if conn:
                conn.close()

    @staticmethod
    def finish_tx(conn, ctx):
        if conn and conn.in_transaction:
            conn.execute("COMMIT" if ctx and ctx.commit_on_error else "ROLLBACK")

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

    def send_json(self, status, payload, cookie=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        if cookie:
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
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # ไม่พิมพ์คำขอไฟล์หน้าเว็บ เหลือเฉพาะ API
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def backup():
    """สำรองฐานข้อมูลแบบปลอดภัยแม้ระบบกำลังทำงาน เก็บ 30 ไฟล์ล่าสุด"""
    init_db()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"central-store-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = connect(), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(BACKUP_DIR.glob("central-store-*.db"))[:-30]:
        old.unlink()
    print(f"สำรองข้อมูลแล้ว: {target}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--backup" in sys.argv:
        return backup()
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PORT}"
    print(f"งานบริหารเวชภัณฑ์ (คลังกลาง) กำลังทำงานที่ {url}  (กด Ctrl+C เพื่อหยุด)")
    print(f"ฐานข้อมูล: {DB_PATH}")
    if HOST in ("0.0.0.0", ""):
        print("เปิดให้เครื่องอื่นในเครือข่ายเข้าได้ที่ http://<IP ของเครื่องนี้>:" + str(PORT))
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
