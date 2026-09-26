#!/usr/bin/env python3
"""TPY Inventory — ระบบคลังสินค้าที่เชื่อมกับงาน CNC

ใช้แค่ Python standard library (http.server + sqlite3) ไม่ต้องติดตั้งไลบรารีเพิ่ม
รัน:  python server.py --open   แล้วเปิด http://127.0.0.1:8000
"""
import json
import math
import os
import re
import sqlite3
import sys
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.environ.get("INVENTORY_DB", BASE_DIR / "data" / "inventory.db"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
# ความเร็วเดินเปล่า (G0) ใช้ประมาณเวลาจาก G-code — ปรับให้ตรงกับเครื่องจริงได้
RAPID_MM_PER_MIN = float(os.environ.get("RAPID_MM_PER_MIN", "5000"))
MAX_BODY = 20 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'ชิ้น',
    qty REAL NOT NULL DEFAULT 0,
    min_qty REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    tool_number INTEGER,
    diameter REAL,
    life_minutes REAL NOT NULL DEFAULT 0,
    used_minutes REAL NOT NULL DEFAULT 0,
    spare_qty INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'ชิ้น',
    qty REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT,
    product_id INTEGER REFERENCES products(id),
    gcode TEXT NOT NULL DEFAULT '',
    est_minutes REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS program_materials (
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    qty_per_piece REAL NOT NULL,
    PRIMARY KEY (program_id, material_id)
);
CREATE TABLE IF NOT EXISTS program_tools (
    program_id INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    tool_id INTEGER NOT NULL REFERENCES tools(id),
    minutes_per_piece REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (program_id, tool_id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    program_id INTEGER NOT NULL REFERENCES programs(id),
    quantity INTEGER NOT NULL,
    good_qty INTEGER,
    status TEXT NOT NULL DEFAULT 'planned',
    machine_minutes REAL,
    note TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS movements (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    delta REAL NOT NULL,
    balance REAL NOT NULL,
    reason TEXT NOT NULL,
    job_id INTEGER
);
"""

FIELD_LABELS = {
    "code": "รหัส", "name": "ชื่อ", "unit": "หน่วย", "min_qty": "จุดสั่งซื้อขั้นต่ำ",
    "tool_number": "เบอร์ทูล (T)", "diameter": "เส้นผ่านศูนย์กลาง", "life_minutes": "อายุการใช้งาน",
    "initial_qty": "ยอดยกมา", "delta": "จำนวน",
}

# ชนิดข้อมูล, บังคับกรอก, ค่าเริ่มต้น
RESOURCES = {
    "materials": {
        "label": "วัตถุดิบ", "stock": "qty", "integer_stock": False,
        "fields": {"code": ("str", True, None), "name": ("str", True, None),
                   "unit": ("str", False, "ชิ้น"), "min_qty": ("float", False, 0)},
    },
    "tools": {
        "label": "ดอกกัด", "stock": "spare_qty", "integer_stock": True,
        "fields": {"code": ("str", True, None), "name": ("str", True, None),
                   "tool_number": ("int", False, None), "diameter": ("float", False, None),
                   "life_minutes": ("float", False, 0)},
    },
    "products": {
        "label": "สินค้าสำเร็จรูป", "stock": "qty", "integer_stock": False,
        "fields": {"code": ("str", True, None), "name": ("str", True, None),
                   "unit": ("str", False, "ชิ้น")},
    },
}

JOB_STATUS = {"planned": "รอผลิต", "running": "กำลังผลิต", "done": "เสร็จแล้ว", "cancelled": "ยกเลิก"}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Raw:
    """คำตอบที่ไม่ใช่ JSON เช่น ไฟล์ G-code สำหรับดาวน์โหลด"""

    def __init__(self, body, content_type, filename=None):
        self.body = body
        self.content_type = content_type
        self.filename = filename


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def label(field):
    return FIELD_LABELS.get(field, field)


# ---------- แปลงและตรวจค่าที่ส่งเข้ามา ----------

def to_str(value, field, required=False):
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise ApiError(400, f"กรุณาระบุ{label(field)}")
        return None
    return text


def to_float(value, field, required=False):
    if value is None or value == "":
        if required:
            raise ApiError(400, f"กรุณาระบุ{label(field)}")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{label(field)} ต้องเป็นตัวเลข")
    if not math.isfinite(number):
        raise ApiError(400, f"{label(field)} ต้องเป็นตัวเลข")
    return number


def to_int(value, field, required=False):
    number = to_float(value, field, required)
    if number is None:
        return None
    if not number.is_integer():
        raise ApiError(400, f"{label(field)} ต้องเป็นจำนวนเต็ม")
    return int(number)


CONVERT = {"str": to_str, "int": to_int, "float": to_float}


def clean_fields(spec, data):
    out = {}
    for name, (kind, required, default) in spec.items():
        value = CONVERT[kind](data.get(name), name, required)
        out[name] = default if value is None else value
    return out


def stock_amount(res, value, field, required=False):
    convert = to_int if RESOURCES[res]["integer_stock"] else to_float
    return convert(value, field, required)


# ---------- สต็อกและประวัติการเคลื่อนไหว ----------

def change_stock(conn, res, item_id, delta, reason, job_id=None):
    col = RESOURCES[res]["stock"]
    conn.execute(f"UPDATE {res} SET {col} = {col} + ? WHERE id = ?", (delta, item_id))
    balance = conn.execute(f"SELECT {col} FROM {res} WHERE id = ?", (item_id,)).fetchone()[0]
    conn.execute(
        "INSERT INTO movements (ts, item_type, item_id, delta, balance, reason, job_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now(), res, item_id, delta, balance, reason, job_id),
    )
    return balance


def get_item(conn, res, item_id):
    row = conn.execute(f"SELECT * FROM {res} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ApiError(404, f"ไม่พบ{RESOURCES[res]['label']}รายการนี้")
    return dict(row)


def list_items(conn, body, query, res):
    return rows(conn.execute(f"SELECT * FROM {res} ORDER BY code"))


def create_item(conn, body, query, res):
    values = clean_fields(RESOURCES[res]["fields"], body)
    initial = stock_amount(res, body.get("initial_qty"), "initial_qty")
    if initial is not None and initial < 0:
        raise ApiError(400, "ยอดยกมาต้องไม่ติดลบ")
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    try:
        cur = conn.execute(f"INSERT INTO {res} ({cols}) VALUES ({marks})", list(values.values()))
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัส {values['code']} มีอยู่แล้ว")
    if initial:
        change_stock(conn, res, cur.lastrowid, initial, "ยอดยกมา")
    return get_item(conn, res, cur.lastrowid)


def update_item(conn, body, query, res, item_id):
    get_item(conn, res, item_id)
    values = clean_fields(RESOURCES[res]["fields"], body)
    assignments = ", ".join(f"{col} = ?" for col in values)
    try:
        conn.execute(f"UPDATE {res} SET {assignments} WHERE id = ?", [*values.values(), item_id])
    except sqlite3.IntegrityError:
        raise ApiError(409, f"รหัส {values['code']} มีอยู่แล้ว")
    return get_item(conn, res, item_id)


def delete_item(conn, body, query, res, item_id):
    get_item(conn, res, item_id)
    try:
        conn.execute(f"DELETE FROM {res} WHERE id = ?", (item_id,))
    except sqlite3.IntegrityError:
        raise ApiError(409, "ลบไม่ได้ เพราะมีโปรแกรม G-code ใช้รายการนี้อยู่")
    return {"ok": True}


def adjust_item(conn, body, query, res, item_id):
    item = get_item(conn, res, item_id)
    delta = stock_amount(res, body.get("delta"), "delta", required=True)
    if delta == 0:
        raise ApiError(400, "จำนวนต้องไม่เป็นศูนย์")
    col = RESOURCES[res]["stock"]
    if item[col] + delta < 0:
        raise ApiError(409, f"สต็อกไม่พอ (คงเหลือ {item[col]:g})")
    reason = to_str(body.get("reason"), "reason") or ("รับเข้า" if delta > 0 else "เบิกออก")
    change_stock(conn, res, item_id, delta, reason)
    return get_item(conn, res, item_id)


def replace_tool(conn, body, query, tool_id):
    tool = get_item(conn, "tools", tool_id)
    if tool["spare_qty"] < 1:
        raise ApiError(409, "ไม่มีดอกสำรองในสต็อก กรุณารับดอกเข้าก่อน")
    conn.execute("UPDATE tools SET used_minutes = 0 WHERE id = ?", (tool_id,))
    change_stock(conn, "tools", tool_id, -1,
                 f"เปลี่ยนดอกใหม่ (ดอกเดิมใช้ไป {tool['used_minutes']:.0f} นาที)")
    return get_item(conn, "tools", tool_id)


def list_movements(conn, body, query):
    limit = to_int((query.get("limit") or ["300"])[0], "limit") or 300
    item_type = (query.get("type") or [""])[0]
    where, params = "", []
    if item_type in RESOURCES:
        where, params = "WHERE m.item_type = ?", [item_type]
    return rows(conn.execute(
        f"""SELECT m.*,
                   COALESCE(ma.code, t.code, p.code) AS item_code,
                   COALESCE(ma.name, t.name, p.name) AS item_name,
                   COALESCE(ma.unit, p.unit, 'ดอก') AS unit
            FROM movements m
            LEFT JOIN materials ma ON m.item_type = 'materials' AND ma.id = m.item_id
            LEFT JOIN tools t ON m.item_type = 'tools' AND t.id = m.item_id
            LEFT JOIN products p ON m.item_type = 'products' AND p.id = m.item_id
            {where}
            ORDER BY m.id DESC LIMIT ?""",
        [*params, max(1, min(limit, 5000))],
    ))


# ---------- วิเคราะห์ G-code ----------

COMMENT_RE = re.compile(r"\([^)]*\)|;.*")
WORD_RE = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


def arc_length(start, end, arc, scale, clockwise):
    sx, sy, ex, ey = start["X"], start["Y"], end["X"], end["Y"]
    dz = end["Z"] - start["Z"]
    chord = math.hypot(ex - sx, ey - sy)
    if "R" in arc:
        radius = abs(arc["R"] * scale)
        if radius == 0 or chord == 0:
            return math.hypot(chord, dz)
        angle = 2 * math.asin(min(1.0, chord / (2 * radius)))
        if arc["R"] < 0:
            angle = 2 * math.pi - angle
        planar = radius * angle
    else:
        cx = sx + arc.get("I", 0.0) * scale
        cy = sy + arc.get("J", 0.0) * scale
        radius = math.hypot(sx - cx, sy - cy)
        if radius == 0:
            return math.hypot(chord, dz)
        a0 = math.atan2(sy - cy, sx - cx)
        a1 = math.atan2(ey - cy, ex - cx)
        sweep = (a0 - a1 if clockwise else a1 - a0) % (2 * math.pi)
        if sweep < 1e-9:
            sweep = 2 * math.pi  # จุดเริ่ม = จุดจบ คือวงกลมเต็มวง
        planar = radius * sweep
    return math.hypot(planar, dz)


def analyze_gcode(text, rapid=RAPID_MM_PER_MIN):
    """ประมาณเวลาเครื่อง (นาที) และแยกเวลาตามเบอร์ทูล (T) จาก G-code ระนาบ XY"""
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    scale, absolute, motion, feed, tool = 1.0, True, None, 0.0, None
    per_tool, total, lines, warnings = {}, 0.0, 0, set()
    for raw in text.splitlines():
        words = WORD_RE.findall(COMMENT_RE.sub("", raw).upper())
        if not words:
            continue
        lines += 1
        gcodes, axes, arc, new_feed, dwell = [], {}, {}, None, None
        for letter, value in words:
            number = float(value)
            if letter == "G":
                gcodes.append(number)
            elif letter == "T":
                tool = int(number)
                per_tool.setdefault(tool, 0.0)
            elif letter == "F":
                new_feed = number
            elif letter in "XYZ":
                axes[letter] = number
            elif letter in "IJR":
                arc[letter] = number
            elif letter == "P":
                dwell = number
        for g in gcodes:
            if g in (0, 1, 2, 3):
                motion = int(g)
            elif g == 20:
                scale = 25.4
            elif g == 21:
                scale = 1.0
            elif g == 90:
                absolute = True
            elif g == 91:
                absolute = False
        if new_feed is not None:
            feed = new_feed * scale
        if 4 in gcodes:
            minutes = (dwell or 0) / 60  # GRBL: P เป็นวินาที
            total += minutes
            per_tool[tool] = per_tool.get(tool, 0.0) + minutes
            continue
        if any(g in (28, 30, 53, 92) for g in gcodes) or not axes or motion is None:
            continue
        target = dict(pos)
        for axis, value in axes.items():
            target[axis] = value * scale if absolute else pos[axis] + value * scale
        if motion in (2, 3):
            distance = arc_length(pos, target, arc, scale, clockwise=motion == 2)
        else:
            distance = math.dist((pos["X"], pos["Y"], pos["Z"]), (target["X"], target["Y"], target["Z"]))
        if motion == 0:
            minutes = distance / rapid
        elif feed > 0:
            minutes = distance / feed
        else:
            minutes = 0.0
            if distance > 0:
                warnings.add("พบคำสั่งตัดที่ไม่มีค่า F — เวลาบางส่วนอาจขาดไป")
        total += minutes
        per_tool[tool] = per_tool.get(tool, 0.0) + minutes
        pos = target
    tools = [{"tool_number": t, "minutes": round(m, 2)}
             for t, m in sorted(per_tool.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
             if t is not None or m > 0]
    return {"lines": lines, "minutes": round(total, 2), "tools": tools, "warnings": sorted(warnings)}


def analyze_endpoint(conn, body, query):
    return analyze_gcode(str(body.get("gcode") or ""))


# ---------- โปรแกรม G-code ----------

def get_program(conn, program_id, with_gcode=True):
    row = conn.execute(
        """SELECT pg.*, p.code AS product_code, p.name AS product_name
           FROM programs pg LEFT JOIN products p ON p.id = pg.product_id
           WHERE pg.id = ?""", (program_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ไม่พบโปรแกรมนี้")
    program = dict(row)
    program["gcode_lines"] = len(program["gcode"].splitlines())
    if not with_gcode:
        del program["gcode"]
    program["materials"] = rows(conn.execute(
        """SELECT pm.material_id, pm.qty_per_piece, m.code, m.name, m.unit, m.qty AS stock
           FROM program_materials pm JOIN materials m ON m.id = pm.material_id
           WHERE pm.program_id = ? ORDER BY m.code""", (program_id,)))
    program["tools"] = rows(conn.execute(
        """SELECT pt.tool_id, pt.minutes_per_piece, t.code, t.name, t.tool_number
           FROM program_tools pt JOIN tools t ON t.id = pt.tool_id
           WHERE pt.program_id = ? ORDER BY t.tool_number, t.code""", (program_id,)))
    return program


def list_programs(conn, body, query):
    ids = [r[0] for r in conn.execute("SELECT id FROM programs ORDER BY name")]
    return [get_program(conn, pid, with_gcode=False) for pid in ids]


def get_program_endpoint(conn, body, query, program_id):
    return get_program(conn, program_id)


def download_gcode(conn, body, query, program_id):
    program = get_program(conn, program_id)
    filename = program["filename"] or f"program-{program_id}.nc"
    return Raw(program["gcode"].encode("utf-8"), "text/plain; charset=utf-8", filename)


def save_program(conn, body, program_id=None):
    existing = get_program(conn, program_id) if program_id else None
    name = to_str(body.get("name"), "name", required=True)
    filename = to_str(body.get("filename"), "filename") or (existing or {}).get("filename")
    gcode = body.get("gcode")
    if gcode is None:
        gcode = existing["gcode"] if existing else ""
    gcode = str(gcode)
    product_id = to_int(body.get("product_id"), "product_id")
    if product_id is not None:
        get_item(conn, "products", product_id)
    est = to_float(body.get("est_minutes"), "est_minutes")
    if est is None:
        est = analyze_gcode(gcode)["minutes"]
    if est < 0:
        raise ApiError(400, "เวลาต่อชิ้นต้องไม่ติดลบ")

    materials = {}
    for entry in body.get("materials") or []:
        material_id = to_int(entry.get("material_id"), "วัตถุดิบ", required=True)
        qty = to_float(entry.get("qty_per_piece"), "จำนวนวัตถุดิบต่อชิ้น", required=True)
        if qty <= 0:
            raise ApiError(400, "จำนวนวัตถุดิบต่อชิ้นต้องมากกว่า 0")
        get_item(conn, "materials", material_id)
        materials[material_id] = materials.get(material_id, 0) + qty
    tools = {}
    for entry in body.get("tools") or []:
        tool_id = to_int(entry.get("tool_id"), "ดอกกัด", required=True)
        minutes = to_float(entry.get("minutes_per_piece"), "เวลาต่อชิ้นของดอกกัด") or 0.0
        if minutes < 0:
            raise ApiError(400, "เวลาของดอกกัดต้องไม่ติดลบ")
        get_item(conn, "tools", tool_id)
        tools[tool_id] = tools.get(tool_id, 0) + minutes

    if existing:
        conn.execute(
            "UPDATE programs SET name = ?, filename = ?, product_id = ?, gcode = ?, est_minutes = ? WHERE id = ?",
            (name, filename, product_id, gcode, est, program_id))
        conn.execute("DELETE FROM program_materials WHERE program_id = ?", (program_id,))
        conn.execute("DELETE FROM program_tools WHERE program_id = ?", (program_id,))
    else:
        program_id = conn.execute(
            "INSERT INTO programs (name, filename, product_id, gcode, est_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, filename, product_id, gcode, est, now())).lastrowid
    conn.executemany("INSERT INTO program_materials VALUES (?, ?, ?)",
                     [(program_id, mid, qty) for mid, qty in materials.items()])
    conn.executemany("INSERT INTO program_tools VALUES (?, ?, ?)",
                     [(program_id, tid, minutes) for tid, minutes in tools.items()])
    return get_program(conn, program_id)


def create_program(conn, body, query):
    return save_program(conn, body)


def update_program(conn, body, query, program_id):
    return save_program(conn, body, program_id)


def delete_program(conn, body, query, program_id):
    get_program(conn, program_id, with_gcode=False)
    if conn.execute("SELECT 1 FROM jobs WHERE program_id = ?", (program_id,)).fetchone():
        raise ApiError(409, "ลบไม่ได้ เพราะมีงาน CNC ที่ใช้โปรแกรมนี้อยู่")
    conn.execute("DELETE FROM programs WHERE id = ?", (program_id,))
    return {"ok": True}


# ---------- งาน CNC ----------

JOB_SELECT = """
    SELECT j.*, pg.name AS program_name, pg.est_minutes, pg.product_id,
           p.code AS product_code, p.name AS product_name, p.unit AS product_unit
    FROM jobs j
    JOIN programs pg ON pg.id = j.program_id
    LEFT JOIN products p ON p.id = pg.product_id
"""


def get_job(conn, job_id):
    row = conn.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if row is None:
        raise ApiError(404, "ไม่พบงานนี้")
    return dict(row)


def list_jobs(conn, body, query):
    status = (query.get("status") or [""])[0]
    if status in JOB_STATUS:
        return rows(conn.execute(JOB_SELECT + " WHERE j.status = ? ORDER BY j.id DESC", (status,)))
    return rows(conn.execute(JOB_SELECT + " ORDER BY j.id DESC"))


def create_job(conn, body, query):
    program_id = to_int(body.get("program_id"), "โปรแกรม", required=True)
    get_program(conn, program_id, with_gcode=False)
    quantity = to_int(body.get("quantity"), "จำนวนที่จะผลิต", required=True)
    if quantity < 1:
        raise ApiError(400, "จำนวนที่จะผลิตต้องอย่างน้อย 1")
    note = to_str(body.get("note"), "note")
    job_id = conn.execute(
        "INSERT INTO jobs (program_id, quantity, note, created_at) VALUES (?, ?, ?, ?)",
        (program_id, quantity, note, now())).lastrowid
    return get_job(conn, job_id)


def require_status(job, *allowed):
    if job["status"] not in allowed:
        raise ApiError(409, f"งานนี้อยู่ในสถานะ \"{JOB_STATUS[job['status']]}\" ทำรายการนี้ไม่ได้")


def start_job(conn, body, query, job_id):
    """เริ่มงาน: เบิกวัตถุดิบออกจากสต็อกตามจำนวนที่จะผลิต"""
    job = get_job(conn, job_id)
    require_status(job, "planned")
    program = get_program(conn, job["program_id"], with_gcode=False)
    needs = [(m, m["qty_per_piece"] * job["quantity"]) for m in program["materials"]]
    short = [f"{m['code']} ต้องใช้ {need:g} มี {m['stock']:g} {m['unit']}"
             for m, need in needs if m["stock"] < need]
    if short:
        raise ApiError(409, "วัตถุดิบไม่พอ: " + ", ".join(short))
    for m, need in needs:
        change_stock(conn, "materials", m["material_id"], -need, f"เบิกใช้งาน CNC #{job_id}", job_id)
    conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?", (now(), job_id))
    return get_job(conn, job_id)


def complete_job(conn, body, query, job_id):
    """จบงาน: รับชิ้นงานดีเข้าคลัง และบันทึกเวลาใช้งานดอกกัด"""
    job = get_job(conn, job_id)
    require_status(job, "running")
    good = to_int(body.get("good_qty"), "จำนวนชิ้นงานดี")
    good = job["quantity"] if good is None else good
    if not 0 <= good <= job["quantity"]:
        raise ApiError(400, f"จำนวนชิ้นงานดีต้องอยู่ระหว่าง 0 ถึง {job['quantity']}")
    program = get_program(conn, job["program_id"], with_gcode=False)
    planned = program["est_minutes"] * job["quantity"]
    actual = to_float(body.get("machine_minutes"), "เวลาเครื่องจริง")
    if actual is not None and actual < 0:
        raise ApiError(400, "เวลาเครื่องต้องไม่ติดลบ")
    machine_minutes = planned if actual is None else actual
    # ถ้ากรอกเวลาจริง ให้กระจายเวลานั้นไปแต่ละดอกตามสัดส่วนเวลาต่อชิ้นของดอก
    tool_total = sum(t["minutes_per_piece"] for t in program["tools"]) * job["quantity"]
    ratio = actual / tool_total if actual is not None and tool_total > 0 else 1.0
    for t in program["tools"]:
        used = t["minutes_per_piece"] * job["quantity"] * ratio
        if used:
            conn.execute("UPDATE tools SET used_minutes = used_minutes + ? WHERE id = ?", (used, t["tool_id"]))
    if program["product_id"] and good > 0:
        change_stock(conn, "products", program["product_id"], good, f"รับชิ้นงานจาก CNC #{job_id}", job_id)
    conn.execute(
        "UPDATE jobs SET status = 'done', good_qty = ?, machine_minutes = ?, finished_at = ? WHERE id = ?",
        (good, machine_minutes, now(), job_id))
    return get_job(conn, job_id)


def cancel_job(conn, body, query, job_id):
    """ยกเลิกงาน: ถ้าเบิกวัตถุดิบไปแล้วให้คืนเข้าสต็อก"""
    job = get_job(conn, job_id)
    require_status(job, "planned", "running")
    taken = conn.execute(
        "SELECT item_id, SUM(delta) FROM movements WHERE job_id = ? AND item_type = 'materials' GROUP BY item_id",
        (job_id,)).fetchall()
    for material_id, total in taken:
        if total:
            change_stock(conn, "materials", material_id, -total, f"คืนวัตถุดิบ ยกเลิกงาน CNC #{job_id}", job_id)
    conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ?", (now(), job_id))
    return get_job(conn, job_id)


# ---------- ภาพรวม ----------

def summary(conn, body, query):
    count = lambda table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return {
        "counts": {name: count(name) for name in ("materials", "tools", "products", "programs")},
        "low_materials": rows(conn.execute(
            "SELECT * FROM materials WHERE min_qty > 0 AND qty <= min_qty ORDER BY qty / min_qty")),
        "worn_tools": rows(conn.execute(
            "SELECT * FROM tools WHERE life_minutes > 0 AND used_minutes >= life_minutes * 0.8 "
            "ORDER BY used_minutes / life_minutes DESC")),
        "jobs": {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")},
        "active_jobs": rows(conn.execute(JOB_SELECT + " WHERE j.status IN ('planned', 'running') ORDER BY j.id")),
        "recent_movements": list_movements(conn, {}, {"limit": ["10"]}),
    }


# ---------- เส้นทาง API ----------

ROUTES = []


def route(method, pattern, handler):
    ROUTES.append((method, re.compile(f"^/api{pattern}$"), handler))


RES = "(materials|tools|products)"
ID = r"(\d+)"
route("GET", "/summary", summary)
route("GET", f"/{RES}", list_items)
route("POST", f"/{RES}", create_item)
route("PUT", f"/{RES}/{ID}", update_item)
route("DELETE", f"/{RES}/{ID}", delete_item)
route("POST", f"/{RES}/{ID}/adjust", adjust_item)
route("POST", f"/tools/{ID}/replace", replace_tool)
route("GET", "/movements", list_movements)
route("POST", "/gcode/analyze", analyze_endpoint)
route("GET", "/programs", list_programs)
route("POST", "/programs", create_program)
route("GET", f"/programs/{ID}", get_program_endpoint)
route("GET", f"/programs/{ID}/gcode", download_gcode)
route("PUT", f"/programs/{ID}", update_program)
route("DELETE", f"/programs/{ID}", delete_program)
route("GET", "/jobs", list_jobs)
route("POST", "/jobs", create_job)
route("POST", f"/jobs/{ID}/start", start_job)
route("POST", f"/jobs/{ID}/complete", complete_job)
route("POST", f"/jobs/{ID}/cancel", cancel_job)

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TPYInventory/1.0"

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self.send_json(405, {"error": "Method not allowed"})
            return self.serve_static(url.path)
        try:
            body = self.read_json() if method in ("POST", "PUT") else {}
            for route_method, pattern, handler in ROUTES:
                match = pattern.match(url.path)
                if route_method == method and match:
                    args = [int(g) if g.isdigit() else g for g in match.groups()]
                    conn = connect()
                    try:
                        with conn:
                            result = handler(conn, body, parse_qs(url.query), *args)
                    finally:
                        conn.close()
                    return self.send_result(result)
            raise ApiError(404, "ไม่พบ API นี้")
        except ApiError as err:
            self.send_json(err.status, {"error": err.message})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"error": "เกิดข้อผิดพลาดในเซิร์ฟเวอร์"})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "ไฟล์ใหญ่เกินไป (สูงสุด 20 MB)")
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "ข้อมูลที่ส่งมาไม่ใช่ JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "ข้อมูลที่ส่งมาต้องเป็น JSON object")
        return data

    def send_result(self, result):
        if isinstance(result, Raw):
            self.send_response(200)
            self.send_header("Content-Type", result.content_type)
            if result.filename:
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(result.filename)}")
            self.send_header("Content-Length", str(len(result.body)))
            self.end_headers()
            self.wfile.write(result.body)
        else:
            self.send_json(200, result)

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
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
        self.end_headers()
        self.wfile.write(data)


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
