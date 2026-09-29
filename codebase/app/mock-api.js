// โหมดตัวอย่าง: จำลอง API ของ server.py ในเบราว์เซอร์ พร้อมข้อมูลตัวอย่าง
// ใช้เปิดหน้าเว็บได้ทันทีโดยไม่ต้องรัน Python (เช่นใน Claude Design) ข้อมูลหายเมื่อรีเฟรช
(() => {
  "use strict";

  const stamp = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const now = () => stamp(new Date());
  const ago = (days, hours = 0) => stamp(new Date(Date.now() - (days * 24 + hours) * 3600000));

  const db = {
    departments: [
      { id: 1, name: "งานผู้ป่วยนอก (OPD)", active: 1 },
      { id: 2, name: "ห้องฉุกเฉิน (ER)", active: 1 },
      { id: 3, name: "หอผู้ป่วยใน (IPD)", active: 1 },
      { id: 4, name: "กลุ่มงานทันตกรรม", active: 1 },
    ],
    users: [
      { id: 1, username: "admin", full_name: "เจ้าหน้าที่คลังพัสดุ", role: "admin", department_id: null, active: 1 },
      { id: 2, username: "opd01", full_name: "พยาบาลตัวอย่าง OPD", role: "dept", department_id: 1, active: 1 },
      { id: 3, username: "er01", full_name: "พยาบาลตัวอย่าง ER", role: "dept", department_id: 2, active: 1 },
      { id: 4, username: "ipd01", full_name: "พยาบาลตัวอย่าง IPD", role: "dept", department_id: 3, active: 1 },
    ],
    items: [
      { id: 1, code: "MED-001", name: "ถุงมือยาง ไซส์ M", category: "วัสดุการแพทย์", unit: "กล่อง", qty: 32, min_qty: 10, active: 1 },
      { id: 2, code: "MED-002", name: "สำลีก้อน 450 กรัม", category: "วัสดุการแพทย์", unit: "ห่อ", qty: 4, min_qty: 10, active: 1 },
      { id: 3, code: "MED-003", name: "แอลกอฮอล์ 70% 450 มล.", category: "วัสดุการแพทย์", unit: "ขวด", qty: 48, min_qty: 12, active: 1 },
      { id: 4, code: "MED-004", name: "ผ้าก๊อซ 3x3 นิ้ว", category: "วัสดุการแพทย์", unit: "ห่อ", qty: 120, min_qty: 30, active: 1 },
      { id: 5, code: "MED-005", name: "หน้ากากอนามัย", category: "วัสดุการแพทย์", unit: "กล่อง", qty: 6, min_qty: 8, active: 1 },
      { id: 6, code: "MED-006", name: "กระบอกฉีดยา 3 มล.", category: "วัสดุการแพทย์", unit: "กล่อง", qty: 25, min_qty: 5, active: 1 },
      { id: 7, code: "OFF-001", name: "กระดาษ A4 80 แกรม", category: "วัสดุสำนักงาน", unit: "รีม", qty: 40, min_qty: 10, active: 1 },
      { id: 8, code: "OFF-002", name: "ปากกาลูกลื่น สีน้ำเงิน", category: "วัสดุสำนักงาน", unit: "ด้าม", qty: 150, min_qty: 20, active: 1 },
      { id: 9, code: "CLN-001", name: "น้ำยาล้างพื้น 3.8 ลิตร", category: "วัสดุงานบ้าน", unit: "แกลลอน", qty: 9, min_qty: 4, active: 1 },
      { id: 10, code: "CLN-002", name: "ถุงขยะสีแดง (ติดเชื้อ)", category: "วัสดุงานบ้าน", unit: "แพ็ค", qty: 0, min_qty: 5, active: 0 },
    ],
    requisitions: [
      { id: 1, doc_no: "REQ2569-0001", department_id: 1, created_by: 2, requester_name: "พยาบาลตัวอย่าง OPD", note: "ใช้ประจำเดือน",
        status: "issued", created_at: ago(6), approver_name: "หัวหน้ากลุ่มงานบริหาร", approved_at: ago(6, -2),
        issuer_name: "เจ้าหน้าที่คลังพัสดุ", receiver_name: "พยาบาลตัวอย่าง OPD", issued_at: ago(5) },
      { id: 2, doc_no: "REQ2569-0002", department_id: 2, created_by: 3, requester_name: "พยาบาลตัวอย่าง ER", note: null,
        status: "approved", created_at: ago(1), approver_name: "หัวหน้ากลุ่มงานบริหาร", approved_at: ago(0, 20) },
      { id: 3, doc_no: "REQ2569-0003", department_id: 1, created_by: 2, requester_name: "พยาบาลตัวอย่าง OPD", note: "ด่วน ของหมดตู้",
        status: "pending", created_at: ago(0, 3) },
      { id: 4, doc_no: "REQ2569-0004", department_id: 3, created_by: 4, requester_name: "พยาบาลตัวอย่าง IPD", note: null,
        status: "pending", created_at: ago(0, 1) },
      { id: 5, doc_no: "REQ2569-0005", department_id: 4, created_by: 1, requester_name: "ทันตแพทย์ตัวอย่าง", note: null,
        status: "rejected", created_at: ago(3), approver_name: "หัวหน้ากลุ่มงานบริหาร", approved_at: ago(2),
        reject_reason: "เบิกซ้ำกับใบเบิกเดือนนี้" },
    ],
    lines: [
      { id: 1, requisition_id: 1, item_id: 1, qty_requested: 10, qty_approved: 8, qty_issued: 8 },
      { id: 2, requisition_id: 1, item_id: 7, qty_requested: 5, qty_approved: 5, qty_issued: 5 },
      { id: 3, requisition_id: 2, item_id: 4, qty_requested: 20, qty_approved: 20, qty_issued: null },
      { id: 4, requisition_id: 2, item_id: 3, qty_requested: 6, qty_approved: 4, qty_issued: null },
      { id: 5, requisition_id: 3, item_id: 2, qty_requested: 5, qty_approved: null, qty_issued: null },
      { id: 6, requisition_id: 3, item_id: 5, qty_requested: 3, qty_approved: null, qty_issued: null },
      { id: 7, requisition_id: 4, item_id: 6, qty_requested: 2, qty_approved: null, qty_issued: null },
      { id: 8, requisition_id: 5, item_id: 8, qty_requested: 50, qty_approved: null, qty_issued: null },
    ],
    movements: [],
  };
  let nextId = 100;
  let me = db.users[0];

  const log = (item_id, delta, reason, requisition_id = null, ts = now()) => {
    const item = db.items.find((i) => i.id === item_id);
    item.qty += delta;
    db.movements.unshift({ id: nextId++, ts, item_id, delta, balance: item.qty, reason, requisition_id, user_id: me.id });
  };
  // ยอดยกมาและการจ่ายของใบเบิกแรก
  db.items.forEach((i) => {
    i.qty += i.id === 1 ? 8 : i.id === 7 ? 5 : 0;
    if (i.qty) db.movements.unshift({ id: nextId++, ts: ago(30), item_id: i.id, delta: i.qty, balance: i.qty,
      reason: "ยอดยกมา", requisition_id: null, user_id: 1 });
  });
  log(1, -8, "จ่ายตามใบเบิก REQ2569-0001 (งานผู้ป่วยนอก (OPD))", 1, ago(5));
  log(7, -5, "จ่ายตามใบเบิก REQ2569-0001 (งานผู้ป่วยนอก (OPD))", 1, ago(5));

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }
  const need = (value, label) => {
    const text = String(value ?? "").trim();
    if (!text) throw new ApiError(400, `กรุณาระบุ${label}`);
    return text;
  };
  const dept = (id) => db.departments.find((d) => d.id === Number(id));
  const pub = (u) => u && { ...u, department_name: dept(u.department_id)?.name ?? null };
  const item = (id) => {
    const found = db.items.find((i) => i.id === Number(id));
    if (!found) throw new ApiError(404, "ไม่พบสินค้านี้");
    return found;
  };
  const STATUS = { pending: "รออนุมัติ", approved: "อนุมัติแล้ว รอจ่าย", issued: "จ่ายแล้ว", rejected: "ไม่อนุมัติ", cancelled: "ยกเลิก" };

  const reqView = (r) => ({
    ...r,
    department_name: dept(r.department_id).name,
    created_by_name: db.users.find((u) => u.id === r.created_by)?.full_name,
    line_count: db.lines.filter((l) => l.requisition_id === r.id).length,
  });
  const getReq = (id) => {
    const r = db.requisitions.find((x) => x.id === Number(id));
    if (!r || (me.role !== "admin" && r.department_id !== me.department_id)) throw new ApiError(404, "ไม่พบใบเบิกนี้");
    return {
      ...reqView(r),
      lines: db.lines.filter((l) => l.requisition_id === r.id).map((l) => {
        const i = item(l.item_id);
        return { ...l, code: i.code, name: i.name, unit: i.unit, stock: i.qty };
      }),
    };
  };
  const status = (r, ...allowed) => {
    if (!allowed.includes(r.status)) throw new ApiError(409, `ใบเบิกนี้อยู่ในสถานะ "${STATUS[r.status]}" ทำรายการนี้ไม่ได้`);
  };
  const lineQty = (doc, entries, field, fallback) => {
    const given = Object.fromEntries((entries || []).map((e) => [Number(e.line_id), Number(e[field])]));
    return Object.fromEntries(doc.lines.map((l) => {
      const qty = given[l.id] ?? l[fallback];
      if (!(qty >= 0) || qty > l.qty_requested) throw new ApiError(400, `${l.name}: จำนวนไม่ถูกต้อง`);
      return [l.id, qty];
    }));
  };
  const itemValues = (b) => ({
    code: need(b.code, "รหัสสินค้า"), name: need(b.name, "ชื่อสินค้า"), category: String(b.category || "").trim() || null,
    unit: need(b.unit, "หน่วย"), min_qty: Number(b.min_qty) || 0, active: b.active === false || b.active === "0" ? 0 : 1,
  });

  const routes = [
    ["GET", /^\/setup$/, () => ({ needs_setup: false })],
    ["POST", /^\/login$/, (b) => {
      const u = db.users.find((x) => x.username.toLowerCase() === String(b.username || "").toLowerCase());
      if (!u) throw new ApiError(401, "ชื่อผู้ใช้ไม่ถูกต้อง (โหมดตัวอย่าง: admin, opd01, er01, ipd01 รหัสผ่านอะไรก็ได้)");
      if (!u.active) throw new ApiError(403, "บัญชีนี้ถูกปิดใช้งาน ติดต่อผู้ดูแลคลัง");
      me = u;
      return pub(u);
    }],
    ["POST", /^\/logout$/, () => ({ ok: true })],
    ["GET", /^\/me$/, () => pub(me)],
    ["POST", /^\/me\/password$/, () => ({ ok: true })],
    ["GET", /^\/departments$/, () => db.departments.filter((d) => me.role === "admin" || d.active)],
    ["POST", /^\/departments$/, (b) => {
      const d = { id: nextId++, name: need(b.name, "ชื่อหน่วยงาน"), active: b.active === false ? 0 : 1 };
      db.departments.push(d);
      return d;
    }],
    ["PUT", /^\/departments\/(\d+)$/, (b, id) => Object.assign(dept(id), { name: need(b.name, "ชื่อหน่วยงาน"), active: b.active === false ? 0 : 1 })],
    ["GET", /^\/users$/, () => db.users.map(pub)],
    ["POST", /^\/users$/, (b) => {
      const u = { id: nextId++, username: need(b.username, "ชื่อผู้ใช้"), full_name: need(b.full_name, "ชื่อ-นามสกุล"), role: b.role,
        department_id: b.department_id ? Number(b.department_id) : null, active: 1 };
      db.users.push(u);
      return pub(u);
    }],
    ["PUT", /^\/users\/(\d+)$/, (b, id) => pub(Object.assign(db.users.find((u) => u.id === id), {
      full_name: need(b.full_name, "ชื่อ-นามสกุล"), role: b.role, department_id: b.department_id ? Number(b.department_id) : null,
      active: b.active === false ? 0 : 1,
    }))],
    ["GET", /^\/items$/, (b, q) => db.items.filter((i) => (me.role === "admin" && q.get("all") === "1") || i.active)],
    ["POST", /^\/items$/, (b) => {
      const i = { id: nextId++, qty: 0, ...itemValues(b) };
      db.items.push(i);
      if (Number(b.initial_qty) > 0) log(i.id, Number(b.initial_qty), "ยอดยกมา");
      return i;
    }],
    ["PUT", /^\/items\/(\d+)$/, (b, id) => Object.assign(item(id), itemValues(b))],
    ["POST", /^\/items\/(\d+)\/adjust$/, (b, id) => {
      const i = item(id);
      const delta = Number(b.delta);
      if (!delta) throw new ApiError(400, "จำนวนต้องไม่เป็นศูนย์");
      if (i.qty + delta < 0) throw new ApiError(409, `สต็อกไม่พอ (คงเหลือ ${i.qty} ${i.unit})`);
      log(i.id, delta, b.reason || (delta > 0 ? "รับเข้า" : "ปรับลด"));
      return i;
    }],
    ["GET", /^\/movements$/, (b, q) => db.movements
      .filter((m) => !q.get("item_id") || m.item_id === Number(q.get("item_id")))
      .map((m) => {
        const i = item(m.item_id);
        return { ...m, code: i.code, name: i.name, unit: i.unit, user_name: db.users.find((u) => u.id === m.user_id)?.full_name,
          doc_no: db.requisitions.find((r) => r.id === m.requisition_id)?.doc_no };
      })],
    ["GET", /^\/requisitions$/, (b, q) => db.requisitions
      .filter((r) => (me.role === "admin" || r.department_id === me.department_id) && (!q.get("status") || r.status === q.get("status")))
      .slice().reverse().map(reqView)],
    ["POST", /^\/requisitions$/, (b) => {
      const department_id = me.role === "admin" ? Number(b.department_id) : me.department_id;
      if (!dept(department_id)) throw new ApiError(400, "กรุณาเลือกหน่วยงาน");
      if (!(b.lines || []).length) throw new ApiError(400, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ");
      const r = { id: nextId++, doc_no: `REQ2569-${String(db.requisitions.length + 1).padStart(4, "0")}`, department_id,
        created_by: me.id, requester_name: need(b.requester_name, "ชื่อผู้เบิก"), note: b.note || null, status: "pending", created_at: now() };
      db.requisitions.push(r);
      b.lines.forEach((l) => db.lines.push({ id: nextId++, requisition_id: r.id, item_id: item(l.item_id).id,
        qty_requested: Number(l.qty), qty_approved: null, qty_issued: null }));
      return getReq(r.id);
    }],
    ["GET", /^\/requisitions\/(\d+)$/, (b, id) => getReq(id)],
    ["POST", /^\/requisitions\/(\d+)\/cancel$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "pending");
      db.requisitions.find((r) => r.id === id).status = "cancelled";
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/approve$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "pending");
      const approver = need(b.approver_name, "ชื่อผู้อนุมัติ");
      const qty = lineQty(doc, b.lines, "qty_approved", "qty_requested");
      db.lines.filter((l) => l.requisition_id === id).forEach((l) => (l.qty_approved = qty[l.id]));
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "approved", approver_name: approver, approved_at: now() });
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/reject$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "pending", "approved");
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "rejected",
        approver_name: need(b.approver_name, "ชื่อผู้อนุมัติ"), reject_reason: need(b.reason, "เหตุผล"), approved_at: now() });
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/issue$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "approved");
      const issuer = need(b.issuer_name, "ชื่อผู้จ่าย");
      const receiver = need(b.receiver_name, "ชื่อผู้รับ");
      const qty = lineQty(doc, b.lines, "qty_issued", "qty_approved");
      const short = doc.lines.filter((l) => qty[l.id] > l.stock).map((l) => `${l.name} ต้องจ่าย ${qty[l.id]} คงเหลือ ${l.stock} ${l.unit}`);
      if (short.length) throw new ApiError(409, "สต็อกไม่พอ: " + short.join(", "));
      db.lines.filter((l) => l.requisition_id === id).forEach((l) => {
        l.qty_issued = qty[l.id];
        if (l.qty_issued) log(l.item_id, -l.qty_issued, `จ่ายตามใบเบิก ${doc.doc_no} (${doc.department_name})`, id);
      });
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "issued", issuer_name: issuer, receiver_name: receiver, issued_at: now() });
      return getReq(id);
    }],
    ["GET", /^\/summary$/, () => {
      const counts = {};
      db.requisitions.forEach((r) => (counts[r.status] = (counts[r.status] || 0) + 1));
      const issued = {};
      db.movements.filter((m) => m.requisition_id && m.ts >= ago(30)).forEach((m) => (issued[m.item_id] = (issued[m.item_id] || 0) - m.delta));
      return {
        status_counts: counts,
        item_count: db.items.filter((i) => i.active).length,
        department_count: db.departments.filter((d) => d.active).length,
        low_stock: db.items.filter((i) => i.active && i.min_qty > 0 && i.qty <= i.min_qty),
        waiting: db.requisitions.filter((r) => ["pending", "approved"].includes(r.status)).map(reqView),
        top_items: Object.entries(issued).sort((a, b) => b[1] - a[1]).slice(0, 10)
          .map(([id, n]) => ({ ...item(id), issued: n })),
      };
    }],
  ];

  const json = (status, data) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const at = url.pathname.indexOf("/api/");
    if (at === -1) return realFetch(input, init);
    const path = url.pathname.slice(at + 4);
    const method = (init.method || "GET").toUpperCase();
    const body = init.body ? JSON.parse(init.body) : {};
    await new Promise((r) => setTimeout(r, 80)); // หน่วงนิดหน่อยให้เหมือนเรียกเซิร์ฟเวอร์จริง
    try {
      for (const [m, pattern, handler] of routes) {
        const match = method === m && path.match(pattern);
        if (match) {
          const result = handler(body, match[1] ? Number(match[1]) : url.searchParams);
          return json(200, JSON.parse(JSON.stringify(result)));
        }
      }
      return json(404, { error: "ไม่พบ API นี้" });
    } catch (err) {
      return json(err.status || 500, { error: err.message });
    }
  };
})();
