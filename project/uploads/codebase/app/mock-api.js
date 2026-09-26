// โหมดตัวอย่าง: จำลอง API ของ server.py ในเบราว์เซอร์ พร้อมข้อมูลตัวอย่าง
// ใช้เปิดหน้าเว็บได้ทันทีโดยไม่ต้องรัน Python (เช่นใน Claude Design) ข้อมูลหายเมื่อรีเฟรช
(() => {
  "use strict";

  const stamp = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  const now = () => stamp(new Date());
  const ago = (days, hours = 0) => stamp(new Date(Date.now() - (days * 24 + hours) * 3600000));
  const later = (ts, hours) => stamp(new Date(new Date(ts).getTime() + hours * 3600000));
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const pick = (list) => list[Math.floor(rnd() * list.length)];

  const WAREHOUSES = [
    { id: 1, code: "DRG", name: "คลังยา", initials: "ยา", hue: 175, description: "ยาเม็ด ยาน้ำ ยาฉีด และยาใช้ภายนอก" },
    { id: 2, code: "MED", name: "คลังเวชภัณฑ์มิใช่ยา", initials: "วช", hue: 172, description: "ถุงมือ สำลี ผ้าก๊อซ กระบอกฉีดยา และวัสดุการแพทย์" },
    { id: 3, code: "HRB", name: "คลังยาสมุนไพร", initials: "สม", hue: 145, description: "ยาสมุนไพรและผลิตภัณฑ์แพทย์แผนไทย" },
    { id: 4, code: "LAB", name: "คลังเทคนิคการแพทย์", initials: "ทน", hue: 220, description: "น้ำยาตรวจ และวัสดุห้องปฏิบัติการ" },
    { id: 5, code: "DEN", name: "คลังทันตกรรม", initials: "ทต", hue: 260, description: "วัสดุและอุปกรณ์สิ้นเปลืองงานทันตกรรม" },
    { id: 6, code: "SUP", name: "คลังพัสดุ", initials: "พด", hue: 40, description: "วัสดุสำนักงาน วัสดุงานบ้าน และวัสดุทั่วไป" },
    { id: 7, code: "IT", name: "คลังเทคโนโลยีสารสนเทศ", initials: "ทส", hue: 320, description: "คอมพิวเตอร์ อุปกรณ์ต่อพ่วง หมึกพิมพ์ และวัสดุไอที" },
  ];
  // [warehouse_id, code, name, unit, qty, min_qty]
  const ITEMS = [
    [1, "DRG-001", "พาราเซตามอล 500 มก. (1,000 เม็ด)", "กระปุก", 24, 6], [1, "DRG-002", "อะม็อกซีซิลลิน 500 มก.", "กล่อง", 12, 5],
    [1, "DRG-003", "น้ำเกลือ NSS 1,000 มล.", "ขวด", 80, 20], [1, "DRG-004", "ผงเกลือแร่ ORS", "กล่อง", 30, 10],
    [1, "DRG-005", "ยาแก้ไอน้ำดำ 60 มล.", "ขวด", 6, 12], [1, "DRG-006", "เมทฟอร์มิน 500 มก.", "กระปุก", 18, 6],
    [2, "MED-001", "ถุงมือยาง ไซส์ M", "กล่อง", 32, 10], [2, "MED-002", "สำลีก้อน 450 กรัม", "ห่อ", 4, 10],
    [2, "MED-003", "แอลกอฮอล์ 70% 450 มล.", "ขวด", 48, 12], [2, "MED-004", "ผ้าก๊อซ 3x3 นิ้ว", "ห่อ", 120, 30],
    [2, "MED-005", "หน้ากากอนามัย", "กล่อง", 6, 8], [2, "MED-006", "กระบอกฉีดยา 3 มล.", "กล่อง", 25, 5],
    [3, "HRB-001", "ฟ้าทะลายโจร แคปซูล", "ขวด", 40, 10], [3, "HRB-002", "ขมิ้นชัน แคปซูล", "ขวด", 25, 10],
    [3, "HRB-003", "ยาหอมนวโกฐ", "กล่อง", 8, 5], [3, "HRB-004", "ยาอมมะแว้ง", "ซอง", 60, 20], [3, "HRB-005", "ครีมไพล", "หลอด", 3, 10],
    [4, "LAB-001", "หลอดเก็บเลือด EDTA", "กล่อง", 20, 5], [4, "LAB-002", "แถบตรวจน้ำตาลในเลือด", "กล่อง", 5, 8],
    [4, "LAB-003", "สไลด์แก้ว", "กล่อง", 14, 4], [4, "LAB-004", "เข็มเจาะเลือดปลายนิ้ว", "กล่อง", 30, 10], [4, "LAB-005", "ชุดตรวจ ATK", "กล่อง", 0, 5],
    [5, "DEN-001", "เข็มฉีดยาชาทันตกรรม", "กล่อง", 10, 4], [5, "DEN-002", "ยาชาลิโดเคน คาร์ทริดจ์", "กล่อง", 8, 4],
    [5, "DEN-003", "สำลีม้วนทันตกรรม", "ห่อ", 22, 6], [5, "DEN-004", "วัสดุอุดฟัน GIC", "ชุด", 3, 4], [5, "DEN-005", "ผ้ากันเปื้อนผู้ป่วย", "แพ็ค", 15, 5],
    [6, "SUP-001", "กระดาษ A4 80 แกรม", "รีม", 40, 10], [6, "SUP-002", "ปากกาลูกลื่น สีน้ำเงิน", "ด้าม", 150, 20],
    [6, "SUP-003", "แฟ้มเอกสาร", "เล่ม", 35, 10], [6, "SUP-004", "หมึกพิมพ์เลเซอร์", "ตลับ", 4, 3],
    [6, "SUP-005", "น้ำยาล้างพื้น 3.8 ลิตร", "แกลลอน", 9, 4], [6, "SUP-006", "ถุงขยะสีแดง (ติดเชื้อ)", "แพ็ค", 0, 5],
    [7, "IT-001", "เมาส์ USB", "อัน", 15, 5], [7, "IT-002", "คีย์บอร์ด USB", "อัน", 8, 3],
    [7, "IT-003", "หมึกพิมพ์เลเซอร์ HP 85A", "ตลับ", 6, 4], [7, "IT-004", "สาย LAN CAT6 3 เมตร", "เส้น", 20, 5],
    [7, "IT-005", "แฟลชไดรฟ์ 32 GB", "อัน", 2, 5], [7, "IT-006", "กระดาษสติกเกอร์บาร์โค้ด", "ม้วน", 12, 6],
  ];

  const db = {
    warehouses: WAREHOUSES,
    departments: [
      { id: 1, code: "OPD", name: "งานผู้ป่วยนอก (OPD)", group_name: "กลุ่มการพยาบาล", active: 1 },
      { id: 2, code: "ER", name: "ห้องฉุกเฉิน (ER)", group_name: "กลุ่มการพยาบาล", active: 1 },
      { id: 3, code: "IPD-M", name: "ผู้ป่วยในชาย", group_name: "กลุ่มการพยาบาล", active: 1 },
      { id: 4, code: "IPD-F", name: "ผู้ป่วยในหญิง", group_name: "กลุ่มการพยาบาล", active: 1 },
      { id: 5, code: "LR", name: "ห้องคลอด", group_name: "กลุ่มการพยาบาล", active: 1 },
      { id: 6, code: "DEN", name: "งานทันตกรรม", group_name: "กลุ่มงานทันตกรรม", active: 1 },
      { id: 7, code: "LAB", name: "งานชันสูตร (LAB)", group_name: "กลุ่มงานเทคนิคการแพทย์", active: 1 },
    ],
    // username = เลขบัตรประชาชน 13 หลัก รหัสผ่าน = 5 ตัวท้าย
    users: [
      { id: 1, username: "1103700012345", full_name: "นิพนธ์ วงศ์สวัสดิ์", role: "admin", department_id: null, active: 1 },
      { id: 2, username: "3100600054321", full_name: "สมหญิง ใจดี", role: "dept", department_id: 1, active: 1 },
      { id: 3, username: "1209900067890", full_name: "ธนพล แก้วมณี", role: "dept", department_id: 2, active: 1 },
      { id: 4, username: "3340100024680", full_name: "จันทร์เพ็ญ ทองดี", role: "dept", department_id: 3, active: 1 },
    ],
    items: ITEMS.map(([warehouse_id, code, name, unit, qty, min_qty], i) =>
      ({ id: i + 1, warehouse_id, code, name, unit, qty, min_qty, active: code === "SUP-006" ? 0 : 1 })),
    // ทะเบียนผู้เกี่ยวข้อง: requester = ผู้เบิกสินค้า, receiver = ผู้รับสินค้า, central = เจ้าหน้าที่คลังกลาง
    people: [],
    positions: [],
    requisitions: [],
    lines: [],
    movements: [],
  };
  let nextId = 1000;
  let me = null;

  [
    ["requester", "สมหญิง ใจดี", "พยาบาลวิชาชีพชำนาญการ", 1], ["requester", "วิภาวรรณ ศรีสุข", "หัวหน้างานผู้ป่วยนอก", 1],
    ["requester", "ธนพล แก้วมณี", "พยาบาลวิชาชีพปฏิบัติการ", 2], ["requester", "จันทร์เพ็ญ ทองดี", "พยาบาลวิชาชีพชำนาญการ", 3],
    ["requester", "ศิริพร อินทร์แก้ว", "พยาบาลวิชาชีพชำนาญการ", 5], ["requester", "อนุชา พึ่งบุญ", "นักเทคนิคการแพทย์", 7],
    ["requester", "ปวีณา รักษาดี", "ทันตแพทย์", 6], ["requester", "มณีรัตน์ ศรีวงศ์", "พยาบาลวิชาชีพชำนาญการ", 4],
    ["receiver", "ประเสริฐ มั่นคง", "เจ้าพนักงานธุรการ", 1], ["receiver", "กมลชนก แสงทอง", "ผู้ช่วยเหลือคนไข้", 1],
    ["receiver", "สมชาย บุญมา", "พนักงานทั่วไป", 2], ["receiver", "รัตนา ชัยวงศ์", "ผู้ช่วยเหลือคนไข้", 3],
    ["receiver", "บุญเลิศ สายทอง", "พนักงานทั่วไป", 5], ["receiver", "ชุติมา พรมแก้ว", "เจ้าพนักงานธุรการ", 7],
    ["receiver", "สุนีย์ คงดี", "ผู้ช่วยทันตแพทย์", 6], ["receiver", "วันชัย ทองมา", "พนักงานทั่วไป", 4],
    ["central", "นิพนธ์ วงศ์สวัสดิ์", "เภสัชกรชำนาญการพิเศษ (หัวหน้างานบริหารเวชภัณฑ์)", null],
    ["central", "อรุณี พรหมมา", "เภสัชกรปฏิบัติการ", null], ["central", "สุทธิพงษ์ คำดี", "เจ้าพนักงานเภสัชกรรม", null],
    ["central", "มาลี บุญเรือง", "เจ้าพนักงานพัสดุ", null],
  ].forEach(([kind, full_name, position, department_id]) => db.people.push({ id: nextId++, kind, full_name, position, department_id }));
  [
    ...["พยาบาลวิชาชีพชำนาญการ", "พยาบาลวิชาชีพปฏิบัติการ", "หัวหน้างานผู้ป่วยนอก", "หัวหน้างาน", "เจ้าพนักงานธุรการ", "ผู้ช่วยเหลือคนไข้",
      "นักเทคนิคการแพทย์", "ทันตแพทย์", "ผู้ช่วยทันตแพทย์", "พนักงานทั่วไป"].map((name) => ({ name, scope: "dept" })),
    ...["เภสัชกรชำนาญการพิเศษ (หัวหน้างานบริหารเวชภัณฑ์)", "เภสัชกรปฏิบัติการ", "เจ้าพนักงานเภสัชกรรม", "เจ้าพนักงานพัสดุ"].map((name) => ({ name, scope: "central" })),
  ].forEach((p) => db.positions.push({ id: nextId++, ...p }));

  const byCode = (code) => db.items.find((i) => i.code === code);
  const peopleOf = (kind, department_id) => db.people.filter((p) => p.kind === kind && (kind === "central" || p.department_id === department_id));
  let docSeq = 60;
  const docNo = () => `RQ69-${String(++docSeq).padStart(4, "0")}`;
  const addReq = (r, lines) => {
    const doc = { id: nextId++, doc_no: docNo(), note: null, approver_name: null, approver_position: null, approved_at: null,
      issuer_name: null, issuer_position: null, issued_at: null, receiver_name: null, receiver_position: null, ...r };
    db.requisitions.push(doc);
    Object.entries(lines).forEach(([code, qty]) => db.lines.push({ id: nextId++, requisition_id: doc.id, item_id: byCode(code).id,
      qty_requested: qty, qty_approved: ["approved", "issued"].includes(doc.status) ? qty : null, qty_issued: doc.status === "issued" ? qty : null }));
    return doc;
  };

  // ยอดยกมา
  db.items.forEach((i) => {
    if (i.qty) db.movements.unshift({ id: nextId++, ts: ago(90), item_id: i.id, delta: i.qty, balance: i.qty, reason: "ยอดยกมา", requisition_id: null, user_id: 1 });
  });

  // ประวัติใบเบิก 12 สัปดาห์ (ใช้แสดง Dashboard) — จ่ายแล้วทั้งหมด
  const deptWeight = [1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 7];
  const common = ["DRG-003", "DRG-003", "DRG-001", "DRG-004", "MED-001", "MED-001", "MED-004", "MED-004", "MED-003", "MED-006", "SUP-001", "SUP-002", "SUP-005"];
  const special = { 5: ["DEN-001", "DEN-002", "DEN-003", "DEN-005"], 6: ["DEN-001", "DEN-002", "DEN-003", "DEN-005"], 7: ["LAB-001", "LAB-002", "LAB-003", "LAB-004"] };
  for (let day = 83; day >= 3; day -= 1) {
    const perDay = day % 7 === 0 || day % 7 === 6 ? 0 : rnd() < 0.55 ? 1 : rnd() < 0.5 ? 2 : 0;
    for (let k = 0; k < perDay; k++) {
      const dept = pick(deptWeight);
      const type = rnd() < (dept === 2 ? 0.3 : 0.08) ? "emergency" : "routine";
      const lines = {};
      const pool = special[dept] ? [...special[dept], ...special[dept], ...common] : [...common, "HRB-001", "HRB-004", "LAB-004", "IT-003", "IT-004", "IT-001"];
      const n = 2 + Math.floor(rnd() * 3);
      for (let j = 0; j < n; j++) lines[pick(pool)] = 1 + Math.floor(rnd() * 12);
      const created = ago(day, Math.floor(rnd() * 8));
      const req = pick(peopleOf("requester", dept)) || { full_name: "เจ้าหน้าที่หน่วยงาน", position: null };
      const rec = pick(peopleOf("receiver", dept)) || req;
      const app = db.people.find((p) => p.kind === "central");
      const iss = pick(peopleOf("central").slice(1));
      addReq({ department_id: dept, created_by: 1, req_type: type, status: "issued", created_at: created,
        requester_name: req.full_name, requester_position: req.position,
        approver_name: app.full_name, approver_position: app.position, approved_at: later(created, type === "emergency" ? 1 : 5),
        issuer_name: iss.full_name, issuer_position: iss.position, issued_at: later(created, type === "emergency" ? 2 + rnd() * 3 : 22 + rnd() * 30),
        receiver_name: rec.full_name, receiver_position: rec.position }, lines);
    }
  }
  // ใบเบิกปัจจุบัน
  const named = (kind, name) => db.people.find((p) => p.kind === kind && p.full_name === name);
  const who = (name) => ({ requester_name: name, requester_position: named("requester", name)?.position ?? null });
  addReq({ department_id: 1, created_by: 2, req_type: "routine", status: "issued", created_at: ago(14, 5), ...who("สมหญิง ใจดี"),
    approver_name: "นิพนธ์ วงศ์สวัสดิ์", approver_position: named("central", "นิพนธ์ วงศ์สวัสดิ์").position, approved_at: ago(14, 2),
    issuer_name: "มาลี บุญเรือง", issuer_position: "เจ้าพนักงานพัสดุ", issued_at: ago(13), receiver_name: "ประเสริฐ มั่นคง", receiver_position: "เจ้าพนักงานธุรการ" },
  { "SUP-001": 5, "SUP-002": 20, "SUP-003": 10, "SUP-005": 2 });
  addReq({ department_id: 1, created_by: 2, req_type: "routine", status: "approved", created_at: ago(6, 3), ...who("สมหญิง ใจดี"),
    approver_name: "นิพนธ์ วงศ์สวัสดิ์", approver_position: named("central", "นิพนธ์ วงศ์สวัสดิ์").position, approved_at: ago(5), note: "ขอรับช่วงบ่าย" },
  { "DRG-001": 2, "DRG-004": 5, "MED-001": 4, "MED-003": 6, "MED-004": 10, "MED-005": 2 });
  const board = [
    [2, "emergency", "ธนพล แก้วมณี", "approved", 9, { "DRG-003": 20, "MED-001": 10, "MED-004": 15 }],
    [1, "routine", "สมหญิง ใจดี", "pending", 7, { "DRG-003": 10, "DRG-001": 4, "MED-001": 5, "SUP-001": 5 }],
    [3, "routine", "จันทร์เพ็ญ ทองดี", "pending", 6, { "DRG-003": 30, "MED-004": 20, "MED-003": 6 }],
    [5, "emergency", "ศิริพร อินทร์แก้ว", "pending", 3, { "MED-001": 8, "MED-002": 6, "DRG-003": 12 }],
    [6, "routine", "ปวีณา รักษาดี", "pending", 1, { "DEN-002": 4, "DEN-003": 6, "MED-001": 4 }],
  ];
  board.forEach(([department_id, req_type, name, status, hoursAgo, lines]) => addReq({ department_id, created_by: 1, req_type, status,
    created_at: ago(0, hoursAgo), ...who(name),
    ...(status === "approved" ? { approver_name: "นิพนธ์ วงศ์สวัสดิ์", approver_position: named("central", "นิพนธ์ วงศ์สวัสดิ์").position, approved_at: ago(0, hoursAgo - 1) } : {}),
  }, lines));

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }
  const need = (value, label) => {
    const text = String(value ?? "").trim();
    if (!text) throw new ApiError(400, `กรุณาระบุ${label}`);
    return text;
  };
  const opt = (value) => String(value ?? "").trim() || null;
  const admin = () => { if (me.role !== "admin") throw new ApiError(403, "หน้านี้สำหรับผู้ดูแลคลังกลางเท่านั้น"); };
  const nationalId = (value) => {
    const id = String(value ?? "").replace(/\D/g, "");
    if (id.length !== 13) throw new ApiError(400, "เลขบัตรประชาชนต้องมี 13 หลัก");
    return id;
  };
  const dept = (id) => db.departments.find((d) => d.id === Number(id));
  const wh = (id) => db.warehouses.find((w) => w.id === Number(id));
  const pub = (u) => u && { id: u.id, username: u.username, full_name: u.full_name, role: u.role, department_id: u.department_id, active: u.active,
    department_name: dept(u.department_id)?.name ?? null, department_code: dept(u.department_id)?.code ?? null };
  const item = (id) => {
    const found = db.items.find((i) => i.id === Number(id));
    if (!found) throw new ApiError(404, "ไม่พบสินค้านี้");
    return found;
  };
  const itemView = (i) => ({ ...i, warehouse_name: wh(i.warehouse_id)?.name ?? null });
  const STATUS = { pending: "รออนุมัติ", approved: "อนุมัติแล้ว รอจ่าย", issued: "จ่ายแล้ว", rejected: "ไม่อนุมัติ", cancelled: "ยกเลิก" };

  const reqView = (r) => {
    const lines = db.lines.filter((l) => l.requisition_id === r.id);
    const whIds = [...new Set(lines.map((l) => item(l.item_id).warehouse_id))].sort((a, b) => a - b);
    return {
      ...r,
      department_name: dept(r.department_id).name,
      department_code: dept(r.department_id).code,
      created_by_name: db.users.find((u) => u.id === r.created_by)?.full_name,
      line_count: lines.length,
      warehouses: whIds.map((id) => wh(id).name),
    };
  };
  const getReq = (id) => {
    const r = db.requisitions.find((x) => x.id === Number(id));
    if (!r || (me.role !== "admin" && r.department_id !== me.department_id)) throw new ApiError(404, "ไม่พบใบเบิกนี้");
    return {
      ...reqView(r),
      lines: db.lines.filter((l) => l.requisition_id === r.id).map((l) => {
        const i = item(l.item_id);
        return { ...l, code: i.code, name: i.name, unit: i.unit, stock: i.qty, warehouse_id: i.warehouse_id, warehouse_name: wh(i.warehouse_id).name };
      }).sort((a, b) => a.warehouse_id - b.warehouse_id || a.code.localeCompare(b.code)),
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
  const itemValues = (b) => {
    if (!wh(b.warehouse_id)) throw new ApiError(400, "กรุณาเลือกคลัง");
    return {
      code: need(b.code, "รหัสสินค้า"), name: need(b.name, "ชื่อสินค้า"), warehouse_id: Number(b.warehouse_id),
      unit: need(b.unit, "หน่วย"), min_qty: Number(b.min_qty) || 0, active: b.active === false || b.active === "0" ? 0 : 1,
    };
  };
  // ข้อมูลใบเบิกที่หน่วยงานกรอก (ใช้ทั้งตอนส่งและตอนแก้ไข)
  const reqValues = (b) => {
    if (!["emergency", "routine"].includes(b.req_type)) throw new ApiError(400, "กรุณาเลือกประเภทการเบิก (ฉุกเฉิน หรือ ตามรอบปกติ)");
    if (!(b.lines || []).length) throw new ApiError(400, "กรุณาเลือกสินค้าอย่างน้อย 1 รายการ");
    b.lines.forEach((l) => {
      const i = item(l.item_id);
      if (!i.active) throw new ApiError(400, `${i.name} งดเบิกอยู่`);
      if (!(Number(l.qty) > 0)) throw new ApiError(400, `${i.name}: จำนวนต้องมากกว่า 0`);
    });
    const v = { req_type: b.req_type, note: opt(b.note), requester_name: need(b.requester_name, "ชื่อผู้เบิก") };
    ["requester_position", "approver_name", "approver_position", "issuer_name", "issuer_position", "receiver_name", "receiver_position"]
      .forEach((k) => (v[k] = opt(b[k])));
    return v;
  };
  const writeLines = (id, lines) => {
    db.lines = db.lines.filter((l) => l.requisition_id !== id);
    lines.forEach((l) => db.lines.push({ id: nextId++, requisition_id: id, item_id: item(l.item_id).id,
      qty_requested: Number(l.qty), qty_approved: null, qty_issued: null }));
  };
  const person = (id) => {
    const p = db.people.find((x) => x.id === Number(id));
    if (!p || (me.role !== "admin" && (p.kind === "central" || p.department_id !== me.department_id))) throw new ApiError(404, "ไม่พบรายชื่อนี้");
    return p;
  };
  const personValues = (b) => {
    const kind = b.kind;
    if (!["requester", "receiver", "central"].includes(kind)) throw new ApiError(400, "ประเภททะเบียนไม่ถูกต้อง");
    if (kind === "central") admin();
    const department_id = kind === "central" ? null : me.role === "admin" ? Number(b.department_id) : me.department_id;
    if (kind !== "central" && !dept(department_id)) throw new ApiError(400, "กรุณาเลือกหน่วยงาน");
    const position = opt(b.position);
    const scope = kind === "central" ? "central" : "dept";
    if (position && !db.positions.some((p) => p.scope === scope && p.name === position)) db.positions.push({ id: nextId++, name: position, scope });
    return { kind, full_name: need(b.full_name, "ชื่อ-นามสกุล"), position, department_id };
  };
  const deptValues = (b) => ({ code: need(b.code, "รหัสหน่วย").toUpperCase(), name: need(b.name, "ชื่อหน่วยเบิก"),
    group_name: opt(b.group_name), active: b.active === false || b.active === "0" ? 0 : 1 });

  const routes = [
    ["GET", /^\/setup$/, () => ({ needs_setup: false })],
    ["POST", /^\/login$/, (b) => {
      const id = String(b.username || "").replace(/\D/g, "");
      const u = db.users.find((x) => x.username === id);
      if (!u || String(b.password || "") !== id.slice(-5))
        throw new ApiError(401, "เลขบัตรประชาชนหรือรหัสผ่านไม่ถูกต้อง (โหมดตัวอย่าง: 1103700012345 ผู้ดูแลคลัง, 3100600054321 OPD, 1209900067890 ER — รหัสผ่านคือ 5 ตัวท้าย)");
      if (!u.active) throw new ApiError(403, "บัญชีนี้ถูกปิดใช้งาน ติดต่อเจ้าหน้าที่คลังกลาง");
      me = u;
      return pub(u);
    }],
    ["POST", /^\/logout$/, () => { me = null; return { ok: true }; }],
    ["GET", /^\/me$/, () => pub(me)],
    // โหมดตัวอย่างไม่บังคับตั้งรหัสใหม่ และไม่เก็บรหัสผ่าน
    ["POST", /^\/me\/password$/, () => pub(me)],
    ["GET", /^\/warehouses$/, () => db.warehouses],
    ["GET", /^\/departments$/, () => db.departments.filter((d) => me.role === "admin" || d.active).map((d) => ({ ...d,
      requester_count: peopleOf("requester", d.id).length, receiver_count: peopleOf("receiver", d.id).length }))],
    ["POST", /^\/departments$/, (b) => { admin(); const d = { id: nextId++, ...deptValues(b) }; db.departments.push(d); return d; }],
    ["PUT", /^\/departments\/(\d+)$/, (b, id) => { admin(); return Object.assign(dept(id), deptValues(b)); }],
    ["GET", /^\/users$/, () => { admin(); return db.users.map(pub); }],
    ["POST", /^\/users$/, (b) => {
      admin();
      const username = nationalId(b.username);
      if (db.users.some((u) => u.username === username)) throw new ApiError(409, "มีบัญชีของเลขบัตรนี้แล้ว");
      const u = { id: nextId++, username, full_name: need(b.full_name, "ชื่อ-นามสกุล"), role: b.role,
        department_id: b.department_id ? Number(b.department_id) : null, active: 1 };
      db.users.push(u);
      return pub(u);
    }],
    ["PUT", /^\/users\/(\d+)$/, (b, id) => { admin(); return pub(Object.assign(db.users.find((u) => u.id === id), {
      full_name: need(b.full_name, "ชื่อ-นามสกุล"), role: b.role, department_id: b.department_id ? Number(b.department_id) : null,
      active: b.active === false ? 0 : 1,
    })); }],
    // ทะเบียนผู้เกี่ยวข้อง หน่วยงานเห็นเฉพาะของตัวเอง + เจ้าหน้าที่คลังกลาง
    ["GET", /^\/people$/, (b, q) => db.people.filter((p) => (!q.get("kind") || p.kind === q.get("kind"))
      && (!q.get("department_id") || p.kind === "central" || p.department_id === Number(q.get("department_id")))
      && (me.role === "admin" || p.kind === "central" || p.department_id === me.department_id))
      .map((p) => ({ ...p, department_name: dept(p.department_id)?.name ?? null }))],
    ["POST", /^\/people$/, (b) => { const p = { id: nextId++, ...personValues(b) }; db.people.push(p); return p; }],
    ["PUT", /^\/people\/(\d+)$/, (b, id) => { const p = person(id); return Object.assign(p, personValues({ ...b, kind: p.kind })); }],
    ["DELETE", /^\/people\/(\d+)$/, (b, id) => { const p = person(id); if (p.kind === "central") admin(); db.people = db.people.filter((x) => x !== p); return { ok: true }; }],
    ["GET", /^\/positions$/, (b, q) => db.positions.filter((p) => !q.get("scope") || p.scope === q.get("scope"))],
    ["POST", /^\/positions$/, (b) => {
      const scope = b.scope === "central" ? "central" : "dept";
      if (scope === "central") admin();
      const name = need(b.name, "ชื่อตำแหน่ง");
      let p = db.positions.find((x) => x.scope === scope && x.name === name);
      if (!p) db.positions.push((p = { id: nextId++, name, scope }));
      return p;
    }],
    ["GET", /^\/items$/, (b, q) => db.items.filter((i) => (me.role === "admin" && q.get("all") === "1") || i.active).map(itemView)],
    ["POST", /^\/items$/, (b) => {
      admin();
      const i = { id: nextId++, qty: 0, ...itemValues(b) };
      db.items.push(i);
      if (Number(b.initial_qty) > 0) log(i.id, Number(b.initial_qty), "ยอดยกมา");
      return itemView(i);
    }],
    ["PUT", /^\/items\/(\d+)$/, (b, id) => { admin(); return itemView(Object.assign(item(id), itemValues(b))); }],
    ["POST", /^\/items\/(\d+)\/adjust$/, (b, id) => {
      admin();
      const i = item(id);
      const delta = Number(b.delta);
      if (!delta) throw new ApiError(400, "จำนวนต้องไม่เป็นศูนย์");
      if (i.qty + delta < 0) throw new ApiError(409, `สต็อกไม่พอ (คงเหลือ ${i.qty} ${i.unit})`);
      log(i.id, delta, b.reason || (delta > 0 ? "รับเข้า" : "ปรับลด"));
      return itemView(i);
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
    // ตารางรวมสำหรับหน้าอนุมัติ: ใบที่รออนุมัติและอนุมัติแล้วรอจ่าย พร้อมรายการ
    ["GET", /^\/requisitions\/board$/, () => {
      admin();
      return db.requisitions.filter((r) => ["pending", "approved"].includes(r.status)).map((r) => getReq(r.id));
    }],
    ["POST", /^\/requisitions$/, (b) => {
      const department_id = me.role === "admin" ? Number(b.department_id) : me.department_id;
      if (!dept(department_id)) throw new ApiError(400, "กรุณาเลือกหน่วยงาน");
      const r = { id: nextId++, doc_no: docNo(), department_id, created_by: me.id, status: "pending", created_at: now(),
        approved_at: null, issued_at: null, ...reqValues(b) };
      db.requisitions.push(r);
      writeLines(r.id, b.lines);
      return getReq(r.id);
    }],
    // หน่วยงานแก้ไขใบเบิกได้จนกว่าคลังกลางจะอนุมัติ
    ["PUT", /^\/requisitions\/(\d+)$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "pending");
      Object.assign(db.requisitions.find((r) => r.id === id), reqValues(b), { updated_at: now() });
      writeLines(id, b.lines);
      return getReq(id);
    }],
    ["GET", /^\/requisitions\/(\d+)$/, (b, id) => getReq(id)],
    ["POST", /^\/requisitions\/(\d+)\/cancel$/, (b, id) => {
      const doc = getReq(id);
      status(doc, "pending");
      db.requisitions.find((r) => r.id === id).status = "cancelled";
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/approve$/, (b, id) => {
      admin();
      const doc = getReq(id);
      status(doc, "pending");
      const approver = need(b.approver_name, "ชื่อผู้อนุมัติ");
      const qty = lineQty(doc, b.lines, "qty_approved", "qty_requested");
      db.lines.filter((l) => l.requisition_id === id).forEach((l) => (l.qty_approved = qty[l.id]));
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "approved", approver_name: approver,
        approver_position: opt(b.approver_position), approved_at: now() });
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/unapprove$/, (b, id) => {
      admin();
      const doc = getReq(id);
      status(doc, "approved");
      db.lines.filter((l) => l.requisition_id === id).forEach((l) => (l.qty_approved = null));
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "pending", approved_at: null });
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/reject$/, (b, id) => {
      admin();
      const doc = getReq(id);
      status(doc, "pending", "approved");
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "rejected", approver_name: need(b.approver_name, "ชื่อผู้อนุมัติ"),
        approver_position: opt(b.approver_position), reject_reason: need(b.reason, "เหตุผล"), approved_at: now() });
      return getReq(id);
    }],
    ["POST", /^\/requisitions\/(\d+)\/issue$/, (b, id) => {
      admin();
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
      Object.assign(db.requisitions.find((r) => r.id === id), { status: "issued", issuer_name: issuer, issuer_position: opt(b.issuer_position),
        receiver_name: receiver, receiver_position: opt(b.receiver_position), issued_at: now() });
      return getReq(id);
    }],
    ["GET", /^\/summary$/, () => {
      admin();
      const counts = {};
      db.requisitions.forEach((r) => (counts[r.status] = (counts[r.status] || 0) + 1));
      return {
        status_counts: counts,
        low_stock: db.items.filter((i) => i.active && i.min_qty > 0 && i.qty <= i.min_qty).map(itemView),
        waiting: db.requisitions.filter((r) => ["pending", "approved"].includes(r.status)).map(reqView),
      };
    }],
    // ข้อมูลวิเคราะห์การเบิก 12 สัปดาห์ล่าสุด (ทั้งโรงพยาบาล)
    ["GET", /^\/analytics$/, () => {
      const WEEKS = 12;
      const end = new Date();
      const start = new Date(end.getTime() - WEEKS * 7 * 864e5);
      const docs = db.requisitions.filter((r) => r.created_at >= stamp(start) && !["cancelled", "rejected"].includes(r.status));
      const weeks = Array.from({ length: WEEKS }, (_, i) => ({ start: stamp(new Date(start.getTime() + i * 7 * 864e5)), emergency: 0, routine: 0 }));
      docs.forEach((r) => {
        const w = Math.min(WEEKS - 1, Math.floor((new Date(r.created_at) - start) / (7 * 864e5)));
        weeks[w][r.req_type] += 1;
      });
      const issuedLines = db.lines.filter((l) => l.qty_issued && docs.some((r) => r.id === l.requisition_id));
      const byWh = db.warehouses.map((w) => ({ warehouse_id: w.id, name: w.name, hue: w.hue,
        lines: issuedLines.filter((l) => item(l.item_id).warehouse_id === w.id).length })).sort((a, b) => b.lines - a.lines);
      const byDept = db.departments.map((d) => {
        const mine = docs.filter((r) => r.department_id === d.id);
        return { name: d.name, total: mine.length, emergency: mine.filter((r) => r.req_type === "emergency").length };
      }).filter((d) => d.total).sort((a, b) => b.total - a.total).slice(0, 6);
      const qty = {};
      issuedLines.forEach((l) => (qty[l.item_id] = (qty[l.item_id] || 0) + l.qty_issued));
      const top = Object.entries(qty).sort((a, b) => b[1] - a[1]).slice(0, 5)
        .map(([id, n]) => { const i = item(id); return { name: i.name, unit: i.unit, warehouse_name: wh(i.warehouse_id).name, qty: n }; });
      const hours = (r) => (new Date(r.issued_at) - new Date(r.created_at)) / 36e5;
      const avg = (list) => (list.length ? list.reduce((a, r) => a + hours(r), 0) / list.length : null);
      const issued = docs.filter((r) => r.issued_at);
      return {
        from: stamp(start), to: stamp(end), weeks, by_warehouse: byWh, by_department: byDept, top_items: top,
        totals: {
          requisitions: docs.length,
          emergency: docs.filter((r) => r.req_type === "emergency").length,
          lines_issued: issuedLines.length,
          avg_hours: avg(issued),
          avg_hours_emergency: avg(issued.filter((r) => r.req_type === "emergency")),
        },
      };
    }],
  ];
  function log(item_id, delta, reason, requisition_id = null, ts = now()) {
    const i = db.items.find((x) => x.id === item_id);
    i.qty += delta;
    db.movements.unshift({ id: nextId++, ts, item_id, delta, balance: i.qty, reason, requisition_id, user_id: me?.id ?? 1 });
  }

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
      const open = ["/setup", "/login", "/logout"].includes(path);
      if (!open && !me) throw new ApiError(401, "กรุณาเข้าสู่ระบบ");
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
