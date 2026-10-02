#!/usr/bin/env python3
"""งานบริหารเวชภัณฑ์ (คลังกลาง) รพ.ตาพระยา — ระบบเบิกยา เวชภัณฑ์ และพัสดุ

ใช้แค่ Python standard library (http.server + sqlite3) ไม่ต้องติดตั้งไลบรารีเพิ่ม
รัน:      python server.py --open      แล้วเปิด http://127.0.0.1:8000
สำรองข้อมูล: python server.py --backup
"""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import sys
import traceback
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.environ.get("CENTRAL_STORE_DB", BASE_DIR / "data" / "central-store.db"))
# ระบบ รพ.สต. ใช้ฐานข้อมูลแยก (สินค้า ใบเบิก ทะเบียน ฯลฯ) ส่วนบัญชีผู้ใช้และการล็อกอินอยู่ในฐานข้อมูลหลัก
PHC_DB_PATH = Path(os.environ.get("CENTRAL_STORE_PHC_DB", DB_PATH.with_name(DB_PATH.stem + "-phc" + DB_PATH.suffix)))
DB_PATHS = {"hospital": DB_PATH, "phc": PHC_DB_PATH}
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", DB_PATH.parent / "backups"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# บังคับคุกกี้แบบ HTTPS เสมอ (ไม่จำเป็นกับ Cloudflare Tunnel เพราะระบบดูจาก X-Forwarded-Proto ให้เอง)
COOKIE_SECURE = os.environ.get("HTTPS", "0") == "1"
SESSION_HOURS = float(os.environ.get("SESSION_HOURS", "12"))
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
PBKDF2_ROUNDS = 200_000
MAX_BODY = 12 * 1024 * 1024  # ไฟล์ Excel นำเข้าสินค้า (ส่งแบบ base64)
GUIDE_MAX_MB = 8  # ไฟล์ PDF แนวทางปฏิบัติ (base64 ใหญ่ขึ้น 4/3 ยังไม่เกิน MAX_BODY)
MAX_IMPORT_ROWS = 5000

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
    locked_until TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 1   -- รหัสเริ่มต้น (5 ตัวท้าย) ต้องเปลี่ยนก่อนใช้งาน
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
CREATE TABLE IF NOT EXISTS guidelines (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    file_name TEXT,
    file_size INTEGER,
    file_data BLOB,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_req_dept ON requisitions(department_id, status);
CREATE INDEX IF NOT EXISTS idx_req_created ON requisitions(created_at);
CREATE INDEX IF NOT EXISTS idx_lines_req ON lines(requisition_id);
CREATE INDEX IF NOT EXISTS idx_mov_item ON movements(item_id);
CREATE TABLE IF NOT EXISTS stock_reports (
    id INTEGER PRIMARY KEY,
    warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
    report_at TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_data BLOB NOT NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_stock_rep ON stock_reports(warehouse_id, report_at);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    ref TEXT,
    message TEXT NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    reply TEXT,
    replied_by TEXT,
    replied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_issues_dept ON issues(department_id, created_at);
-- การใช้งานระบบ: ผู้ใช้ 1 คนนับ 1 แถวต่อชั่วโมงที่มีการใช้งาน (hour = YYYY-MM-DDTHH)
CREATE TABLE IF NOT EXISTS user_activity (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hour TEXT NOT NULL,
    PRIMARY KEY (user_id, hour)
);
CREATE INDEX IF NOT EXISTS idx_activity_hour ON user_activity(hour);
"""

DEFAULT_WAREHOUSES = [
    ("DRG", "คลังยา", "ยา", 175, "ยาเม็ด ยาน้ำ ยาฉีด และยาใช้ภายนอก"),
    ("MED", "คลังเวชภัณฑ์มิใช่ยา", "วช", 172, "ถุงมือ สำลี ผ้าก๊อซ กระบอกฉีดยา และวัสดุการแพทย์"),
    ("HRB", "คลังยาสมุนไพร", "สม", 145, "ยาสมุนไพรและผลิตภัณฑ์แพทย์แผนไทย"),
    ("LAB", "คลังเทคนิคการแพทย์", "ทน", 220, "น้ำยาตรวจ และวัสดุห้องปฏิบัติการ"),
    ("DEN", "คลังทันตกรรม", "ทต", 260, "วัสดุและอุปกรณ์สิ้นเปลืองงานทันตกรรม"),
    ("SUP", "คลังพัสดุ", "พด", 40, "วัสดุสำนักงาน วัสดุงานบ้าน และวัสดุทั่วไป"),
    ("IT", "คลังเทคโนโลยีสารสนเทศ", "ทส", 320, "คอมพิวเตอร์ อุปกรณ์ต่อพ่วง หมึกพิมพ์ และวัสดุไอที"),
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

    def __init__(self, conn, user, token=None, secure=False):
        self.conn = conn  # ฐานข้อมูลของระบบที่ล็อกอินเข้ามา (รพ. หรือ รพ.สต.)
        self.auth = conn  # ฐานข้อมูลหลัก: บัญชีผู้ใช้และเซสชัน
        self.user = user
        self.token = token
        self.secure = secure  # เปิดผ่าน HTTPS: คุกกี้ส่งเฉพาะทาง HTTPS
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


def connect(system="hospital"):
    conn = sqlite3.connect(DB_PATHS[system], timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db():
    for system in DB_PATHS:
        init_one(system)


def init_one(system):
    DB_PATHS[system].parent.mkdir(parents=True, exist_ok=True)
    conn = connect(system)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # ฐานข้อมูลที่สร้างจากรุ่นก่อน: เพิ่มคอลัมน์ใหม่ ผู้ใช้เดิมทุกคนต้องตั้งรหัสผ่านใหม่
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "must_change_password" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 1")
        # แยกระบบ รพ. / รพ.สต.: บัญชีเดิมทั้งหมดเป็นของ รพ. (ผู้ดูแลคลังกลางเข้าได้ทั้ง 2 ระบบ)
        if "system" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN system TEXT NOT NULL DEFAULT 'hospital'")
        # ราคาต่อหน่วย (บาท) ของรายการที่จ่าย ใช้ในระบบ รพ.สต.
        if "unit_price" not in {r["name"] for r in conn.execute("PRAGMA table_info(lines)")}:
            conn.execute("ALTER TABLE lines ADD COLUMN unit_price REAL")
        # ราคาในหน่วยย่อย (เบิก) ของสินค้า ใช้เป็นราคาตั้งต้นตอนจ่าย (ระบบ รพ.สต.)
        if "unit_price" not in {r["name"] for r in conn.execute("PRAGMA table_info(items)")}:
            conn.execute("ALTER TABLE items ADD COLUMN unit_price REAL")
        if "system" not in {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}:
            conn.execute("ALTER TABLE sessions ADD COLUMN system TEXT NOT NULL DEFAULT 'hospital'")
        # เพิ่มคลังตั้งต้นที่ยังไม่มี (ฐานข้อมูลเดิมได้คลังใหม่อัตโนมัติ ไม่แตะคลังที่มีอยู่)
        conn.executemany("INSERT OR IGNORE INTO warehouses (code, name, initials, hue, description) VALUES (?, ?, ?, ?, ?)",
                         DEFAULT_WAREHOUSES)
        if not conn.execute("SELECT 1 FROM positions").fetchone():
            conn.executemany("INSERT INTO positions (name, scope) VALUES (?, ?)",
                             [(n, s) for s, names in DEFAULT_POSITIONS.items() for n in names])
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        # การใช้งานระบบ: ลบข้อมูลเก่ากว่า 1 ปี และถ้ายังไม่มีข้อมูลเลย ตั้งต้นจากผู้ที่ล็อกอินค้างอยู่
        conn.execute("DELETE FROM user_activity WHERE hour < ?",
                     ((datetime.now() - timedelta(days=ACTIVITY_KEEP_DAYS)).strftime("%Y-%m-%dT%H"),))
        if not conn.execute("SELECT 1 FROM user_activity LIMIT 1").fetchone():
            for user_id, expires in conn.execute("SELECT user_id, expires_at FROM sessions").fetchall():
                start = datetime.fromisoformat(expires) - timedelta(hours=SESSION_HOURS)
                conn.execute("INSERT OR IGNORE INTO user_activity (user_id, hour) VALUES (?, ?)", (user_id, start.strftime("%Y-%m-%dT%H")))
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


# รหัสผ่านเริ่มต้น: เลข 5 ตัวท้ายของบัตรประชาชน ใช้ได้แค่ครั้งแรก แล้วต้องตั้งรหัสใหม่
def default_password(username):
    return username[-5:]


MIN_PASSWORD = 8


def check_new_password(username, password):
    if len(password) < MIN_PASSWORD:
        raise ApiError(400, f"รหัสผ่านใหม่ต้องยาวอย่างน้อย {MIN_PASSWORD} ตัวอักษร")
    if password.isdigit():
        raise ApiError(400, "รหัสผ่านใหม่ต้องมีตัวอักษรปนอยู่ด้วย ไม่ใช่ตัวเลขล้วน")
    if username[-5:] in password or password in username:
        raise ApiError(400, "รหัสผ่านใหม่ต้องไม่มีเลขบัตรประชาชนอยู่ในนั้น")


DUMMY_HASH = hash_password("00000")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(conn, token):
    if not token:
        return None
    user = one(conn, """SELECT u.*, s.system AS session_system FROM sessions s JOIN users u ON u.id = s.user_id
                        WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""", (token_hash(token), now()))
    return user


def find_department(conn, system, dept_id):
    """หน่วยเบิกในทะเบียนของระบบ (conn คือฐานข้อมูลหลัก ระบบ รพ.สต. เปิดฐานข้อมูลของตัวเอง)"""
    if not dept_id:
        return None
    if system == "hospital":
        return one(conn, "SELECT name, code FROM departments WHERE id = ?", (dept_id,))
    other = connect(system)
    try:
        return one(other, "SELECT name, code FROM departments WHERE id = ?", (dept_id,))
    finally:
        other.close()


def public_user(conn, u, session_system=None):
    d = find_department(conn, u["system"], u["department_id"])
    out = {"id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"], "system": u["system"],
           "department_id": u["department_id"], "active": u["active"], "must_change_password": u["must_change_password"],
           "department_name": d["name"] if d else None, "department_code": d["code"] if d else None}
    if session_system:
        out["session_system"] = session_system  # ระบบที่ล็อกอินเข้ามาในเซสชันนี้
    return out


ACTIVITY_KEEP_DAYS = 365
_activity_seen = set()  # (user_id, hour) ที่บันทึกแล้วในชั่วโมงนี้ กันเขียนฐานข้อมูลทุกคำขอ


def record_activity(conn, user_id, system="hospital"):
    """นับผู้ใช้ที่ใช้งานในแต่ละชั่วโมง (สำหรับ Dashboard การใช้งานระบบ)"""
    hour = datetime.now().strftime("%Y-%m-%dT%H")
    key = (user_id, hour, system)
    if key in _activity_seen:
        return
    if len(_activity_seen) > 5000 or any(k[1] != hour for k in list(_activity_seen)[:1]):
        _activity_seen.clear()
    conn.execute("INSERT OR IGNORE INTO user_activity (user_id, hour) VALUES (?, ?)", key[:2])
    _activity_seen.add(key)


MIRROR_COLS = ("id", "username", "full_name", "role", "department_id", "active", "system")


def mirror_user(conn, user):
    """คัดลอกข้อมูลผู้ใช้ไปฐานข้อมูล รพ.สต. (ไม่มีรหัสผ่าน ใช้ล็อกอินไม่ได้) เฉพาะเมื่อมีการเปลี่ยนแปลง"""
    have = one(conn, f"SELECT {', '.join(MIRROR_COLS)} FROM users WHERE id = ?", (user["id"],))
    want = {k: user[k] for k in MIRROR_COLS}
    if user["system"] != "phc":
        want["department_id"] = None  # หน่วยงานของ รพ. ไม่มีในทะเบียนของ รพ.สต.
    if have == want:
        return
    conn.execute(f"""INSERT INTO users ({', '.join(MIRROR_COLS)}, password_hash, must_change_password) VALUES ({', '.join('?' * len(MIRROR_COLS))}, '!', 0)
        ON CONFLICT(id) DO UPDATE SET {', '.join(f'{k} = excluded.{k}' for k in MIRROR_COLS[1:])}""", tuple(want.values()))


def start_session(ctx, user, system="hospital"):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    ctx.conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at, system) VALUES (?, ?, ?, ?)",
                     (token_hash(token), user["id"], expires, system))
    ctx.cookie = session_cookie(token, int(SESSION_HOURS * 3600), ctx.secure)


def session_cookie(value, max_age, secure):
    return (f"sid={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
            + ("; Secure" if secure else ""))


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
    return public_user(ctx.conn, user, "hospital")


SYSTEM_NAMES = {"hospital": "รพ.", "phc": "รพ.สต."}
MAX_ADMINS = 5  # ผู้ดูแลคลังกลาง (เข้าได้ทั้ง รพ. และ รพ.สต.) ที่ใช้งานอยู่ได้ไม่เกินจำนวนนี้


def login(ctx, body, query):
    system = "phc" if body.get("system") == "phc" else "hospital"
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
    # บัญชีหน่วยงานเข้าได้เฉพาะระบบของตัวเอง ผู้ดูแลคลังกลางเข้าได้ทั้ง 2 ระบบ
    if user["role"] != "admin" and user["system"] != system:
        mine = SYSTEM_NAMES.get(user["system"], user["system"])
        raise ApiError(403, f"บัญชีนี้ใช้ได้เฉพาะระบบ {mine} กรุณากลับไปเลือกช่องทาง \"ใช้งานโดย {mine}\"")
    ctx.conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    start_session(ctx, user, system)
    return public_user(ctx.conn, user, system)


def logout(ctx, body, query):
    if ctx.token:
        ctx.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(ctx.token),))
    ctx.cookie = session_cookie("", 0, ctx.secure)
    return {"ok": True}


def get_me(ctx, body, query):
    return public_user(ctx.conn, ctx.user, ctx.user["session_system"])


def change_password(ctx, body, query):
    user = ctx.user
    if not check_password(str(body.get("old_password") or ""), user["password_hash"]):
        raise ApiError(400, "รหัสผ่านปัจจุบันไม่ถูกต้อง")
    new = str(body.get("new_password") or "")
    check_new_password(user["username"], new)
    ctx.conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", (hash_password(new), user["id"]))
    # ออกจากระบบทุกเครื่องอื่น เหลือเครื่องนี้
    ctx.conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user["id"], token_hash(ctx.token or "")))
    return public_user(ctx.conn, one(ctx.conn, "SELECT * FROM users WHERE id = ?", (user["id"],)), user["session_system"])


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
    # แต่ละระบบเห็นเฉพาะบัญชีของระบบตัวเอง และผู้ดูแลคลังกลาง (ซึ่งเข้าได้ทั้ง 2 ระบบ)
    ctx.require_admin()
    return [public_user(ctx.conn, u) for u in rows(ctx.conn.execute(
        "SELECT * FROM users WHERE role = 'admin' OR system = ? ORDER BY role, full_name", (ctx.user["session_system"],)))]


def user_values(ctx, body):
    role = body.get("role")
    if role not in ("admin", "dept"):
        raise ApiError(400, "สิทธิ์ไม่ถูกต้อง")
    # บัญชีหน่วยงานเป็นของระบบที่ผู้ดูแลล็อกอินเข้ามา (ผู้ดูแลคลังกลางเข้าได้ทั้ง 2 ระบบ)
    system = "hospital" if role == "admin" else ctx.user["session_system"]
    dept_id = int(body["department_id"]) if str(body.get("department_id") or "").isdigit() else None
    if role == "dept" and not dept_id:
        raise ApiError(400, "บัญชีหน่วยงานต้องระบุหน่วยงาน")
    if dept_id and not find_department(ctx.auth, ctx.user["session_system"], dept_id):
        raise ApiError(400, "ไม่พบหน่วยงานนี้")
    return text(body.get("full_name"), "ชื่อ-นามสกุล", True), role, dept_id, system


def check_admin_limit(ctx, user_id=None):
    others = ctx.conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (user_id or 0,)).fetchone()[0]
    if others >= MAX_ADMINS:
        raise ApiError(409, f"ผู้ดูแลคลังกลางที่ใช้งานอยู่มีได้ไม่เกิน {MAX_ADMINS} คน ปิดใช้งานหรือเปลี่ยนสิทธิ์บัญชีอื่นก่อน")


def create_user(ctx, body, query):
    ctx.require_admin()
    username = national_id(body.get("username"))
    full_name, role, dept_id, system = user_values(ctx, body)
    if role == "admin":
        check_admin_limit(ctx)
    try:
        uid = ctx.conn.execute("INSERT INTO users (username, password_hash, full_name, role, department_id, system) VALUES (?, ?, ?, ?, ?, ?)",
                               (username, hash_password(default_password(username)), full_name, role, dept_id, system)).lastrowid
    except sqlite3.IntegrityError:
        other = one(ctx.conn, "SELECT role, system FROM users WHERE username = ?", (username,))
        where = "" if not other or other["role"] == "admin" else f" ในระบบ {SYSTEM_NAMES.get(other['system'], other['system'])}"
        raise ApiError(409, f"มีบัญชีของเลขบัตรนี้แล้ว{where}")
    return public_user(ctx.conn, one(ctx.conn, "SELECT * FROM users WHERE id = ?", (uid,)))


def update_user(ctx, body, query, user_id):
    ctx.require_admin()
    full_name, role, dept_id, system = user_values(ctx, body)
    active = flag(body.get("active", True))
    before = one(ctx.conn, "SELECT role, active, system FROM users WHERE id = ?", (user_id,))
    if not before or (before["role"] != "admin" and before["system"] != ctx.user["session_system"]):
        raise ApiError(404, "ไม่พบผู้ใช้นี้")
    # ตรวจจำนวนผู้ดูแลเฉพาะตอนเพิ่มผู้ดูแลที่ใช้งานอยู่ (แก้ชื่อผู้ดูแลเดิมได้เสมอ)
    if role == "admin" and active and not (before["role"] == "admin" and before["active"]):
        check_admin_limit(ctx, user_id)
    others = ctx.conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (user_id,)).fetchone()[0]
    if not others and (role != "admin" or not active):
        raise ApiError(409, "ต้องมีผู้ดูแลคลังกลางที่ใช้งานอยู่อย่างน้อย 1 บัญชี")
    # ปลดล็อกบัญชีไปด้วยเมื่อผู้ดูแลบันทึก
    ctx.conn.execute("UPDATE users SET full_name = ?, role = ?, department_id = ?, active = ?, system = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                     (full_name, role, dept_id, active, system, user_id))
    if body.get("reset_password") is True:
        target = one(ctx.conn, "SELECT username FROM users WHERE id = ?", (user_id,))
        ctx.conn.execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                         (hash_password(default_password(target["username"])), user_id))
    # ปิดใช้งาน รีเซ็ตรหัส หรือย้ายระบบ/สิทธิ์: ออกจากระบบทุกเครื่อง
    if not active or body.get("reset_password") is True or role != before["role"] or system != before["system"]:
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


def is_phc(ctx):
    return bool(ctx.user) and ctx.user["session_system"] == "phc"


def save_item_price(ctx, item_id, body):
    if is_phc(ctx) and "unit_price" in body:
        ctx.conn.execute("UPDATE items SET unit_price = ? WHERE id = ?", (number(body.get("unit_price"), "ราคาต่อหน่วย", minimum=0), item_id))


def item_values(ctx, body):
    wh = body.get("warehouse_id")
    if not str(wh or "").isdigit() or not ctx.conn.execute("SELECT 1 FROM warehouses WHERE id = ?", (int(wh),)).fetchone():
        raise ApiError(400, "กรุณาเลือกคลัง")
    return (text(body.get("code"), "รหัสสินค้า", True), text(body.get("name"), "ชื่อสินค้า", True), int(wh),
            text(body.get("unit"), "หน่วยนับ", True), number(body.get("min_qty"), "จุดสั่งซื้อ", minimum=0) or 0,
            flag(body.get("active", True)))


def change_stock(ctx, item_id, delta, reason, requisition_id=None, floor_at_zero=False):
    """floor_at_zero: การจ่ายตามใบเบิกจ่ายได้เกินคงเหลือ โดยตัดสต็อกได้แค่ถึง 0 และบันทึกส่วนที่ขาดไว้ในประวัติ
    ส่วนการปรับลดเองยังห้ามเกินคงเหลือ"""
    item = get_item(ctx.conn, item_id)
    if floor_at_zero and item["qty"] + delta < 0:
        short = round(-(item["qty"] + delta), 4)
        reason = f"{reason} · จ่าย {-delta:g} ตัดสต็อกได้ {item['qty']:g} ขาดสต็อก {short:g} {item['unit']}"
        delta = -item["qty"]
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
    save_item_price(ctx, item_id, body)
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
    save_item_price(ctx, item_id, body)
    return get_item(ctx.conn, item_id)


def adjust_item(ctx, body, query, item_id):
    ctx.require_admin()
    delta = number(body.get("delta"), "จำนวน", True)
    if not delta:
        raise ApiError(400, "จำนวนต้องไม่เป็นศูนย์")
    change_stock(ctx, item_id, delta, text(body.get("reason"), "หมายเหตุ") or ("รับเข้า" if delta > 0 else "ปรับลด"))
    return get_item(ctx.conn, item_id)


# ---------- นำเข้าสินค้าจากไฟล์ Excel (.xlsx) หรือ CSV ----------
# อ่านไฟล์ด้วย standard library ล้วน: .xlsx คือ zip ของไฟล์ XML

XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def cell_text(value):
    value = str(value if value is not None else "").strip()
    # Excel เก็บจำนวนเต็มบางครั้งเป็น 12.0
    return value[:-2] if re.fullmatch(r"-?\d+\.0", value) else value


def column_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(raw):
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ApiError(400, "เปิดไฟล์ไม่ได้ ไฟล์เสียหรือไม่ใช่ .xlsx (ถ้าเป็น .xls แบบเก่า ให้เปิดใน Excel แล้วบันทึกเป็น .xlsx)")
    if sum(i.file_size for i in z.infolist()) > 80 * 1024 * 1024:
        raise ApiError(400, "ไฟล์ใหญ่เกินไป")
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{{{XLSX_NS}}}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{XLSX_NS}}}t")))
    # แผ่นงานแรกตามลำดับในไฟล์
    sheet = None
    try:
        first = ET.fromstring(z.read("xl/workbook.xml")).find(f"{{{XLSX_NS}}}sheets/{{{XLSX_NS}}}sheet")
        rid = first.get(f"{{{REL_NS}}}id")
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{{{PKG_REL_NS}}}Relationship"):
            if rel.get("Id") == rid:
                target = rel.get("Target", "")
                sheet = target.lstrip("/") if target.startswith("/") else "xl/" + target
    except (KeyError, AttributeError, ET.ParseError):
        sheet = None
    if sheet not in names:
        sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets:
            raise ApiError(400, "ไม่พบแผ่นงานในไฟล์ Excel")
        sheet = sheets[0]
    table = []
    for row in ET.fromstring(z.read(sheet)).iter(f"{{{XLSX_NS}}}row"):
        cells, pos = {}, 0
        for c in row.iter(f"{{{XLSX_NS}}}c"):
            idx = column_index(c.get("r"))
            pos = pos if idx is None else idx
            kind = c.get("t")
            v = c.find(f"{{{XLSX_NS}}}v")
            if kind == "s" and v is not None and v.text and v.text.isdigit() and int(v.text) < len(shared):
                value = shared[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{{{XLSX_NS}}}t"))
            else:
                value = v.text if v is not None else ""
            cells[pos] = cell_text(value)
            pos += 1
        table.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        if len(table) > MAX_IMPORT_ROWS + 20:
            raise ApiError(400, f"ไฟล์มีแถวเกิน {MAX_IMPORT_ROWS} แถว แบ่งเป็นหลายไฟล์")
    return table


def read_csv(raw):
    for encoding in ("utf-8-sig", "cp874"):  # Excel บน Windows ภาษาไทยบันทึก CSV เป็น cp874
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ApiError(400, "อ่านตัวอักษรในไฟล์ CSV ไม่ได้ ให้บันทึกเป็น CSV UTF-8 หรือ .xlsx")
    first = text.split("\n", 1)[0]
    delimiter = max([",", ";", "\t"], key=first.count)
    return [[cell_text(v) for v in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


IMPORT_COLUMNS = {
    "code": ["รหัสสินค้า", "รหัส", "code", "itemcode"],
    "name": ["ชื่อสินค้า", "ชื่อ", "รายการ", "name"],
    "warehouse": ["คลัง", "ชื่อคลัง", "รหัสคลัง", "warehouse"],
    "unit": ["หน่วยนับ", "หน่วย", "unit"],
    "qty": ["คงเหลือ", "ยอดคงเหลือ", "จำนวนคงเหลือ", "จำนวน", "qty", "stock"],
    "min_qty": ["จุดสั่งซื้อ", "ขั้นต่ำ", "min", "reorder"],
}
REQUIRED_COLUMNS = {"code": "รหัสสินค้า", "name": "ชื่อสินค้า", "warehouse": "คลัง", "unit": "หน่วยนับ"}
# ระบบ รพ.สต.: ไฟล์มี รหัสสินค้า ชื่อสินค้า หน่วยย่อย ราคาในหน่วยย่อย (เบิก) คลัง
PHC_IMPORT_COLUMNS = {
    "code": ["รหัสสินค้า", "รหัส", "code", "itemcode"],
    "name": ["ชื่อสินค้า", "ชื่อ", "รายการ", "name"],
    "unit": ["หน่วยย่อย", "หน่วยนับ", "หน่วย", "unit"],
    "price": ["ราคาในหน่วยย่อยเบิก", "ราคาในหน่วยย่อย", "ราคาต่อหน่วย", "ราคา", "price"],
    "warehouse": ["คลัง", "ชื่อคลัง", "รหัสคลัง", "warehouse"],
}
PHC_REQUIRED_COLUMNS = {"code": "รหัสสินค้า", "name": "ชื่อสินค้า", "unit": "หน่วยย่อย", "price": "ราคาในหน่วยย่อย (เบิก)", "warehouse": "คลัง"}


def header_key(text, columns=IMPORT_COLUMNS):
    t = re.sub(r"[\s*_\-()]", "", str(text)).lower()
    for key, aliases in columns.items():
        if t in [a.lower() for a in aliases]:
            return key
    return None


def find_header(table, columns, required):
    """หาแถวหัวตาราง (อยู่ใน 10 แถวแรก) คืน (เลขแถว, {คอลัมน์: ตำแหน่ง})"""
    for i, row in enumerate(table[:10]):
        found = {}
        for j, cell in enumerate(row):
            key = header_key(cell, columns)
            if key and key not in found:
                found[key] = j
        if len(found) >= 2:
            missing = [label for key, label in required.items() if key not in found]
            if missing:
                raise ApiError(400, "ไฟล์ไม่มีคอลัมน์: " + ", ".join(missing))
            return i, found
    raise ApiError(400, "ไม่พบหัวตาราง ต้องมีคอลัมน์ " + ", ".join(required.values()))


def find_warehouse_in(warehouses, text):
    t = re.sub(r"\s", "", text)
    for w in warehouses:
        if t.upper() == w["code"].upper() or t in (w["name"], w["name"].replace("คลัง", "", 1)):
            return w
    return None


def import_number(value, label):
    v = str(value or "").replace(",", "").strip()
    if not v:
        return None
    try:
        n = float(v)
    except ValueError:
        raise ValueError(f"{label} \"{value}\" ไม่ใช่ตัวเลข")
    if n < 0:
        raise ValueError(f"{label}ต้องไม่ติดลบ")
    return n


def import_items(ctx, body, query):
    """ตรวจไฟล์และแสดงผลก่อน (apply=false) แล้วค่อยบันทึกจริง (apply=true)"""
    ctx.require_admin()
    if is_phc(ctx):
        return import_items_phc(ctx, body, read_import_table(body))
    table = read_import_table(body)
    header_row, columns = find_header(table, IMPORT_COLUMNS, REQUIRED_COLUMNS)
    return import_items_hospital(ctx, body, table, header_row, columns)


def read_import_table(body):
    filename = str(body.get("filename") or "").lower()
    try:
        raw = base64.b64decode(str(body.get("data") or ""), validate=True)
    except (ValueError, TypeError):
        raise ApiError(400, "อ่านไฟล์ไม่ได้")
    if not raw:
        raise ApiError(400, "ไฟล์ว่างเปล่า")
    if filename.endswith(".xlsx") or raw[:2] == b"PK":
        table = read_xlsx(raw)
    elif filename.endswith((".csv", ".txt")):
        table = read_csv(raw)
    elif filename.endswith(".xls"):
        raise ApiError(400, "ไฟล์ .xls แบบเก่ายังไม่รองรับ ให้เปิดใน Excel แล้วบันทึกเป็น .xlsx")
    else:
        raise ApiError(400, "รองรับเฉพาะไฟล์ .xlsx หรือ .csv")
    return table


def import_items_phc(ctx, body, table):
    """นำเข้าสินค้าของ รพ.สต.: รหัสที่มีอยู่แล้วจะอัปเดตชื่อ คลัง หน่วยย่อย และราคา แทนการเพิ่มซ้ำ (ไม่มียอดคงเหลือในไฟล์)"""
    header_row, columns = find_header(table, PHC_IMPORT_COLUMNS, PHC_REQUIRED_COLUMNS)
    warehouses = rows(ctx.conn.execute("SELECT * FROM warehouses"))
    existing = {r["code"]: r for r in rows(ctx.conn.execute("SELECT * FROM items"))}
    results, seen = [], set()
    for n, row in enumerate(table[header_row + 1:], start=header_row + 2):
        get = lambda key: row[columns[key]].strip() if key in columns and columns[key] < len(row) else ""
        values = {k: get(k) for k in PHC_IMPORT_COLUMNS}
        if not any(values.values()):
            continue
        r = {"row": n, "code": values["code"], "name": values["name"], "warehouse": values["warehouse"], "unit": values["unit"],
             "price": None, "qty": None, "action": "error", "message": ""}
        results.append(r)
        if len(results) > MAX_IMPORT_ROWS:
            raise ApiError(400, f"ไฟล์มีสินค้าเกิน {MAX_IMPORT_ROWS} รายการ แบ่งเป็นหลายไฟล์")
        try:
            empty = [label for key, label in PHC_REQUIRED_COLUMNS.items() if key != "price" and not values[key]]
            if empty:
                raise ValueError("ไม่ได้กรอก " + ", ".join(empty))
            wh = find_warehouse_in(warehouses, values["warehouse"])
            if not wh:
                raise ValueError(f"ไม่รู้จักคลัง \"{values['warehouse']}\"")
            if values["code"] in seen:
                raise ValueError("รหัสซ้ำกับแถวก่อนหน้าในไฟล์")
            seen.add(values["code"])
            price = import_number(values["price"], "ราคาในหน่วยย่อย")
        except ValueError as err:
            r["message"] = str(err)
            continue
        r.update(warehouse=wh["name"], warehouse_id=wh["id"], price=price)
        old = existing.get(values["code"])
        if not old:
            r["action"] = "new"
            r["message"] = "เพิ่มใหม่" + (f" ราคา {price:,.2f} บาท/{values['unit']}" if price is not None else " (ยังไม่มีราคา)")
            continue
        changes = []
        if old["name"] != values["name"]:
            changes.append("ชื่อ")
        if old["warehouse_id"] != wh["id"]:
            changes.append("คลัง")
        if old["unit"] != values["unit"]:
            changes.append("หน่วยย่อย")
        if price is not None and old["unit_price"] != price:
            changes.append(f"ราคา {old['unit_price'] or 0:,.2f} → {price:,.2f}")
        r["item_id"] = old["id"]
        r["action"] = "update" if changes else "same"
        r["message"] = ("แก้ " + ", ".join(changes)) if changes else "มีอยู่แล้ว ข้อมูลตรงกัน"

    if body.get("apply") is True:
        for r in results:
            if r["action"] == "new":
                ctx.conn.execute("INSERT INTO items (code, name, warehouse_id, unit, unit_price) VALUES (?, ?, ?, ?, ?)",
                                 (r["code"], r["name"], r["warehouse_id"], r["unit"], r["price"]))
            elif r["action"] == "update":
                ctx.conn.execute("UPDATE items SET name = ?, warehouse_id = ?, unit = ?, unit_price = COALESCE(?, unit_price) WHERE id = ?",
                                 (r["name"], r["warehouse_id"], r["unit"], r["price"], r["item_id"]))
    counts = {k: sum(1 for r in results if r["action"] == k) for k in ("new", "update", "same", "error")}
    for r in results:
        r.pop("item_id", None)
        r.pop("warehouse_id", None)
    return {"columns": [k for k in PHC_IMPORT_COLUMNS if k in columns], "rows": results, "counts": counts, "applied": body.get("apply") is True}


def import_items_hospital(ctx, body, table, header_row, columns):
    warehouses = rows(ctx.conn.execute("SELECT * FROM warehouses"))
    find_warehouse = lambda text: find_warehouse_in(warehouses, text)

    existing = {r["code"]: r for r in rows(ctx.conn.execute("SELECT * FROM items"))}
    update_stock = body.get("update_stock") is True
    results, seen = [], set()
    for n, row in enumerate(table[header_row + 1:], start=header_row + 2):
        get = lambda key: row[columns[key]].strip() if key in columns and columns[key] < len(row) else ""
        values = {k: get(k) for k in IMPORT_COLUMNS}
        if not any(values.values()):
            continue
        r = {"row": n, "code": values["code"], "name": values["name"], "warehouse": values["warehouse"], "unit": values["unit"],
             "qty": None, "min_qty": None, "action": "error", "message": ""}
        results.append(r)
        if len(results) > MAX_IMPORT_ROWS:
            raise ApiError(400, f"ไฟล์มีสินค้าเกิน {MAX_IMPORT_ROWS} รายการ แบ่งเป็นหลายไฟล์")
        try:
            empty = [label for key, label in REQUIRED_COLUMNS.items() if not values[key]]
            if empty:
                raise ValueError("ไม่ได้กรอก " + ", ".join(empty))
            wh = find_warehouse(values["warehouse"])
            if not wh:
                raise ValueError(f"ไม่รู้จักคลัง \"{values['warehouse']}\"")
            if values["code"] in seen:
                raise ValueError("รหัสซ้ำกับแถวก่อนหน้าในไฟล์")
            seen.add(values["code"])
            qty = import_number(values["qty"], "คงเหลือ")
            min_qty = import_number(values["min_qty"], "จุดสั่งซื้อ")
        except ValueError as err:
            r["message"] = str(err)
            continue
        r.update(warehouse=wh["name"], warehouse_id=wh["id"], qty=qty, min_qty=min_qty)
        old = existing.get(values["code"])
        if not old:
            r["action"] = "new"
            r["message"] = f"เพิ่มใหม่ ยอดยกมา {qty or 0:,g} {values['unit']}"
            continue
        changes = []
        if old["name"] != values["name"]:
            changes.append("ชื่อ")
        if old["warehouse_id"] != wh["id"]:
            changes.append("คลัง")
        if old["unit"] != values["unit"]:
            changes.append("หน่วยนับ")
        if min_qty is not None and old["min_qty"] != min_qty:
            changes.append("จุดสั่งซื้อ")
        if update_stock and qty is not None and old["qty"] != qty:
            changes.append(f"คงเหลือ {old['qty']:,g} → {qty:,g}")
        r["item_id"] = old["id"]
        r["action"] = "update" if changes else "same"
        r["message"] = ("แก้ " + ", ".join(changes)) if changes else "มีอยู่แล้ว ข้อมูลตรงกัน"
        if not update_stock and qty is not None and old["qty"] != qty:
            r["message"] += f" · คงเหลือในระบบ {old['qty']:,g} (ไม่ปรับตามไฟล์)"

    if body.get("apply") is True:
        for r in results:
            if r["action"] == "new":
                item_id = ctx.conn.execute("INSERT INTO items (code, name, warehouse_id, unit, min_qty) VALUES (?, ?, ?, ?, ?)",
                                           (r["code"], r["name"], r["warehouse_id"], r["unit"], r["min_qty"] or 0)).lastrowid
                if r["qty"]:
                    change_stock(ctx, item_id, r["qty"], "ยอดยกมา (นำเข้าจาก Excel)")
            elif r["action"] == "update":
                ctx.conn.execute("UPDATE items SET name = ?, warehouse_id = ?, unit = ?, min_qty = COALESCE(?, min_qty) WHERE id = ?",
                                 (r["name"], r["warehouse_id"], r["unit"], r["min_qty"], r["item_id"]))
                if update_stock and r["qty"] is not None:
                    current = get_item(ctx.conn, r["item_id"])["qty"]
                    if current != r["qty"]:
                        change_stock(ctx, r["item_id"], r["qty"] - current, "ปรับยอดตามไฟล์นำเข้า Excel")
    counts = {k: sum(1 for r in results if r["action"] == k) for k in ("new", "update", "same", "error")}
    for r in results:
        r.pop("item_id", None)
        r.pop("warehouse_id", None)
    return {"columns": [k for k in IMPORT_COLUMNS if k in columns], "rows": results, "counts": counts, "applied": body.get("apply") is True}


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
    # last_price: ราคาต่อหน่วยล่าสุดของสินค้านี้จากใบเบิกอื่น ใช้เป็นค่าตั้งต้นตอนจ่าย
    doc["lines"] = rows(ctx.conn.execute("""SELECT l.*, i.code, i.name, i.unit, i.qty AS stock, i.warehouse_id, w.name AS warehouse_name,
        (SELECT p.unit_price FROM lines p WHERE p.item_id = l.item_id AND p.unit_price IS NOT NULL AND p.id != l.id
         ORDER BY p.id DESC LIMIT 1) AS last_price, i.unit_price AS item_price
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
    # ผู้อนุมัติกำหนดผู้จ่ายไว้ล่วงหน้าได้ ตอนจ่ายจริงยังเปลี่ยนได้
    if "issuer_name" in body:
        ctx.conn.execute("UPDATE requisitions SET issuer_name = ?, issuer_position = ? WHERE id = ?",
                         (text(body.get("issuer_name"), "ชื่อผู้จ่าย"), text(body.get("issuer_position"), "ตำแหน่ง"), req_id))
    return get_req(ctx, req_id)


def set_requisition_names(ctx, body, query, req_id):
    """แก้ชื่อผู้อนุมัติ/ผู้จ่ายของใบที่อนุมัติแล้วแต่ยังไม่จ่าย โดยไม่ต้องยกเลิกอนุมัติ"""
    ctx.require_admin()
    require_status(get_req(ctx, req_id), "approved")
    ctx.conn.execute("UPDATE requisitions SET approver_name = ?, approver_position = ?, issuer_name = ?, issuer_position = ? WHERE id = ?",
                     (text(body.get("approver_name"), "ชื่อผู้อนุมัติ", True), text(body.get("approver_position"), "ตำแหน่ง"),
                      text(body.get("issuer_name"), "ชื่อผู้จ่าย"), text(body.get("issuer_position"), "ตำแหน่ง"), req_id))
    return get_req(ctx, req_id)


def set_requisition_people(ctx, body, query, req_id):
    """ผู้ดูแลคลังแก้ชื่อและตำแหน่งผู้เบิก/ผู้อนุมัติ/ผู้จ่าย/ผู้รับ ได้ทุกสถานะยกเว้นยกเลิก ไม่แตะจำนวนหรือสต็อก"""
    ctx.require_admin()
    doc = get_req(ctx, req_id)
    require_status(doc, "pending", "approved", "issued", "rejected")
    # ชื่อที่ต้องมีตามสถานะ (เหมือนตอนอนุมัติ/จ่าย) ตำแหน่งเว้นว่างได้
    need = {"requester": True, "approver": doc["status"] in ("approved", "issued", "rejected"),
            "issuer": doc["status"] == "issued", "receiver": doc["status"] == "issued"}
    label = {"requester": "ชื่อผู้เบิก", "approver": "ชื่อผู้อนุมัติ", "issuer": "ชื่อผู้จ่าย", "receiver": "ชื่อผู้รับ"}
    values = {}
    for role, required in need.items():
        values[f"{role}_name"] = text(body.get(f"{role}_name"), label[role], required)
        values[f"{role}_position"] = text(body.get(f"{role}_position"), "ตำแหน่ง")
    ctx.conn.execute(f"UPDATE requisitions SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?", (*values.values(), req_id))
    return get_req(ctx, req_id)


# ---------- แนวทางปฏิบัติ: ประกาศพร้อมไฟล์ PDF (เก็บในฐานข้อมูล จึงถูกสำรองไปพร้อมกัน) ----------

class FileResult:
    """ผลลัพธ์ของ handler ที่ต้องส่งเป็นไฟล์แทน JSON (inline = เปิดในเบราว์เซอร์, attachment = ดาวน์โหลด)"""
    def __init__(self, data, content_type, filename, disposition="inline"):
        self.data, self.content_type, self.filename, self.disposition = data, content_type, filename, disposition


GUIDE_SQL = """SELECT g.id, g.title, g.body, g.file_name, g.file_size, g.created_at, u.full_name AS created_by_name
               FROM guidelines g LEFT JOIN users u ON u.id = g.created_by"""


def list_guidelines(ctx, body, query):
    return rows(ctx.conn.execute(GUIDE_SQL + " ORDER BY g.created_at DESC, g.id DESC"))


def pdf_from_body(body):
    """ถอดไฟล์ PDF ที่ส่งมาแบบ base64 คืน (ข้อมูล, ชื่อไฟล์) หรือ (None, None) ถ้าไม่ได้แนบ"""
    if not body.get("file_data"):
        return None, None
    try:
        data = base64.b64decode(str(body["file_data"]), validate=True)
    except ValueError:
        raise ApiError(400, "อ่านไฟล์ไม่ได้ ลองเลือกไฟล์ใหม่")
    if not data.startswith(b"%PDF-"):
        raise ApiError(400, "รองรับเฉพาะไฟล์ PDF")
    if len(data) > GUIDE_MAX_MB * 1024 * 1024:
        raise ApiError(413, f"ไฟล์ใหญ่เกิน {GUIDE_MAX_MB} MB")
    name = (text(body.get("file_name"), "ชื่อไฟล์") or "เอกสาร.pdf").replace("/", "_").replace("\\", "_")[:200]
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return data, name


def create_guideline(ctx, body, query):
    ctx.require_admin()
    title = text(body.get("title"), "หัวข้อ", True)
    detail = text(body.get("body"), "รายละเอียด")
    data, name = pdf_from_body(body)
    if not detail and data is None:
        raise ApiError(400, "กรุณาใส่รายละเอียดหรือแนบไฟล์ PDF อย่างน้อยหนึ่งอย่าง")
    gid = ctx.conn.execute("""INSERT INTO guidelines (title, body, file_name, file_size, file_data, created_at, created_by)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""",
                           (title, detail, name, len(data) if data else None, data, now(), ctx.user["id"])).lastrowid
    return one(ctx.conn, GUIDE_SQL + " WHERE g.id = ?", (gid,))


def delete_guideline(ctx, body, query, gid):
    ctx.require_admin()
    if not ctx.conn.execute("DELETE FROM guidelines WHERE id = ?", (gid,)).rowcount:
        raise ApiError(404, "ไม่พบประกาศนี้")
    return {"ok": True}


def guideline_file(ctx, body, query, gid):
    g = one(ctx.conn, "SELECT file_name, file_data FROM guidelines WHERE id = ?", (gid,))
    if not g or g["file_data"] is None:
        raise ApiError(404, "ไม่พบไฟล์")
    return FileResult(bytes(g["file_data"]), "application/pdf", g["file_name"])


# ---------- แจ้งปัญหาคลังกลาง: หน่วยงานแจ้ง ผู้ดูแลตอบกลับ ----------
# บัญชีหน่วยงานเห็นเฉพาะเรื่องของหน่วยงานตัวเอง (เหมือนใบเบิก)

ISSUE_TYPES = {"requisition": "ปัญหาการเบิก", "system": "ปัญหาการใช้งานระบบ", "delivery": "ปัญหาการส่ง/รับของ", "other": "อื่น ๆ"}
ISSUE_STATUS = {"open": "รอดำเนินการ", "answered": "ตอบกลับแล้ว", "closed": "ปิดเรื่อง"}
ISSUE_SQL = """SELECT i.*, d.name AS department_name, u.full_name AS created_by_name
               FROM issues i LEFT JOIN departments d ON d.id = i.department_id LEFT JOIN users u ON u.id = i.created_by"""


def get_issue(ctx, iid):
    issue = one(ctx.conn, ISSUE_SQL + " WHERE i.id = ?", (iid,))
    if not issue or (not ctx.admin and issue["department_id"] != ctx.user["department_id"]):
        raise ApiError(404, "ไม่พบเรื่องนี้")
    return issue


def list_issues(ctx, body, query):
    sql, params = ISSUE_SQL + " WHERE 1 = 1", []
    if not ctx.admin:
        sql += " AND i.department_id = ?"
        params.append(ctx.user["department_id"])
    status = query.get("status", [""])[0]
    if status in ISSUE_STATUS:
        sql += " AND i.status = ?"
        params.append(status)
    return rows(ctx.conn.execute(sql + " ORDER BY i.created_at DESC, i.id DESC LIMIT 500", params))


def create_issue(ctx, body, query):
    category = body.get("category")
    if category not in ISSUE_TYPES:
        raise ApiError(400, "กรุณาเลือกประเภทปัญหา")
    message = text(body.get("message"), "รายละเอียดปัญหา", True)
    if len(message) > 2000:
        raise ApiError(400, "รายละเอียดยาวเกิน 2,000 ตัวอักษร")
    ref = (text(body.get("ref"), "เลขที่ใบเบิก") or "")[:40] or None
    iid = ctx.conn.execute("INSERT INTO issues (category, ref, message, department_id, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (category, ref, message, ctx.user["department_id"], ctx.user["id"], now())).lastrowid
    return get_issue(ctx, iid)


def reply_issue(ctx, body, query, iid):
    ctx.require_admin()
    get_issue(ctx, iid)
    status = body.get("status") or "answered"
    if status not in ISSUE_STATUS:
        raise ApiError(400, "สถานะไม่ถูกต้อง")
    reply = text(body.get("reply"), "ข้อความตอบกลับ")
    if reply and len(reply) > 2000:
        raise ApiError(400, "ข้อความตอบกลับยาวเกิน 2,000 ตัวอักษร")
    if status == "answered" and not reply:
        raise ApiError(400, "กรุณาพิมพ์ข้อความตอบกลับ")
    ctx.conn.execute("UPDATE issues SET reply = ?, status = ?, replied_by = ?, replied_at = ? WHERE id = ?",
                     (reply, status, ctx.user["full_name"] if reply else None, now() if reply else None, iid))
    return get_issue(ctx, iid)


# ---------- สินค้าคงคลังรายวัน: ไฟล์ PDF ยอดคงคลังแยกตามคลัง ----------

STOCK_KEEP_DAYS = 14  # เก็บไฟล์ต่อคลังย้อนหลังกี่วัน (เก่ากว่านี้ลบอัตโนมัติ เพื่อไม่ให้ฐานข้อมูลและไฟล์สำรองโตเร็ว)
STOCK_SQL = """SELECT s.id, s.warehouse_id, s.report_at, s.file_name, s.file_size, s.created_at, u.full_name AS created_by_name
               FROM stock_reports s LEFT JOIN users u ON u.id = s.created_by"""


def list_stock_reports(ctx, body, query):
    return rows(ctx.conn.execute(STOCK_SQL + " ORDER BY s.warehouse_id, s.report_at DESC, s.id DESC"))


def create_stock_report(ctx, body, query):
    ctx.require_admin()
    wh = body.get("warehouse_id")
    if not str(wh or "").isdigit() or not ctx.conn.execute("SELECT 1 FROM warehouses WHERE id = ?", (int(wh),)).fetchone():
        raise ApiError(400, "กรุณาเลือกคลัง")
    try:
        report_at = datetime.fromisoformat(str(body.get("report_at") or "")).isoformat(timespec="seconds")
    except ValueError:
        raise ApiError(400, "กรุณาระบุวันที่และเวลาของยอดคงคลัง")
    if report_at > (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"):
        raise ApiError(400, "วันที่ของยอดคงคลังต้องไม่เป็นวันในอนาคต")
    data, name = pdf_from_body(body)
    if data is None:
        raise ApiError(400, "กรุณาเลือกไฟล์ PDF")
    sid = ctx.conn.execute("""INSERT INTO stock_reports (warehouse_id, report_at, file_name, file_size, file_data, created_at, created_by)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""",
                           (int(wh), report_at, name, len(data), data, now(), ctx.user["id"])).lastrowid
    cutoff = (datetime.now() - timedelta(days=STOCK_KEEP_DAYS)).isoformat(timespec="seconds")
    ctx.conn.execute("DELETE FROM stock_reports WHERE warehouse_id = ? AND report_at < ? AND id != ?", (int(wh), cutoff, sid))
    return one(ctx.conn, STOCK_SQL + " WHERE s.id = ?", (sid,))


def delete_stock_report(ctx, body, query, sid):
    ctx.require_admin()
    if not ctx.conn.execute("DELETE FROM stock_reports WHERE id = ?", (sid,)).rowcount:
        raise ApiError(404, "ไม่พบไฟล์นี้")
    return {"ok": True}


def stock_report_file(ctx, body, query, sid):
    s = one(ctx.conn, "SELECT file_name, file_data FROM stock_reports WHERE id = ?", (sid,))
    if not s:
        raise ApiError(404, "ไม่พบไฟล์")
    return FileResult(bytes(s["file_data"]), "application/pdf", s["file_name"])


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
    save_prices(ctx, doc, body.get("lines"))
    # จ่ายได้ตามจำนวนที่ต้องการแม้คงเหลือในระบบไม่พอ: คงเหลือหยุดที่ 0 ไม่ติดลบ และประวัติสต็อกบันทึกส่วนที่ขาด
    for l in doc["lines"]:
        ctx.conn.execute("UPDATE lines SET qty_issued = ? WHERE id = ?", (qty[l["id"]], l["id"]))
        if qty[l["id"]]:
            change_stock(ctx, l["item_id"], -qty[l["id"]], f"จ่ายตามใบเบิก {doc['doc_no']} ({doc['department_name']})", req_id,
                         floor_at_zero=True)
    ctx.conn.execute("""UPDATE requisitions SET status = 'issued', issuer_name = ?, issuer_position = ?, receiver_name = ?, receiver_position = ?,
                        issued_at = ? WHERE id = ?""", (issuer, text(body.get("issuer_position"), "ตำแหน่ง"), receiver,
                                                       text(body.get("receiver_position"), "ตำแหน่ง"), now(), req_id))
    return get_req(ctx, req_id)


def save_prices(ctx, doc, entries):
    """ราคาต่อหน่วย (บาท) ของแต่ละรายการ เฉพาะระบบ รพ.สต. เว้นว่างได้ มูลค่า = ราคาต่อหน่วย × จำนวนจ่ายจริง"""
    if ctx.user["session_system"] != "phc":
        return
    ids = {l["id"] for l in doc["lines"]}
    for e in entries or []:
        if isinstance(e, dict) and "unit_price" in e and str(e.get("line_id", "")).isdigit() and int(e["line_id"]) in ids:
            price = number(e.get("unit_price"), "ราคาต่อหน่วย", minimum=0)
            ctx.conn.execute("UPDATE lines SET unit_price = ? WHERE id = ?", (price, int(e["line_id"])))


def set_requisition_prices(ctx, body, query, req_id):
    """ผู้ดูแลแก้ราคาต่อหน่วยของใบเบิกที่จ่ายแล้วได้ทุกเมื่อ (ไม่แตะจำนวนหรือสต็อก)"""
    ctx.require_admin()
    if ctx.user["session_system"] != "phc":
        raise ApiError(400, "ราคาต่อหน่วยใช้ได้เฉพาะระบบ รพ.สต.")
    doc = get_req(ctx, req_id)
    require_status(doc, "issued")
    save_prices(ctx, doc, body.get("lines"))
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


def usage_stats(conn, end):
    """การใช้งานระบบ (เฉพาะผู้ดูแล): จำนวนผู้ใช้ตามช่วงเวลาและหน่วยงาน นับจาก user_activity"""
    h = lambda days: (end - timedelta(days=days)).strftime("%Y-%m-%dT%H")
    today = end.strftime("%Y-%m-%d")
    distinct = lambda since: conn.execute("SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE hour >= ?", (since,)).fetchone()[0]
    by_hour = dict(conn.execute("""SELECT CAST(substr(hour, 12, 2) AS INTEGER), COUNT(*) FROM user_activity
                                   WHERE hour >= ? GROUP BY 1""", (h(30),)).fetchall())
    days = [(end - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    per_day = dict(conn.execute("""SELECT substr(hour, 1, 10), COUNT(DISTINCT user_id) FROM user_activity
                                   WHERE hour >= ? GROUP BY 1""", (days[0],)).fetchall())
    by_dept = rows(conn.execute("""
        SELECT COALESCE(d.name, 'คลังกลาง (ผู้ดูแล)') AS name, COUNT(DISTINCT a.user_id) AS users,
               COUNT(*) AS hours, MAX(a.hour) AS last_hour
        FROM user_activity a JOIN users u ON u.id = a.user_id LEFT JOIN departments d ON d.id = u.department_id
        WHERE a.hour >= ? GROUP BY u.department_id ORDER BY users DESC, hours DESC""", (h(30),)))
    first = conn.execute("SELECT MIN(hour) FROM user_activity").fetchone()[0]
    return {
        "today": distinct(today), "d7": distinct(h(7)), "d30": distinct(h(30)), "since": first,
        "by_hour": [{"hour": i, "count": by_hour.get(i, 0)} for i in range(24)],
        "by_day": [{"day": d, "users": per_day.get(d, 0)} for d in days],
        "by_department": by_dept,
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
    # สถิติการใช้สินค้านับจากจำนวนที่อนุมัติ (อนุมัติแล้วและจ่ายแล้ว) ไม่ใช่จำนวนจ่ายจริง
    # เพื่อให้เห็นความต้องการแม้ของในคลังไม่พอจ่าย
    approved = rows(ctx.conn.execute("""SELECT l.qty_approved AS qty, i.id AS item_id, i.name, i.unit, i.warehouse_id, w.name AS warehouse_name
        FROM lines l JOIN requisitions r ON r.id = l.requisition_id JOIN items i ON i.id = l.item_id JOIN warehouses w ON w.id = i.warehouse_id
        WHERE r.created_at >= ? AND r.status IN ('approved', 'issued') AND l.qty_approved > 0""", (start_s,)))
    by_wh = []
    for w in ctx.conn.execute("SELECT * FROM warehouses ORDER BY id"):
        by_wh.append({"warehouse_id": w["id"], "name": w["name"], "hue": w["hue"], "lines": sum(1 for l in approved if l["warehouse_id"] == w["id"])})
    by_wh.sort(key=lambda x: -x["lines"])
    by_dept = []
    for d in ctx.conn.execute("SELECT id, name FROM departments"):
        mine = [r for r in docs if r["department_id"] == d["id"]]
        if mine:
            by_dept.append({"name": d["name"], "total": len(mine), "emergency": sum(1 for r in mine if r["req_type"] == "emergency")})
    by_dept.sort(key=lambda x: -x["total"])
    # สินค้าที่เบิกมากที่สุด: เรียงตามจำนวนครั้ง (จำนวนใบเบิกที่มีสินค้านั้น) แล้วจึงตามจำนวนรวม
    totals = {}
    for l in approved:
        t = totals.setdefault(l["item_id"], {"name": l["name"], "unit": l["unit"], "warehouse_name": l["warehouse_name"], "times": 0, "qty": 0})
        t["times"] += 1
        t["qty"] += l["qty"]
    top = sorted(totals.values(), key=lambda x: (-x["times"], -x["qty"]))[:5]

    def avg_hours(items):
        hours = [(datetime.fromisoformat(r["issued_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600 for r in items]
        return sum(hours) / len(hours) if hours else None

    # สินค้าที่เปิดให้เบิกแต่ไม่มีใครเบิกเลยใน 30 วันล่าสุด (นับใบทุกสถานะยกเว้นยกเลิก/ไม่อนุมัติ)
    idle_since = (end - timedelta(days=30)).isoformat(timespec="seconds")
    idle = rows(ctx.conn.execute("""
        SELECT i.id, i.code, i.name, i.unit, w.name AS warehouse_name,
               (SELECT MAX(r.created_at) FROM lines l JOIN requisitions r ON r.id = l.requisition_id
                WHERE l.item_id = i.id AND r.status NOT IN ('cancelled', 'rejected')) AS last_requested
        FROM items i JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.active = 1 AND NOT EXISTS (
            SELECT 1 FROM lines l JOIN requisitions r ON r.id = l.requisition_id
            WHERE l.item_id = i.id AND r.created_at >= ? AND r.status NOT IN ('cancelled', 'rejected'))
        ORDER BY w.id, i.code""", (idle_since,)))

    done = [r for r in docs if r["issued_at"]]
    return {
        "usage": usage_stats(ctx.conn, end) if ctx.admin else None,
        "from": start_s, "to": end.isoformat(timespec="seconds"), "weeks": weeks,
        "by_warehouse": by_wh, "by_department": by_dept[:6], "top_items": top,
        "idle_since": idle_since, "idle_items": idle,
        "totals": {
            "requisitions": len(docs),
            "emergency": sum(1 for r in docs if r["req_type"] == "emergency"),
            "lines_approved": len(approved),
            "avg_hours": avg_hours(done),
            "avg_hours_emergency": avg_hours([r for r in done if r["req_type"] == "emergency"]),
        },
    }


# ---------- ส่งออก Dashboard เป็น Excel (.xlsx สร้างเองด้วย zipfile ไม่ใช้ไลบรารีเพิ่ม) ----------

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REQ_TYPE_TH = {"emergency": "ฉุกเฉิน", "routine": "ตามรอบปกติ"}


def th_date(ts, with_time=False):
    """2026-09-29T12:34:56 -> 29/09/2569 (12:34)"""
    if not ts:
        return ""
    d = datetime.fromisoformat(ts)
    return f"{d:%d/%m}/{d.year + 543}" + (f" {d:%H:%M}" if with_time else "")


def xml_escape(s):
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)  # อักขระควบคุมที่ XML ไม่รับ
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_xlsx(sheets):
    """sheets = [(ชื่อชีต, [[แถวหัวตาราง], [แถวข้อมูล], ...])] แถวแรกเป็นตัวหนา ตัวเลขเป็นตัวเลขจริงใน Excel"""
    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    def cell(ref, v, bold):
        style = ' s="1"' if bold else ""
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"{style}><v>{v:g}</v></c>'
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{xml_escape(str(v if v is not None else ""))}</t></is></c>'

    def sheet_xml(data):
        widths = [max(10, min(60, max(len(str(r[c])) if c < len(r) and r[c] is not None else 0 for r in data) + 2))
                  for c in range(max((len(r) for r in data), default=0))]
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
        body = "".join(f'<row r="{n + 1}">' + "".join(cell(f"{col(c)}{n + 1}", v, n == 0) for c, v in enumerate(r)) + "</row>"
                       for n, r in enumerate(data))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                f'{"<cols>" + cols + "</cols>" if cols else ""}<sheetData>{body}</sheetData></worksheet>')

    ns = "http://schemas.openxmlformats.org"
    names = [re.sub(r"[\[\]:*?/\\]", " ", n)[:31] for n, _ in sheets]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Types xmlns="{ns}/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets))) + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="{ns}/package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook xmlns="{ns}/spreadsheetml/2006/main" xmlns:r="{ns}/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{xml_escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="{ns}/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="{ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="{ns}/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<styleSheet xmlns="{ns}/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Tahoma"/></font><font><b/><sz val="11"/><name val="Tahoma"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>')
        for i, (_, data) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", sheet_xml(data))
    return buf.getvalue()


def analytics_export(ctx, body, query):
    """ข้อมูลเดียวกับหน้า Dashboard แยกเป็นชีต"""
    a = analytics(ctx, body, query)
    t = a["totals"]
    hours = lambda h: round(h, 1) if h is not None else "-"
    sheets = [
        ("สรุป", [["หัวข้อ", "ค่า"],
                  ["ช่วงข้อมูล", f"{th_date(a['from'])} – {th_date(a['to'])} ({len(a['weeks'])} สัปดาห์)"],
                  ["ส่งออกเมื่อ", th_date(now(), True)],
                  ["ใบเบิกทั้งหมด", t["requisitions"]],
                  ["เบิกฉุกเฉิน", t["emergency"]],
                  ["รายการที่อนุมัติเบิก", t["lines_approved"]],
                  ["เวลาเฉลี่ยจนได้รับของ (ชั่วโมง)", hours(t["avg_hours"])],
                  ["เวลาเฉลี่ยจนได้รับของ ฉุกเฉิน (ชั่วโมง)", hours(t["avg_hours_emergency"])]]),
        ("การเบิกรายสัปดาห์", [["สัปดาห์เริ่มวันที่", "ฉุกเฉิน", "ตามรอบปกติ", "รวม"]]
         + [[th_date(w["start"]), w["emergency"], w["routine"], w["emergency"] + w["routine"]] for w in a["weeks"]]),
        ("การใช้สินค้าตามคลัง", [["คลัง", "รายการที่อนุมัติเบิก"]] + [[w["name"], w["lines"]] for w in a["by_warehouse"]]),
        ("หน่วยงานที่เบิกมากที่สุด", [["หน่วยงาน", "ใบเบิกทั้งหมด", "เบิกฉุกเฉิน"]]
         + [[d["name"], d["total"], d["emergency"]] for d in a["by_department"]]),
        ("สินค้าที่เบิกมากที่สุด", [["ลำดับ", "รายการ", "คลัง", "จำนวนครั้งที่เบิก", "จำนวนที่อนุมัติรวม", "หน่วย"]]
         + [[i + 1, it["name"], it["warehouse_name"], it["times"], it["qty"], it["unit"]] for i, it in enumerate(a["top_items"])]),
    ]
    if ctx.admin:
        waiting = summary(ctx, body, query)["waiting"]
        sheets.append(("ใบเบิกที่ต้องดำเนินการ", [["เลขที่", "วันที่ส่ง", "หน่วยงาน", "ผู้เบิก", "ประเภท", "สถานะ"]]
                       + [[r["doc_no"], th_date(r["created_at"], True), r["department_name"], r["requester_name"],
                           REQ_TYPE_TH.get(r["req_type"], ""), STATUS[r["status"]]] for r in waiting]))
    # ทุกบัญชีเห็นสินค้าที่ไม่มีการเบิก (เหมือนบนหน้า Dashboard)
    sheets.append(("สินค้าที่ไม่มีการเบิก 30 วัน", [["รหัส", "รายการ", "คลัง", "หน่วย", "เบิกล่าสุด"]]
                   + [[i["code"], i["name"], i["warehouse_name"], i["unit"],
                       th_date(i["last_requested"]) if i["last_requested"] else "ไม่เคยเบิก"] for i in a["idle_items"]]))
    if a["usage"]:
        u = a["usage"]
        sheets.append(("การใช้งานระบบ", [["หัวข้อ", "จำนวนผู้ใช้"], ["วันนี้", u["today"]], ["7 วันล่าสุด", u["d7"]], ["30 วันล่าสุด", u["d30"]], [],
                                          ["ช่วงเวลา (30 วัน)", "ผู้ใช้งาน (คน·วัน)"]]
                       + [[f"{x['hour']:02d}.00–{x['hour']:02d}.59", x["count"]] for x in u["by_hour"]] + [[], ["วันที่", "ผู้ใช้งาน (คน)"]]
                       + [[th_date(x["day"]), x["users"]] for x in u["by_day"]]))
        sheets.append(("การใช้งานตามหน่วยงาน", [["หน่วยงาน", "ผู้ใช้งาน (คน)", "ชั่วโมงที่ใช้งาน", "ใช้งานล่าสุด"]]
                       + [[x["name"], x["users"], x["hours"], th_date(x["last_hour"] + ":00:00", True)] for x in u["by_department"]]))
    d = datetime.now()
    return FileResult(build_xlsx(sheets), XLSX_MIME, f"Dashboard_{d:%d-%m}-{d.year + 543}.xlsx", "attachment")


# ---------- เส้นทาง API ----------

ROUTES = []
PUBLIC = set()
# ผู้ใช้ที่ยังใช้รหัสผ่านเริ่มต้นเรียกได้เฉพาะเส้นทางเหล่านี้ จนกว่าจะตั้งรหัสใหม่
BEFORE_PASSWORD_CHANGE = set()


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
route("POST", "/me/password", change_password)
BEFORE_PASSWORD_CHANGE.update({get_me, change_password})
# เส้นทางที่ใช้ฐานข้อมูลหลักเสมอ (บัญชีผู้ใช้/เซสชัน) เส้นทางอื่นใช้ฐานข้อมูลของระบบที่ล็อกอินเข้ามา
AUTH_HANDLERS = {setup_status, setup, login, logout, get_me, change_password, list_users, create_user, update_user}
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
route("POST", "/items/import", import_items)
route("GET", "/movements", list_movements)
route("GET", "/requisitions", list_requisitions)
route("GET", "/requisitions/board", board)
route("POST", "/requisitions", create_requisition)
route("GET", f"/requisitions/{ID}", get_requisition)
route("PUT", f"/requisitions/{ID}", update_requisition)
route("POST", f"/requisitions/{ID}/cancel", cancel_requisition)
route("POST", f"/requisitions/{ID}/approve", approve_requisition)
route("POST", f"/requisitions/{ID}/unapprove", unapprove_requisition)
route("POST", f"/requisitions/{ID}/names", set_requisition_names)
route("POST", f"/requisitions/{ID}/people", set_requisition_people)
route("GET", "/guidelines", list_guidelines)
route("POST", "/guidelines", create_guideline)
route("DELETE", f"/guidelines/{ID}", delete_guideline)
route("GET", f"/guidelines/{ID}/file", guideline_file)
route("GET", "/stock-reports", list_stock_reports)
route("POST", "/stock-reports", create_stock_report)
route("DELETE", f"/stock-reports/{ID}", delete_stock_report)
route("GET", f"/stock-reports/{ID}/file", stock_report_file)
route("GET", "/issues", list_issues)
route("POST", "/issues", create_issue)
route("POST", f"/issues/{ID}/reply", reply_issue)
route("POST", f"/requisitions/{ID}/reject", reject_requisition)
route("POST", f"/requisitions/{ID}/issue", issue_requisition)
route("POST", f"/requisitions/{ID}/prices", set_requisition_prices)
route("GET", "/summary", summary)
route("GET", "/analytics", analytics)
route("GET", "/analytics/export", analytics_export)

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

    def via_proxy(self):
        # เชื่อ header ของ proxy (เช่น cloudflared) เฉพาะเมื่อคำขอมาจากเครื่องนี้เอง
        return self.client_address[0] in ("127.0.0.1", "::1")

    def is_https(self):
        return COOKIE_SECURE or (self.via_proxy() and self.headers.get("X-Forwarded-Proto", "").lower() == "https")

    def check_origin(self):
        # ป้องกันเว็บอื่นส่งคำสั่งแทนผู้ใช้ (CSRF) นอกเหนือจากคุกกี้ SameSite=Strict
        origin = self.headers.get("Origin")
        if not origin:
            return
        hosts = {self.headers.get("Host")}
        if self.via_proxy() and self.headers.get("X-Forwarded-Host"):
            hosts.add(self.headers.get("X-Forwarded-Host"))
        if urlparse(origin).netloc not in hosts:
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
                ctx = Ctx(conn, session_user(conn, token), token, self.is_https())
                if not ctx.user and handler not in PUBLIC:
                    raise ApiError(401, "กรุณาเข้าสู่ระบบ")
                if ctx.user and ctx.user["must_change_password"] and handler not in PUBLIC | BEFORE_PASSWORD_CHANGE:
                    raise ApiError(403, "กรุณาตั้งรหัสผ่านใหม่ก่อนใช้งาน")
                system = ctx.user["session_system"] if ctx.user else "hospital"
                if system != "hospital" and handler not in AUTH_HANDLERS:
                    # ระบบ รพ.สต.: ข้อมูลทั้งหมดอยู่ในฐานข้อมูลของ รพ.สต. เข้าถึงข้อมูลของ รพ. ไม่ได้
                    data = connect(system)
                    mirror_user(data, ctx.user)
                    conn.close()
                    conn = ctx.conn = data
                if ctx.user:
                    record_activity(ctx.conn, ctx.user["id"], system)
                # ล็อกฐานข้อมูลตั้งแต่ต้นสำหรับคำสั่งที่เขียนข้อมูล กันการตัดสต็อกซ้อนกัน
                conn.execute("BEGIN IMMEDIATE" if method != "GET" else "BEGIN")
                result = handler(ctx, body, parse_qs(url.query), *args)
                conn.execute("COMMIT")
                if isinstance(result, FileResult):
                    return self.send_file(result)
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

    def security_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        if self.is_https():
            self.send_header("Strict-Transport-Security", "max-age=31536000")

    def send_json(self, status, payload, cookie=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.security_headers()
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, f):
        # เปิดในแท็บใหม่ด้วยตัวอ่าน PDF ของเบราว์เซอร์ (ไม่ใส่ CSP ของหน้าเว็บ เพราะบางเบราว์เซอร์จะแสดง PDF ไม่ได้)
        ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", f.filename) if f.filename.isascii() else "document.pdf"
        self.send_response(200)
        self.send_header("Content-Type", f.content_type)
        self.send_header("Content-Length", str(len(f.data)))
        self.send_header("Content-Disposition", f"{f.disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.filename)}")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(f.data)

    def serve_static(self, path):
        target = (STATIC_DIR / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(STATIC_DIR) or not target.is_file():
            return self.send_json(404, {"error": "ไม่พบหน้านี้"})
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.security_headers()
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
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    for system, prefix in (("hospital", "central-store-"), ("phc", "central-store-phc-")):
        target = BACKUP_DIR / f"{prefix}{stamp}.db"
        src, dst = connect(system), sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        for old in sorted(BACKUP_DIR.glob(f"{prefix}2*.db"))[:-30]:
            old.unlink()
        print(f"สำรองข้อมูลแล้ว: {target}")


def reset_requisitions():
    """ล้างใบเบิกทั้งหมดก่อนเริ่มใช้จริง: สำรองข้อมูลก่อน แล้วคืนสต็อกที่จ่ายไป และลบใบเบิกทุกใบ
    สินค้า หน่วยเบิก ทะเบียนรายชื่อ และบัญชีผู้ใช้ยังอยู่ครบ"""
    init_db()
    conn = connect()
    try:
        n_req = conn.execute("SELECT COUNT(*) FROM requisitions").fetchone()[0]
        issued = conn.execute("""SELECT l.item_id, SUM(l.qty_issued) AS qty FROM lines l JOIN requisitions r ON r.id = l.requisition_id
                                 WHERE r.status = 'issued' AND l.qty_issued > 0 GROUP BY l.item_id""").fetchall()
    finally:
        conn.close()
    print(f"ใบเบิกทั้งหมด {n_req} ใบ จะถูกลบ และคืนสต็อกของที่จ่ายไปแล้ว {len(issued)} รายการสินค้า")
    print("สินค้า หน่วยเบิก ทะเบียนรายชื่อ และบัญชีผู้ใช้ยังอยู่ครบ · เลขที่ใบเบิกจะเริ่มนับใหม่")
    if not n_req:
        print("ไม่มีใบเบิกให้ล้าง")
        return
    if input("พิมพ์ YES (ตัวพิมพ์ใหญ่) แล้วกด Enter เพื่อยืนยัน: ").strip() != "YES":
        print("ยกเลิก ไม่มีการเปลี่ยนแปลง")
        return
    backup()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ts = now()
        for item_id, qty in issued:
            balance = conn.execute("SELECT qty FROM items WHERE id = ?", (item_id,)).fetchone()[0] + qty
            conn.execute("UPDATE items SET qty = ? WHERE id = ?", (balance, item_id))
            conn.execute("INSERT INTO movements (ts, item_id, delta, balance, reason) VALUES (?, ?, ?, ?, ?)",
                         (ts, item_id, qty, balance, "คืนสต็อก: ล้างใบเบิกก่อนเริ่มใช้จริง"))
        conn.execute("UPDATE movements SET requisition_id = NULL WHERE requisition_id IS NOT NULL")
        conn.execute("DELETE FROM lines")
        conn.execute("DELETE FROM requisitions")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    print(f"ล้างใบเบิก {n_req} ใบเรียบร้อย")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--backup" in sys.argv:
        return backup()
    if "--reset-requisitions" in sys.argv:
        return reset_requisitions()
    host = "0.0.0.0" if "--lan" in sys.argv else HOST
    if "--log" in sys.argv:
        # ทำงานเบื้องหลัง (Task Scheduler) ไม่มีหน้าต่าง: เก็บบันทึกลงไฟล์ ขนาดเกิน 5 MB ย้ายไปไฟล์ .old
        log = DB_PATH.parent / "server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
            log.replace(log.with_suffix(".log.old"))
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
        print(f"--- เริ่มระบบ {now()} ---")
    init_db()
    try:
        server = ThreadingHTTPServer((host, PORT), Handler)
    except OSError:
        print(f"เปิดระบบไม่ได้: พอร์ต {PORT} ถูกใช้อยู่ ระบบอาจทำงานเบื้องหลังอยู่แล้ว (ตั้งเปิดอัตโนมัติไว้)")
        print(f"ลองเปิด http://127.0.0.1:{PORT} ในเบราว์เซอร์ ถ้าเข้าได้ ไม่ต้องเปิด run.bat")
        sys.exit(1)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{PORT}"
    print(f"งานบริหารเวชภัณฑ์ (คลังกลาง) กำลังทำงานที่ {url}  (กด Ctrl+C เพื่อหยุด)")
    print(f"ฐานข้อมูล: {DB_PATH} (รพ.สต.: {PHC_DB_PATH})")
    if host in ("0.0.0.0", ""):
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
