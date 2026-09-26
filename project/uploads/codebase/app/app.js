"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const view = $("#view");
const dlg = $("#dlg");

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v) => (v == null || v === "" ? "-" : Number(v).toLocaleString("th-TH", { maximumFractionDigits: 2 }));

// วันที่แบบไทย: 26/09/2569 21:19
function when(ts, withTime = true) {
  if (!ts) return "-";
  const [d, t = ""] = ts.split("T");
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${Number(y) + 543}${withTime && t ? " " + t.slice(0, 5) : ""}`;
}
const nowTs = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19); };

// เลขบัตรประชาชน: 1-1037-00012-34-5
const fmtId = (d) => [d.slice(0, 1), d.slice(1, 5), d.slice(5, 10), d.slice(10, 12), d.slice(12, 13)].filter(Boolean).join("-");
const maskId = (d) => fmtId(String(d).slice(0, 5) + "•".repeat(Math.max(0, String(d).length - 5)));

let me = null;
let unauthorized = () => {};

async function api(method, path, body) {
  const res = await fetch("/api" + path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/login") unauthorized();
  if (!res.ok) throw new Error(data.error || `เกิดข้อผิดพลาด (${res.status})`);
  return data;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = isError ? "error" : "";
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 6000 : 3000);
}

// ---------- ส่วนประกอบหน้าจอ ----------

function table(headers, rowsHtml, emptyText) {
  if (!rowsHtml.length) return `<p class="empty">${esc(emptyText)}</p>`;
  const th = headers.map((h) => (Array.isArray(h) ? `<th class="${h[1]}">${esc(h[0])}</th>` : `<th>${esc(h)}</th>`));
  const td = (c) => (Array.isArray(c) ? `<td class="${c[1]}">${c[0]}</td>` : `<td>${c}</td>`);
  return `<div class="table-wrap"><table><thead><tr>${th.join("")}</tr></thead><tbody>${rowsHtml
    .map((cells) => `<tr>${cells.map(td).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const btn = (act, text, id = "", cls = "") =>
  `<button type="button" class="btn small ${cls}" data-act="${act}" data-id="${esc(id)}">${esc(text)}</button>`;
const actions = (...buttons) => [buttons.join(""), "actions"];
const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;
const option = (value, text, selected) =>
  `<option value="${esc(value)}" ${String(value) === String(selected ?? "") ? "selected" : ""}>${esc(text)}</option>`;

function bind(handlers) {
  view.onclick = (e) => {
    const b = e.target.closest("[data-act]");
    if (b && !b.disabled && handlers[b.dataset.act]) handlers[b.dataset.act](b.dataset.id, b);
  };
}

// ช่องจำนวนที่ถูกแก้แล้วกดปุ่มอื่นทันที: change เกิดตอน mousedown ถ้าวาดหน้าใหม่ตอนนั้นปุ่มจะหายและการคลิกไม่ทำงาน
// จึงรอให้คลิกเสร็จก่อนค่อยวาดใหม่
let pointerDown = false;
let deferred = null;
document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
document.addEventListener("pointerup", () => setTimeout(() => {
  pointerDown = false;
  const fn = deferred;
  deferred = null;
  if (fn) fn();
}), true);
function afterPointer(el, draw) {
  if (!pointerDown) return draw();
  deferred = () => { if (document.contains(el)) draw(); };
}

// วาดส่วนของหน้าใหม่โดยให้ปุ่มหรือช่องที่โฟกัสอยู่ยังโฟกัสอยู่ (สำหรับผู้ใช้คีย์บอร์ด)
// ระหว่างวาด ช่องที่โฟกัสอยู่ถูกลบแล้วเกิด change ซ้ำ ให้ตัวจัดการ change ข้ามไป (ดู rendering)
let rendering = false;
function keepFocus(draw) {
  const a = document.activeElement;
  let sel = null;
  if (a && view.contains(a)) {
    if (a.dataset.line) sel = `[data-line="${a.dataset.line}"]`;
    else if (a.dataset.act) sel = `[data-act="${a.dataset.act}"][data-id="${a.dataset.id ?? ""}"]`;
    else if (a.dataset.id && a.classList[0]) sel = `.${a.classList[0]}[data-id="${a.dataset.id}"]`;
    else if (a.id) sel = `#${a.id}`;
  }
  rendering = true;
  try { draw(); } finally { rendering = false; }
  if (sel) $(sel, view)?.focus();
}

function fieldHtml(f, values = {}) {
  const v = values[f.name] ?? f.value ?? "";
  const attrs = [
    `name="${f.name}"`,
    f.required ? "required" : "",
    f.disabled ? "disabled" : "",
    f.min != null ? `min="${f.min}"` : "",
    f.type === "number" ? `step="${f.step || "any"}"` : "",
    f.placeholder ? `placeholder="${esc(f.placeholder)}"` : "",
    f.list ? `list="${f.list}"` : "",
    f.autocomplete ? `autocomplete="${f.autocomplete}"` : "",
    f.inputmode ? `inputmode="${f.inputmode}"` : "",
    f.pattern ? `pattern="${f.pattern}"` : "",
    f.maxlength ? `maxlength="${f.maxlength}"` : "",
  ].join(" ");
  const input = f.type === "select"
    ? `<select ${attrs}>${f.options.map(([val, text]) => option(val, text, v)).join("")}</select>`
    : `<input type="${f.type || "text"}" value="${esc(v)}" ${attrs}>`;
  return `<label class="field"><span>${esc(f.label)}${f.required ? " *" : ""}</span>${input}${
    f.hint ? `<small>${esc(f.hint)}</small>` : ""}</label>`;
}

function dialogShell(title, inner, submitLabel = "บันทึก", cancelLabel = "ยกเลิก") {
  return `<form class="form">
    <h2>${title}</h2>
    ${inner}
    <p class="form-error" hidden></p>
    <div class="actions">
      <button type="button" class="btn" data-cancel>${esc(cancelLabel)}</button>
      ${submitLabel ? `<button type="submit" class="btn primary">${esc(submitLabel)}</button>` : ""}
    </div>
  </form>`;
}

function wireDialog(onSubmit) {
  const form = $("form", dlg);
  const error = $(".form-error", form);
  $("[data-cancel]", form).onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const submit = $("button[type=submit]", form);
    if (submit) submit.disabled = true;
    error.hidden = true;
    try {
      await onSubmit(Object.fromEntries(new FormData(form)), form);
      dlg.close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      if (submit) submit.disabled = false;
    }
  };
  if (!dlg.open) dlg.showModal();
  return form;
}

function openForm({ title, fields, values = {}, submitLabel, intro = "", extra = "", onSubmit, wide = false }) {
  dlg.className = wide ? "wide" : "";
  dlg.innerHTML = dialogShell(esc(title), `${intro}<div class="fields">${fields.map((f) => fieldHtml(f, values)).join("")}</div>${extra}`, submitLabel);
  const form = wireDialog(onSubmit);
  $("input:not([type=hidden]), select", form)?.focus();
  return form;
}

const pageHead = (title, { over = "", sub = "", right = "" } = {}) => `<div class="page-head">
    <div class="titles">${over ? `<small class="over">${over}</small>` : ""}<h1>${title}</h1>${sub ? `<span class="sub">${sub}</span>` : ""}</div>
    ${right}
  </div>`;

// ---------- ข้อมูลอ้างอิง: คลังและประเภทการเบิก ----------

let warehouses = [];
const whOf = (id) => warehouses.find((w) => w.id === Number(id));
const whIco = (w, size = "") => (w ? `<span class="wh-ico ${size}" style="--h:${Number(w.hue) || 0}" aria-hidden="true">${esc(w.initials)}</span>` : "");

const REQ_TYPE = {
  emergency: ["ฉุกเฉิน", "bad", "เบิกฉุกเฉิน"],
  routine: ["ตามรอบ", "brand", "เบิกตามรอบปกติ (รายสัปดาห์)"],
};
const typeBadge = (t) => (REQ_TYPE[t] ? badge(REQ_TYPE[t][0], REQ_TYPE[t][1]) : "");

// ผู้เกี่ยวข้องในใบเบิก: ชื่อฟิลด์ใน API คือ `${key}_name` และ `${key}_position`
const ROLES = [
  { key: "requester", label: "ผู้เบิก", hint: "ผู้ส่งใบเบิก", kind: "requester", required: true },
  { key: "approver", label: "ผู้อนุมัติ", hint: "เว้นว่างได้ คลังกลางเลือกตอนอนุมัติ", kind: "central" },
  { key: "issuer", label: "ผู้จ่าย", hint: "เว้นว่างได้ คลังกลางเลือกตอนจ่าย", kind: "central" },
  { key: "receiver", label: "ผู้รับ", hint: "ผู้มารับของที่คลัง", kind: "receiver" },
];
const REG_NAME = { requester: "ทะเบียนผู้เบิกสินค้า", receiver: "ทะเบียนผู้รับสินค้า", central: "ทะเบียนเจ้าหน้าที่คลังกลาง" };
const scopeOf = (kind) => (kind === "central" ? "central" : "dept");

// ---------- ใบเบิก: สถานะ รายละเอียด และการพิมพ์ ----------

const STATUS = {
  pending: ["รออนุมัติ", "warn"],
  approved: ["อนุมัติแล้ว รอจ่าย", "info"],
  issued: ["จ่ายแล้ว", "ok"],
  rejected: ["ไม่อนุมัติ", "bad"],
  cancelled: ["ยกเลิก", "muted"],
};
const statusBadge = (s) => badge(...STATUS[s]);
const reqSummary = (r) => `${num(r.line_count)} รายการ${r.warehouses?.length ? ` · ${r.warehouses.join(", ")}` : ""}`;

function infoGrid(doc) {
  const cell = (label, value) => `<div><small>${label}</small><div>${value}</div></div>`;
  const person = (name, pos, ts) => (name
    ? `${esc(name)}${pos ? `<span class="pos">${esc(pos)}</span>` : ""}${ts ? ` <small>${when(ts)}</small>` : ""}` : "-");
  return `<div class="info-grid">
    ${cell("หน่วยงาน", esc(doc.department_name))}
    ${cell("วันที่ขอเบิก", when(doc.created_at))}
    ${cell("ประเภทการเบิก", typeBadge(doc.req_type) || "-")}
    ${cell("ผู้เบิก", person(doc.requester_name, doc.requester_position))}
    ${cell(doc.status === "rejected" ? "ผู้พิจารณา" : "ผู้อนุมัติ", person(doc.approver_name, doc.approver_position, doc.approved_at))}
    ${cell("ผู้จ่าย", person(doc.issuer_name, doc.issuer_position, doc.issued_at))}
    ${cell("ผู้รับ", person(doc.receiver_name, doc.receiver_position))}
  </div>
  ${doc.note ? `<p class="hint"><b>หมายเหตุ:</b> ${esc(doc.note)}</p>` : ""}
  ${doc.reject_reason ? `<p class="form-error"><b>เหตุผลที่ไม่อนุมัติ:</b> ${esc(doc.reject_reason)}</p>` : ""}`;
}

// mode: view | approve | issue
function linesTable(doc, mode) {
  const admin = me.role === "admin";
  const input = (line, field, value, max) =>
    `<input class="qty-input" type="number" step="any" min="0" max="${max}" data-line="${line.id}" data-field="${field}" value="${value}" required aria-label="${esc(line.name)}">`;
  const headers = ["#", "คลัง", "รหัส", "รายการ", "หน่วย", ["ขอเบิก", "num"], ["อนุมัติ", "num"], ["จ่ายจริง", "num"]];
  if (admin && doc.status !== "issued") headers.push(["คงเหลือในคลัง", "num"]);
  return table(headers, doc.lines.map((l, i) => {
    const approved = mode === "approve" ? input(l, "qty_approved", l.qty_requested, l.qty_requested) : num(l.qty_approved);
    const issued = mode === "issue" ? input(l, "qty_issued", Math.min(l.qty_approved, l.stock), l.qty_approved) : num(l.qty_issued);
    const cells = [i + 1, esc(l.warehouse_name || "-"), esc(l.code), esc(l.name), esc(l.unit), [num(l.qty_requested), "num"], [approved, "num"], [issued, "num"]];
    if (admin && doc.status !== "issued") {
      const need = mode === "issue" || doc.status === "approved" ? l.qty_approved : l.qty_requested;
      cells.push([`<span class="${l.stock < need ? "minus" : ""}">${num(l.stock)}</span>`, "num"]);
    }
    return cells;
  }), "ไม่มีรายการ");
}

// ช่องเลือกชื่อจากทะเบียน ค่าที่ส่งคือชื่อ-นามสกุล ตำแหน่งดึงจากทะเบียน
function personSelect(name, label, list, selected, hint = "") {
  const opts = [["", "— เลือกชื่อ —"], ...list.map((p) => [p.full_name, p.position ? `${p.full_name} · ${p.position}` : p.full_name])];
  if (selected && !list.some((p) => p.full_name === selected)) opts.push([selected, selected]);
  return fieldHtml({ name, label, type: "select", required: true, options: opts, value: selected, hint });
}
const positionOf = (list, name, fallback = null) => list.find((p) => p.full_name === name)?.position ?? fallback;
const centralDefault = (central, current) => current || central.find((p) => p.full_name === me.full_name)?.full_name || "";

async function openRequisition(id, mode = "view") {
  let doc;
  try { doc = await api("GET", `/requisitions/${id}`); } catch (e) { return toast(e.message, true); }
  const admin = me.role === "admin";
  const title = `ใบเบิก ${esc(doc.doc_no)} ${statusBadge(doc.status)}`;
  let body = infoGrid(doc) + linesTable(doc, mode);
  let submit = null;
  let central = [], receivers = [];
  if (mode !== "view") {
    try {
      [central, receivers] = await Promise.all([api("GET", "/people?kind=central"),
        mode === "issue" ? api("GET", `/people?kind=receiver&department_id=${doc.department_id}`) : []]);
    } catch (e) { return toast(e.message, true); }
  }

  if (mode === "approve") {
    body += `<div class="fields step">${personSelect("approver_name", "ผู้อนุมัติ", central, centralDefault(central, doc.approver_name), "จากทะเบียนเจ้าหน้าที่คลังกลาง")}</div>`;
    submit = "ยืนยันอนุมัติ";
  } else if (mode === "issue") {
    body += `<div class="fields step two">
      ${personSelect("issuer_name", "ผู้จ่าย", central, centralDefault(central, doc.issuer_name), "จากทะเบียนเจ้าหน้าที่คลังกลาง")}
      ${personSelect("receiver_name", "ผู้รับของ", receivers, doc.receiver_name || "", "คนที่มารับของจากคลัง · จากทะเบียนผู้รับสินค้า")}
    </div>`;
    submit = "ยืนยันจ่ายของ (ตัดสต็อก)";
  } else {
    const buttons = [];
    if (admin && doc.status === "pending") buttons.push(btn("approve", "อนุมัติ", "", "primary"), btn("reject", "ไม่อนุมัติ", "", "danger"));
    if (admin && doc.status === "approved") buttons.push(btn("issue", "จ่ายของ", "", "primary"), btn("reject", "ไม่อนุมัติ", "", "danger"));
    if (!admin && doc.status === "pending") buttons.push(btn("edit", "แก้ไขใบเบิก", "", "outline"));
    if (doc.status === "pending") buttons.push(btn("cancel", "ยกเลิกใบเบิก", "", "danger"));
    buttons.push(btn("print", "พิมพ์ใบเบิก"));
    body += `<div class="doc-actions">${buttons.join("")}</div>`;
  }

  dlg.className = "wide";
  dlg.innerHTML = dialogShell(title, body, submit, mode === "view" ? "ปิด" : "ย้อนกลับ");
  const form = wireDialog(async (d, f) => {
    const lines = $$(".qty-input", f).map((i) => ({ line_id: i.dataset.line, [i.dataset.field]: i.value }));
    if (mode === "approve") {
      await api("POST", `/requisitions/${id}/approve`, { approver_name: d.approver_name,
        approver_position: positionOf(central, d.approver_name, doc.approver_position), lines });
      toast("อนุมัติแล้ว");
    } else {
      await api("POST", `/requisitions/${id}/issue`, {
        issuer_name: d.issuer_name, issuer_position: positionOf(central, d.issuer_name, doc.issuer_position),
        receiver_name: d.receiver_name, receiver_position: positionOf(receivers, d.receiver_name, doc.receiver_position), lines });
      toast("จ่ายของแล้ว ตัดสต็อกเรียบร้อย");
    }
    refresh();
  });
  if (mode !== "view") {
    // "ย้อนกลับ" กลับไปหน้ารายละเอียดแทนการปิด
    $("[data-cancel]", form).onclick = () => openRequisition(id);
    $(".qty-input", form)?.focus();
    return;
  }
  form.onclick = async (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "approve" || act === "issue") return openRequisition(id, act);
    if (act === "print") return printRequisition(doc);
    if (act === "edit") return startEdit(doc.id);
    if (act === "cancel") {
      if (!confirm(`ยกเลิกใบเบิก ${doc.doc_no}?`)) return;
      try { await api("POST", `/requisitions/${id}/cancel`, {}); toast("ยกเลิกใบเบิกแล้ว"); dlg.close(); refresh(); }
      catch (err) { toast(err.message, true); }
    }
    if (act === "reject") {
      let central2 = [];
      try { central2 = await api("GET", "/people?kind=central"); } catch (err) { return toast(err.message, true); }
      dlg.className = "";
      dlg.innerHTML = dialogShell(`ไม่อนุมัติใบเบิก ${esc(doc.doc_no)}`, `<div class="fields">
          ${personSelect("approver_name", "ผู้พิจารณา", central2, centralDefault(central2, doc.approver_name))}
          ${fieldHtml({ name: "reason", label: "เหตุผล", required: true, placeholder: "เช่น ของหมด ให้เบิกใหม่รอบหน้า" })}
        </div>`, "ยืนยันไม่อนุมัติ");
      wireDialog(async (d) => {
        await api("POST", `/requisitions/${id}/reject`, { ...d, approver_position: positionOf(central2, d.approver_name) });
        toast("บันทึกไม่อนุมัติแล้ว");
        refresh();
      });
    }
  };
}

function printRequisition(doc) {
  const sign = (role, name, pos, ts) => `<div class="sign">
      <div>ลงชื่อ ....................................... ${role}</div>
      <div>( ${esc(name || "......................................")} )</div>
      <div>ตำแหน่ง ${esc(pos || "......................................")}</div>
      <div>วันที่ ${ts ? when(ts, false) : "......../......../........"}</div>
    </div>`;
  const rejected = doc.status === "rejected";
  $("#print").innerHTML = `
    <h1>ใบเบิกเวชภัณฑ์และพัสดุ</h1>
    <p class="center">งานบริหารเวชภัณฑ์ (คลังกลาง) โรงพยาบาลตาพระยา</p>
    <div class="print-head">
      <div><b>เลขที่:</b> ${esc(doc.doc_no)}</div>
      <div><b>วันที่:</b> ${when(doc.created_at, false)}</div>
      <div><b>หน่วยงาน:</b> ${esc(doc.department_name)}</div>
      <div><b>ประเภท:</b> ${esc(REQ_TYPE[doc.req_type]?.[2] || "-")}</div>
      <div><b>สถานะ:</b> ${esc(STATUS[doc.status][0])}</div>
    </div>
    <table>
      <thead><tr><th>ลำดับ</th><th>คลัง</th><th>รหัส</th><th>รายการ</th><th>หน่วย</th><th class="num">ขอเบิก</th><th class="num">อนุมัติ</th><th class="num">จ่ายจริง</th></tr></thead>
      <tbody>${doc.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.warehouse_name || "")}</td><td>${esc(l.code)}</td><td>${esc(l.name)}</td><td>${esc(l.unit)}</td>
        <td class="num">${num(l.qty_requested)}</td><td class="num">${l.qty_approved == null ? "" : num(l.qty_approved)}</td>
        <td class="num">${l.qty_issued == null ? "" : num(l.qty_issued)}</td></tr>`).join("")}</tbody>
    </table>
    ${doc.note ? `<p><b>หมายเหตุถึงคลังกลาง:</b> ${esc(doc.note)}</p>` : ""}
    <div class="signs">
      ${sign("ผู้เบิก", doc.requester_name, doc.requester_position, doc.created_at)}
      ${sign("ผู้อนุมัติ", rejected ? "" : doc.approver_name, rejected ? "" : doc.approver_position, rejected ? null : doc.approved_at)}
      ${sign("ผู้จ่าย", doc.issuer_name, doc.issuer_position, doc.issued_at)}
      ${sign("ผู้รับ", doc.receiver_name, doc.receiver_position, doc.issued_at)}
    </div>`;
  window.print();
}

// ---------- เบิกสินค้า: เลือกคลัง → ใส่ตะกร้า → ใบเบิก → ส่งแล้ว ----------
// ตะกร้าเดียวใช้ร่วมกันทุกคลัง ตอนส่งรวมเป็นใบเบิก 1 ใบ

const cart = new Map(); // item_id -> qty
const blankForm = () => ({
  req_type: "", note: "", department_id: "", requesterInit: false,
  people: Object.fromEntries(ROLES.map((r) => [r.key, { name: "", position: "" }])),
});
const flow = { step: "wh", wh: null, editing: null, done: null, form: blankForm(), adding: null, error: "" };
let catalog = [];
let registry = { people: [], positions: [], departments: [] };

function resetFlow() {
  cart.clear();
  Object.assign(flow, { step: "wh", wh: null, editing: null, done: null, form: blankForm(), adding: null, error: "" });
}

function cartGroups() {
  let n = 0;
  const groups = warehouses.map((w) => ({
    w, lines: catalog.filter((i) => i.warehouse_id === w.id && cart.has(i.id)).map((item) => ({ item, qty: cart.get(item.id) })),
  })).filter((g) => g.lines.length);
  groups.forEach((g) => g.lines.forEach((l) => (l.n = ++n)));
  return { groups, count: n, whCount: groups.length };
}
const inCart = (w) => catalog.filter((i) => i.warehouse_id === w.id && cart.has(i.id)).length;

function setQty(id, value) {
  const qty = Number(value);
  if (!(qty > 0)) cart.delete(id);
  else cart.set(id, Math.round(qty * 100) / 100);
}

async function requestView() {
  catalog = await api("GET", "/items");
  const ids = new Set(catalog.map((i) => i.id));
  for (const id of [...cart.keys()]) if (!ids.has(id)) cart.delete(id);
  if (flow.step === "done") flow.step = "wh";
  bind(flowActions);
  view.onchange = flowChange;
  view.oninput = (e) => { if (e.target.id === "note") flow.form.note = e.target.value; };
  view.onkeydown = (e) => {
    if (e.key !== "Enter") return;
    if (e.target.id === "add-val") { e.preventDefault(); saveAdd(); }
    else if (e.target.matches(".pick-qty, .cart-qty")) { e.preventDefault(); e.target.dispatchEvent(new Event("change", { bubbles: true })); }
  };
  await drawFlow();
}

async function drawFlow() {
  if (flow.step === "co") return drawCheckout();
  if (flow.step === "done" && flow.done) return drawDone();
  if (flow.step === "shop" && whOf(flow.wh)) return drawShop();
  flow.step = "wh";
  drawWarehouses();
}

function goStep(step) {
  flow.step = step;
  window.scrollTo(0, 0);
  drawFlow().catch((e) => toast(e.message, true));
}

const editBanner = () => (flow.editing ? `<div class="edit-banner"><b>กำลังแก้ไขใบเบิก ${esc(flow.editing.doc_no)}</b>
  <span>แก้ไขได้จนกว่าคลังกลางจะอนุมัติ · สถานะยังเป็น "รออนุมัติ"</span>
  <button type="button" class="btn small" data-act="cancel-edit">ยกเลิกการแก้ไข</button></div>` : "");

function drawWarehouses() {
  const { count, whCount } = cartGroups();
  view.innerHTML = `${editBanner()}
    ${pageHead("เลือกคลังที่จะเบิก", {
      sub: "เลือกสินค้าได้จากหลายคลัง ระบบจะรวมทุกรายการในตะกร้าเป็นใบเบิกเดียว",
      right: count ? `<button type="button" class="btn primary lg" data-act="checkout">${flow.editing ? "กลับไปที่ใบเบิก" : "ทำใบเบิก"} (${count} รายการ จาก ${whCount} คลัง)</button>` : "",
    })}
    <div class="wh-grid">${warehouses.map((w) => {
      const c = inCart(w);
      return `<button type="button" class="wh-card" data-act="wh" data-id="${w.id}">
        <div class="wh-card-top">${whIco(w)}${c ? `<span class="in-cart">ในตะกร้า ${c} รายการ</span>` : ""}</div>
        <div class="wh-card-body"><b>${esc(w.name)}</b><span>${esc(w.description || "")}</span></div>
        <span class="wh-go">เลือกสินค้า →</span>
      </button>`;
    }).join("")}</div>`;
}

function drawShop() {
  const { count } = cartGroups();
  view.innerHTML = `${editBanner()}
    ${pageHead("เบิกสินค้า", {
      over: flow.editing ? `แก้ไขใบเบิก ${esc(flow.editing.doc_no)}` : `ใบเบิกใหม่ · ${when(nowTs(), false)}`,
      right: `<button type="button" class="btn outline" data-act="checkout" id="cart-btn">ตะกร้า <span class="pill-count">${count}</span></button>`,
    })}
    <div class="shop">
      <section class="panel">
        <div class="wh-tabs" id="wh-tabs" role="tablist" aria-label="คลัง"></div>
        <div id="prods"></div>
      </section>
      <aside class="panel cart" id="cart" aria-label="ตะกร้า"></aside>
    </div>`;
  drawShopParts();
}

function drawShopParts() {
  keepFocus(() => {
    const w = whOf(flow.wh);
    const { count } = cartGroups();
    $("#cart-btn .pill-count").textContent = count;
    $("#wh-tabs").innerHTML = warehouses.map((x) => {
      const c = inCart(x);
      return `<button type="button" role="tab" aria-selected="${x.id === w.id}" data-act="wh" data-id="${x.id}">${esc(x.name)}${c ? `<span class="pill-count">${c}</span>` : ""}</button>`;
    }).join("");
    const list = catalog.filter((i) => i.warehouse_id === w.id);
    $("#prods").innerHTML = `<div class="shop-head"><b>${esc(w.name)}</b><small>${esc(w.description || "")}</small></div>
      <div class="prod-row head"><span>รหัส</span><span>รายการ</span><span style="text-align:right">จำนวน · หน่วย</span></div>
      ${list.length ? list.map((i) => {
        const qty = cart.get(i.id) || 0;
        const control = qty
          ? `<div class="stepper">
              <button type="button" data-act="dec" data-id="${i.id}" aria-label="ลดจำนวน ${esc(i.name)}">−</button>
              <input class="pick-qty" data-id="${i.id}" value="${qty}" inputmode="decimal" aria-label="จำนวน ${esc(i.name)} (${esc(i.unit)})">
              <button type="button" data-act="inc" data-id="${i.id}" aria-label="เพิ่มจำนวน ${esc(i.name)}">+</button>
            </div>`
          : `<button type="button" class="btn outline" data-act="inc" data-id="${i.id}">+ ใส่ตะกร้า</button>`;
        return `<div class="prod-row ${qty ? "in" : ""}"><span class="code">${esc(i.code)}</span>
          <span class="name" title="${esc(i.name)}">${esc(i.name)}</span>
          <div class="prod-qty">${control}<span class="unit">${esc(i.unit)}</span></div></div>`;
      }).join("") : `<p class="empty">คลังนี้ยังไม่มีสินค้าที่เปิดให้เบิก</p>`}`;
    drawCart();
  });
}

function drawCart() {
  const { groups, count, whCount } = cartGroups();
  $("#cart").innerHTML = `<div class="cart-head"><h2>ตะกร้า</h2><small>${count} รายการ · ${whCount} คลัง</small></div>
    <div class="cart-body">${count ? groups.map((g) => `<div>
        <div class="cart-group-head">${whIco(g.w, "sm")}<b>${esc(g.w.name)}</b><small>${g.lines.length} รายการ</small></div>
        ${g.lines.map((l) => `<div class="cart-line"><span title="${esc(l.item.name)}">${esc(l.item.name)}</span>
          <span class="qty-u">${num(l.qty)} <small>${esc(l.item.unit)}</small></span>
          <button type="button" class="icon-x" data-act="remove" data-id="${l.item.id}" aria-label="ลบ ${esc(l.item.name)}">×</button></div>`).join("")}
      </div>`).join("") : `<div class="empty-box">ยังไม่มีสินค้าในตะกร้า<br>กด "+ ใส่ตะกร้า" ที่รายการสินค้า</div>`}</div>
    <div class="cart-foot">
      <button type="button" class="btn outline block" data-act="whs">+ เลือกสินค้าจากคลังอื่น</button>
      <button type="button" class="btn primary block" data-act="checkout" ${count ? "" : "disabled"}>${flow.editing ? "กลับไปที่ใบเบิก" : `ทำใบเบิก (${count} รายการ)`} →</button>
    </div>`;
}

// ----- ใบเบิก (ทำใบเบิก / แก้ไข) -----

const deptIdOfForm = () => (me.role === "admin" ? Number(flow.form.department_id) || null : me.department_id);
const regList = (kind) => registry.people.filter((p) => p.kind === kind);
const posList = (kind) => registry.positions.filter((p) => p.scope === scopeOf(kind)).map((p) => p.name);

async function loadRegistry() {
  const deptId = deptIdOfForm();
  const [people, positions, departments] = await Promise.all([
    api("GET", deptId ? `/people?department_id=${deptId}` : "/people?kind=central"),
    api("GET", "/positions"),
    me.role === "admin" ? api("GET", "/departments") : Promise.resolve([]),
  ]);
  registry = { people, positions, departments };
}

async function drawCheckout() {
  await loadRegistry();
  const f = flow.form;
  if (!f.requesterInit) {
    f.requesterInit = true;
    const mine = regList("requester").find((p) => p.full_name === me.full_name);
    if (mine && !f.people.requester.name) f.people.requester = { name: mine.full_name, position: mine.position || "" };
  }
  renderCheckout();
}

function submitLabel() {
  if (flow.editing) return "บันทึกการแก้ไข";
  return flow.form.req_type === "emergency" ? "ส่งใบเบิกฉุกเฉิน" : "ส่งใบเบิก";
}
function updateSubmit() {
  const b = $("#co-submit");
  if (!b) return;
  b.textContent = submitLabel();
  b.className = `btn lg ${flow.form.req_type === "emergency" ? "emerg" : "primary"}`;
}
function showError(message) {
  flow.error = message;
  const el = $("#co-err");
  if (!el) return;
  el.textContent = message;
  el.hidden = !message;
  if (message) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function renderCheckout() {
  const f = flow.form;
  const { groups, count, whCount } = cartGroups();
  const deptCell = me.role === "admin"
    ? `<select id="co-dept" aria-label="หน่วยงานที่เบิก">${option("", "— เลือกหน่วยงาน —", f.department_id)}${registry.departments
      .filter((d) => d.active).map((d) => option(d.id, d.name, f.department_id)).join("")}</select>`
    : esc(me.department_name || "-");
  const typeOpt = (k, label, sub) => `<label class="type-opt ${k}">
      <input type="radio" name="req_type" value="${k}" ${f.req_type === k ? "checked" : ""}>
      <span class="box" aria-hidden="true"></span><span class="txt"><b>${label}</b><small>${sub}</small></span></label>`;
  keepFocus(() => {
    view.innerHTML = `<div class="narrow">
      <div class="page-head">
        <div class="titles"><button type="button" class="link" data-act="shop">← กลับไปเลือกสินค้า</button>
          <h1>${flow.editing ? `แก้ไขใบเบิก ${esc(flow.editing.doc_no)}` : "ใบเบิก"}</h1></div>
        <dl class="meta"><dt>หน่วยงาน</dt><dd>${deptCell}</dd><dt>วันที่</dt><dd>${when(nowTs())}</dd>
          <dt>เลขที่</dt>${flow.editing ? `<dd>${esc(flow.editing.doc_no)}</dd>` : `<dd class="muted">ออกให้เมื่อส่งใบเบิก</dd>`}</dl>
      </div>
      ${editBanner()}
      <section class="panel co-lines">
        <div class="panel-title"><h2>1. รายการที่เบิก <small>· ${count} รายการ จาก ${whCount} คลัง</small></h2>
          <button type="button" class="link" data-act="whs">+ เพิ่มจากคลังอื่น</button></div>
        ${count ? `<div class="row head"><span>ลำดับ</span><span class="code">รหัส</span><span>รายการ</span><span style="text-align:right">จำนวน</span><span class="unit-cell">หน่วย</span><span></span></div>
          ${groups.map((g) => `<div class="wh-row wh-ink" style="--h:${Number(g.w.hue) || 0}">${esc(g.w.name)}</div>
            ${g.lines.map((l) => `<div class="row"><span class="n">${l.n}</span><span class="code">${esc(l.item.code)}</span>
              <span class="name">${esc(l.item.name)}<small class="muted">${esc(l.item.unit)}</small></span>
              <input class="cart-qty" data-id="${l.item.id}" value="${l.qty}" inputmode="decimal" aria-label="จำนวน ${esc(l.item.name)} (${esc(l.item.unit)})">
              <span class="unit-cell">${esc(l.item.unit)}</span>
              <button type="button" class="icon-x" data-act="remove" data-id="${l.item.id}" aria-label="ลบ ${esc(l.item.name)}">×</button></div>`).join("")}`).join("")}`
          : `<p class="empty">ยังไม่มีรายการ</p>`}
      </section>
      <section class="panel pad">
        <h2>2. ประเภทการเบิก <span class="req-star">*</span></h2><small>เลือก 1 อย่าง</small>
        <div class="types" id="types" role="radiogroup" aria-label="ประเภทการเบิก" aria-required="true">
          ${typeOpt("emergency", "เบิกฉุกเฉิน", "ต้องการใช้ด่วน")}${typeOpt("routine", "เบิกตามรอบปกติ", "รอบรายสัปดาห์")}
        </div>
      </section>
      <section class="panel pad"><h2>3. ผู้เกี่ยวข้อง</h2><div class="people" id="people"></div></section>
      <section class="panel pad">
        <h2>4. หมายเหตุถึงคลังกลาง</h2><small>เรื่องอื่น ๆ ที่อยากแจ้ง เช่น ต้องการด่วน ขอรับช่วงบ่าย หรือขอสินค้าทดแทนถ้าไม่มี</small>
        <textarea id="note" rows="4" placeholder="พิมพ์ข้อความถึงคลังกลาง (ไม่บังคับ)" aria-label="หมายเหตุถึงคลังกลาง">${esc(f.note)}</textarea>
      </section>
      <p class="form-error" id="co-err" role="alert" ${flow.error ? "" : "hidden"}>${esc(flow.error)}</p>
      <div class="co-actions">
        <button type="button" class="btn lg" data-act="shop">กลับไปแก้ไข</button>
        <button type="button" class="btn lg" id="co-submit" data-act="submit"></button>
      </div>
    </div>`;
    updateSubmit();
    drawPeople();
  });
}

function drawPeople() {
  const P = flow.form.people;
  const admin = me.role === "admin";
  const dept = admin ? registry.departments.find((d) => d.id === deptIdOfForm())?.name : me.department_name;
  $("#people").innerHTML = ROLES.map((r) => {
    const cur = P[r.key];
    const names = regList(r.kind).map((p) => p.full_name);
    if (cur.name && !names.includes(cur.name)) names.push(cur.name);
    const poss = posList(r.kind);
    if (cur.position && !poss.includes(cur.position)) poss.push(cur.position);
    // ทะเบียนเจ้าหน้าที่คลังกลางแก้ได้เฉพาะผู้ดูแลคลัง
    const canAdd = r.kind !== "central" || admin;
    const adding = flow.adding?.role === r.key ? flow.adding.field : null;
    const invalid = r.required && flow.error && !cur.name;
    const src = r.kind === "central" ? REG_NAME.central : `${REG_NAME[r.kind]}${dept ? ` (${dept})` : ""}`;
    const addRow = (ph) => `<div class="add-row"><input id="add-val" placeholder="${ph}" aria-label="${ph}">
      <button type="button" class="btn primary" data-act="add-save">เพิ่มลงทะเบียน</button>
      <button type="button" class="btn" data-act="add-cancel">ยกเลิก</button></div>`;
    return `<div class="person">
      <div class="person-head"><b>${r.label}</b>${r.required ? `<span class="req-star">*</span>` : ""}<small>${r.hint}</small>
        ${r.key === "receiver" ? `<button type="button" class="link" data-act="copy-req">ใช้ข้อมูลผู้เบิก</button>` : ""}</div>
      <label class="field"><span class="soft">ชื่อ-นามสกุล · จาก${esc(src)}</span>
        <select class="p-name ${invalid ? "invalid" : ""}" data-role="${r.key}" ${r.required ? 'aria-required="true"' : ""}>
          ${option("", "— เลือกชื่อ —", cur.name)}${names.map((n) => option(n, n, cur.name)).join("")}
          ${canAdd ? option("__add", "+ เพิ่มชื่อใหม่…") : ""}
        </select></label>
      ${adding === "name" ? addRow("ชื่อ นามสกุล") : ""}
      <label class="field"><span class="soft">ตำแหน่ง</span>
        <select class="p-pos" data-role="${r.key}">
          ${option("", "— เลือกตำแหน่ง —", cur.position)}${poss.map((n) => option(n, n, cur.position)).join("")}
          ${canAdd ? option("__add", "+ เพิ่มตำแหน่งใหม่…") : ""}
        </select></label>
      ${adding === "position" ? addRow("ชื่อตำแหน่ง") : ""}
    </div>`;
  }).join("");
  $("#add-val")?.focus();
}

async function saveAdd() {
  if (!flow.adding) return;
  const { role, field } = flow.adding;
  const input = $("#add-val");
  const value = input.value.trim();
  if (!value) return input.focus();
  const r = ROLES.find((x) => x.key === role);
  const cur = flow.form.people[role];
  try {
    if (field === "name") {
      const p = await api("POST", "/people", { kind: r.kind, full_name: value, position: cur.position || null, department_id: deptIdOfForm() });
      registry.people.push(p);
      flow.form.people[role] = { name: p.full_name, position: p.position || "" };
      toast(`เพิ่ม ${p.full_name} ลง${REG_NAME[r.kind]}แล้ว`);
    } else {
      const p = await api("POST", "/positions", { name: value, scope: scopeOf(r.kind) });
      if (!registry.positions.some((x) => x.id === p.id)) registry.positions.push(p);
      flow.form.people[role] = { ...cur, position: p.name };
    }
    flow.adding = null;
    drawPeople();
    $(`.p-${field === "name" ? "name" : "pos"}[data-role="${role}"]`)?.focus();
  } catch (e) {
    toast(e.message, true);
  }
}

async function flowChange(e) {
  const t = e.target;
  const P = flow.form.people;
  if (rendering) return;
  if (t.matches(".pick-qty")) {
    setQty(Number(t.dataset.id), t.value);
    afterPointer(t, drawShopParts);
  } else if (t.matches(".cart-qty")) {
    setQty(Number(t.dataset.id), t.value);
    afterPointer(t, renderCheckout);
  } else if (t.name === "req_type") {
    flow.form.req_type = t.value;
    $("#types").classList.remove("invalid");
    if (flow.error) showError("");
    updateSubmit();
  } else if (t.matches(".p-name, .p-pos")) {
    const role = t.dataset.role;
    const field = t.matches(".p-name") ? "name" : "position";
    if (t.value === "__add") {
      flow.adding = { role, field };
    } else {
      flow.adding = null;
      if (field === "name") {
        const found = regList(ROLES.find((r) => r.key === role).kind).find((p) => p.full_name === t.value);
        P[role] = { name: t.value, position: t.value ? found?.position || P[role].position : P[role].position };
        if (role === "requester" && t.value && flow.error) showError("");
      } else {
        P[role] = { ...P[role], position: t.value };
      }
    }
    drawPeople();
    if (!flow.adding) $(`.${t.classList[0]}[data-role="${role}"]`)?.focus();
  } else if (t.id === "co-dept") {
    flow.form.department_id = t.value;
    P.requester = { name: "", position: "" };
    P.receiver = { name: "", position: "" };
    try { await loadRegistry(); } catch (err) { return toast(err.message, true); }
    renderCheckout();
  }
}

async function submitFlow() {
  const f = flow.form;
  const { count } = cartGroups();
  const err = !count ? "ยังไม่มีสินค้าในใบเบิก"
    : me.role === "admin" && !f.department_id ? "กรุณาเลือกหน่วยงานที่เบิก"
    : !f.req_type ? "กรุณาเลือกประเภทการเบิก (ฉุกเฉิน หรือ ตามรอบปกติ)"
    : !f.people.requester.name ? "กรุณาเลือกชื่อผู้เบิก" : "";
  if (err) {
    showError(err);
    if (!f.req_type) $("#types").classList.add("invalid");
    drawPeople();
    return;
  }
  const body = { req_type: f.req_type, note: f.note.trim() || null, lines: [...cart].map(([item_id, qty]) => ({ item_id, qty })) };
  ROLES.forEach((r) => {
    body[`${r.key}_name`] = f.people[r.key].name || null;
    body[`${r.key}_position`] = f.people[r.key].position || null;
  });
  if (me.role === "admin") body.department_id = Number(f.department_id);
  const submit = $("#co-submit");
  submit.disabled = true;
  try {
    const edited = !!flow.editing;
    const doc = edited ? await api("PUT", `/requisitions/${flow.editing.id}`, body) : await api("POST", "/requisitions", body);
    resetFlow();
    flow.done = { id: doc.id, doc_no: doc.doc_no, count: doc.line_count, whCount: doc.warehouses?.length || 0, req_type: doc.req_type, edited };
    goStep("done");
  } catch (e) {
    showError(e.message);
    submit.disabled = false;
  }
}

function drawDone() {
  const d = flow.done;
  view.innerHTML = `<div class="panel done">
    <div class="done-mark" aria-hidden="true">✓</div>
    <div><h1>${d.edited ? "บันทึกการแก้ไขใบเบิกแล้ว" : "ส่งใบเบิกแล้ว"}</h1>
      <span class="muted">เลขที่ <b style="color:var(--text)">${esc(d.doc_no)}</b> · ${num(d.count)} รายการ จาก ${num(d.whCount)} คลัง</span></div>
    <div class="chips">${statusBadge("pending")}${typeBadge(d.req_type)}</div>
    <div class="done-edit"><span>ต้องการเปลี่ยนรายการ จำนวน หรือผู้เกี่ยวข้อง? แก้ไขได้จนกว่าคลังกลางจะอนุมัติ</span>
      <button type="button" class="btn outline" data-act="edit">แก้ไขใบเบิก</button></div>
    <div class="row">
      <button type="button" class="btn" data-act="print">พิมพ์ใบเบิก</button>
      <button type="button" class="btn" data-act="list">${me.role === "admin" ? "ดูใบเบิกทั้งหมด" : "ดูใบเบิกของหน่วยงาน"}</button>
      <button type="button" class="btn primary" data-act="new">เบิกรายการใหม่</button>
    </div>
  </div>`;
}

async function startEdit(id) {
  try {
    const doc = await api("GET", `/requisitions/${id}`);
    if (doc.status !== "pending") return toast("แก้ไขได้เฉพาะใบเบิกที่ยังรออนุมัติ", true);
    if (cart.size && flow.editing?.id !== doc.id
      && !confirm("รายการในตะกร้าตอนนี้จะถูกแทนที่ด้วยรายการในใบเบิกนี้ ต้องการแก้ไขใบเบิกต่อหรือไม่?")) return;
    cart.clear();
    doc.lines.forEach((l) => cart.set(l.item_id, l.qty_requested));
    const f = blankForm();
    Object.assign(f, { req_type: doc.req_type || "", note: doc.note || "", department_id: String(doc.department_id), requesterInit: true });
    ROLES.forEach((r) => (f.people[r.key] = { name: doc[`${r.key}_name`] || "", position: doc[`${r.key}_position`] || "" }));
    Object.assign(flow, { form: f, editing: { id: doc.id, doc_no: doc.doc_no }, step: "co", done: null, adding: null, error: "" });
    show("request");
  } catch (e) {
    toast(e.message, true);
  }
}

const flowActions = {
  wh: (id) => { flow.wh = Number(id); goStep("shop"); },
  whs: () => goStep("wh"),
  shop: () => goStep(flow.wh ? "shop" : "wh"),
  checkout: () => goStep("co"),
  inc: (id) => { setQty(Number(id), (cart.get(Number(id)) || 0) + 1); drawShopParts(); },
  dec: (id) => { setQty(Number(id), (cart.get(Number(id)) || 0) - 1); drawShopParts(); },
  remove: (id) => { cart.delete(Number(id)); if (flow.step === "co") renderCheckout(); else drawShopParts(); },
  "copy-req": () => { flow.form.people.receiver = { ...flow.form.people.requester }; drawPeople(); },
  "add-save": () => saveAdd(),
  "add-cancel": () => { flow.adding = null; drawPeople(); },
  submit: () => submitFlow(),
  "cancel-edit": () => { resetFlow(); show("requisitions"); },
  edit: () => startEdit(flow.done.id),
  print: async () => { try { printRequisition(await api("GET", `/requisitions/${flow.done.id}`)); } catch (e) { toast(e.message, true); } },
  list: () => { resetFlow(); show("requisitions"); },
  new: () => { resetFlow(); goStep("wh"); },
};

// ---------- รายการใบเบิก ----------

async function requisitionsView() {
  const admin = me.role === "admin";
  let saved = null;
  try { saved = sessionStorage.getItem("req-status"); } catch {}
  saved ??= admin ? "approved" : "";
  view.innerHTML = `${pageHead(admin ? "ใบเบิก / จ่ายสินค้า" : "ใบเบิกของหน่วยงาน", {
      sub: admin ? "จ่ายของตามใบเบิกที่อนุมัติแล้ว ดูรายละเอียด และพิมพ์ใบเบิก"
        : `${esc(me.department_name || "")} · แก้ไขหรือยกเลิกได้เฉพาะใบที่ยัง "รออนุมัติ"`,
      right: `<select id="status" aria-label="กรองตามสถานะ" style="width:auto">${option("", "ทุกสถานะ", saved)}${
        Object.entries(STATUS).map(([k, [t]]) => option(k, t, saved)).join("")}</select>
        <button type="button" class="btn primary" data-act="new">+ เบิกสินค้า</button>`,
    })}<div class="list" id="list"></div>`;
  const lockNote = { approved: "แก้ไขไม่ได้ · คลังกลางอนุมัติแล้ว", issued: "แก้ไขไม่ได้ · จ่ายแล้ว", rejected: "ไม่อนุมัติ", cancelled: "" };
  const load = async () => {
    const status = $("#status").value;
    try { sessionStorage.setItem("req-status", status); } catch {}
    const list = await api("GET", `/requisitions${status ? "?status=" + status : ""}`);
    const rows = list.map((r) => {
      const act = admin
        ? actions(btn("open", r.status === "pending" ? "พิจารณา" : r.status === "approved" ? "จ่ายของ" : "ดู", r.id,
          ["pending", "approved"].includes(r.status) ? "primary" : ""))
        : r.status === "pending"
          ? actions(btn("edit", "แก้ไขใบเบิก", r.id, "outline"), btn("cancel", "ยกเลิกใบเบิก", r.id, "danger"), btn("open", "ดู", r.id))
          : actions(lockNote[r.status] ? `<small>${lockNote[r.status]}</small>` : "", btn("open", "ดู", r.id));
      return [`<b class="doc-no">${esc(r.doc_no)}</b>`, when(r.created_at), ...(admin ? [esc(r.department_name), esc(r.requester_name)] : []),
        esc(reqSummary(r)), typeBadge(r.req_type), statusBadge(r.status), act];
    });
    $("#list").innerHTML = table(
      ["เลขที่", "วันที่ส่ง", ...(admin ? ["หน่วยงาน", "ผู้เบิก"] : []), "รายการ", "ประเภท", "สถานะ", ""],
      rows, status ? `ไม่มีใบเบิกสถานะ "${STATUS[status][0]}"` : "ยังไม่มีใบเบิก");
  };
  $("#status").onchange = () => load().catch((e) => toast(e.message, true));
  bind({
    open: (id) => openRequisition(id),
    new: () => { if (flow.step === "done") resetFlow(); show("request"); },
    edit: (id) => startEdit(id),
    cancel: async (id, b) => {
      const doc = b.closest("tr").querySelector("b").textContent;
      if (!confirm(`ยกเลิกใบเบิก ${doc}?`)) return;
      try { await api("POST", `/requisitions/${id}/cancel`, {}); toast(`ยกเลิกใบเบิก ${doc} แล้ว`); await load(); }
      catch (err) { toast(err.message, true); }
    },
  });
  await load();
}

// ---------- อนุมัติและสรุปการเบิก (ผู้ดูแล) ----------
// แถว = สินค้า คอลัมน์ = ใบเบิกแต่ละหน่วยงาน รวมยอดอนุมัติเทียบกับคงเหลือ

const board = { filter: "all", edits: {}, approver: "", scroll: [0, 0] };

async function approveView() {
  const [docs, central] = await Promise.all([api("GET", "/requisitions/board"), api("GET", "/people?kind=central")]);
  docs.sort((a, b) => a.created_at.localeCompare(b.created_at));
  const pendingIds = new Set(docs.filter((d) => d.status === "pending").map((d) => String(d.id)));
  Object.keys(board.edits).forEach((id) => { if (!pendingIds.has(id)) delete board.edits[id]; });
  if (!central.some((p) => p.full_name === board.approver)) board.approver = centralDefault(central, "") || central[0]?.full_name || "";

  const val = (d, l) => (d.status === "approved" ? l.qty_approved : board.edits[d.id]?.[l.id] ?? l.qty_requested);
  const items = new Map();
  docs.forEach((d) => d.lines.forEach((l) => { if (!items.has(l.item_id)) items.set(l.item_id, l); }));
  const allItems = [...items.values()].sort((a, b) => a.warehouse_id - b.warehouse_id || a.code.localeCompare(b.code));
  const lineOf = (d, itemId) => d.lines.find((l) => l.item_id === itemId);
  const approvedDocs = () => docs.filter((d) => d.status === "approved");

  view.innerHTML = `${pageHead("อนุมัติและสรุปการเบิก", {
      over: `<span class="badge dark">ADMIN</span><span>ใบเบิกที่ส่งถึง ${when(nowTs())}</span>`,
      right: `<button type="button" class="btn outline" data-act="pdf" id="pdf-btn" title="ดาวน์โหลดเฉพาะใบเบิกที่อนุมัติแล้ว"><span class="tag">PDF</span><span>ดาวน์โหลดสรุป (<span id="pdf-n">0</span> ใบ)</span></button>`,
    })}
    <div class="board-bar"><div class="chips" id="filters"></div><span class="counts" id="counts"></span></div>
    <div class="matrix-wrap" id="matrix"></div>
    <div class="panel board-foot">
      <label><span>ผู้อนุมัติ</span><select id="approver">${central.map((p) => option(p.full_name,
        `${p.full_name}${p.position ? ` · ${p.position.split(" (")[0]}` : ""}`, board.approver)).join("")}</select></label>
      <span class="over-msg" id="over-msg" role="status"></span>
      <button type="button" class="btn primary lg" data-act="approve-all" id="approve-all"></button>
    </div>`;

  const draw = () => keepFocus(() => {
    const shown = docs.filter((d) => board.filter === "all" || d.req_type === board.filter);
    const rows = allItems.filter((it) => shown.some((d) => lineOf(d, it.item_id))).map((it) => {
      let tot = 0, totReq = 0;
      docs.forEach((d) => { const l = lineOf(d, it.item_id); if (l) { tot += Number(val(d, l)); totReq += l.qty_requested; } });
      return { it, tot, totReq, over: tot > it.stock };
    });
    const overCount = rows.filter((r) => r.over).length;
    const pendingShown = shown.filter((d) => d.status === "pending");
    const nApproved = approvedDocs().length;

    $("#filters").innerHTML = [["all", "ทั้งหมด"], ["emergency", "ฉุกเฉิน"], ["routine", "ตามรอบปกติ"]].map(([k, t]) =>
      `<button type="button" class="chip" data-act="filter" data-id="${k}" aria-pressed="${board.filter === k}">${t}</button>`).join("");
    $("#counts").innerHTML = `รออนุมัติ <b style="color:var(--warn)">${docs.length - nApproved}</b> ใบ · อนุมัติแล้ว <b style="color:var(--info)">${nApproved}</b> ใบ`;
    $("#pdf-n").textContent = nApproved;
    $("#pdf-btn").disabled = !nApproved;
    $("#over-msg").textContent = overCount ? `มี ${overCount} รายการที่อนุมัติรวมเกินคงเหลือ — ปรับลดก่อนอนุมัติ` : "";
    const all = $("#approve-all");
    all.textContent = `อนุมัติทั้งหมดที่แสดง (${pendingShown.length} ใบ)`;
    all.disabled = !pendingShown.length || overCount > 0;

    const wrap = $("#matrix");
    const [left, top] = [wrap.scrollLeft, wrap.scrollTop];
    wrap.innerHTML = shown.length ? `<table class="matrix">
      <thead><tr><th class="lbl">สินค้า \\ ใบเบิก</th>
        ${shown.map((d) => {
          const done = d.status === "approved";
          return `<th class="${done ? "is-approved" : ""}"><div class="doc-col">
            <b>${esc(d.department_name)}</b><small>${esc(d.doc_no)} · ${esc((d.requester_name || "").split(" ")[0])}</small>
            <div class="badges">${typeBadge(d.req_type)}${statusBadge(d.status)}</div>
            ${done ? `<button type="button" class="link muted" data-act="unapprove" data-id="${d.id}">ยกเลิกอนุมัติ</button>`
              : `<button type="button" class="btn outline" data-act="approve-one" data-id="${d.id}">อนุมัติใบนี้</button>`}
          </div></th>`;
        }).join("")}
        <th class="lbl num">รวมอนุมัติ</th><th class="lbl num">คงเหลือ</th></tr></thead>
      <tbody>${rows.map(({ it, tot, totReq, over }) => `<tr class="${over ? "over" : ""}">
        <td class="item-name"><span>${esc(it.name)}</span><small>${esc(it.warehouse_name)} · ${esc(it.unit)}</small></td>
        ${shown.map((d) => {
          const l = lineOf(d, it.item_id);
          if (!l) return `<td class="none">–</td>`;
          const v = val(d, l);
          const done = d.status === "approved";
          const changed = !done && Number(v) !== l.qty_requested;
          return `<td class="cell ${done ? "is-approved" : ""}"><input class="qty-input ${changed ? "changed" : ""}" data-doc="${d.id}" data-line="${l.id}"
            value="${v}" inputmode="decimal" ${done ? "disabled" : ""} aria-label="จำนวนอนุมัติ ${esc(it.name)} ใบ ${esc(d.doc_no)}">
            <small>ขอ ${num(l.qty_requested)}</small></td>`;
        }).join("")}
        <td class="tot num"><b>${num(tot)}</b><small>ขอ ${num(totReq)}</small></td>
        <td class="num"><span class="stock">${num(it.stock)}</span>${over ? `<small class="minus" style="display:block;font-size:11px;white-space:nowrap">เกิน ${num(tot - it.stock)}</small>` : ""}</td>
      </tr>`).join("")}</tbody></table>`
      : `<p class="empty">${docs.length ? "ไม่มีใบเบิกประเภทนี้" : "ไม่มีใบเบิกที่รออนุมัติหรือรอจ่าย"}</p>`;
    wrap.scrollLeft = left || board.scroll[0];
    wrap.scrollTop = top || board.scroll[1];
    board.scroll = [0, 0];
  });

  const approver = () => central.find((p) => p.full_name === board.approver);
  const approveDoc = async (d) => api("POST", `/requisitions/${d.id}/approve`, {
    approver_name: board.approver, approver_position: approver()?.position ?? null,
    lines: d.lines.map((l) => ({ line_id: l.id, qty_approved: val(d, l) })),
  });
  const reload = () => {
    board.scroll = [$("#matrix").scrollLeft, $("#matrix").scrollTop];
    return approveView().catch((e) => toast(e.message, true));
  };
  const docOf = (id) => docs.find((d) => String(d.id) === String(id));

  view.onchange = (e) => {
    const t = e.target;
    if (rendering) return;
    if (t.id === "approver") board.approver = t.value;
    if (t.matches(".qty-input")) {
      const d = docOf(t.dataset.doc);
      const l = d.lines.find((x) => String(x.id) === t.dataset.line);
      const v = Math.min(l.qty_requested, Math.max(0, Number(t.value) || 0));
      board.edits[d.id] = { ...(board.edits[d.id] || {}), [l.id]: v };
      afterPointer(t, draw);
    }
  };
  view.onkeydown = (e) => {
    if (e.key === "Enter" && e.target.matches(".qty-input")) { e.preventDefault(); e.target.dispatchEvent(new Event("change", { bubbles: true })); }
  };
  bind({
    filter: (k) => { board.filter = k; draw(); },
    "approve-one": async (id, b) => {
      if (!board.approver) return toast("กรุณาเลือกผู้อนุมัติ", true);
      b.disabled = true;
      const d = docOf(id);
      try { await approveDoc(d); toast(`อนุมัติ ${d.doc_no} (${d.department_name}) แล้ว`); } catch (e) { toast(e.message, true); }
      reload();
    },
    unapprove: async (id) => {
      const d = docOf(id);
      try { await api("POST", `/requisitions/${id}/unapprove`, {}); toast(`ยกเลิกอนุมัติ ${d.doc_no} แล้ว แก้จำนวนได้อีกครั้ง`); } catch (e) { toast(e.message, true); }
      reload();
    },
    "approve-all": async (_, b) => {
      if (!board.approver) return toast("กรุณาเลือกผู้อนุมัติ", true);
      const list = docs.filter((d) => d.status === "pending" && (board.filter === "all" || d.req_type === board.filter));
      b.disabled = true;
      let n = 0;
      try { for (const d of list) { await approveDoc(d); n++; } toast(`อนุมัติ ${n} ใบเบิกแล้ว`); }
      catch (e) { toast(`อนุมัติแล้ว ${n} ใบ · ${e.message}`, true); }
      reload();
    },
    pdf: () => openSummary(approvedDocs(), approver() || { full_name: board.approver }),
  });
  draw();
}

function summaryHtml(docs, approver) {
  const items = new Map();
  docs.forEach((d) => d.lines.forEach((l) => { if (!items.has(l.item_id)) items.set(l.item_id, l); }));
  const list = [...items.values()].sort((a, b) => a.warehouse_id - b.warehouse_id || a.code.localeCompare(b.code));
  const qty = (d, itemId) => d.lines.find((l) => l.item_id === itemId)?.qty_approved;
  return `<h1>สรุปการอนุมัติเบิกเวชภัณฑ์และพัสดุ</h1>
    <p class="center">งานบริหารเวชภัณฑ์ (คลังกลาง) โรงพยาบาลตาพระยา<br>วันที่ ${when(nowTs(), false)} · ใบเบิก ${esc(docs.map((d) => d.doc_no).join(", "))}</p>
    <table>
      <thead><tr><th>ลำดับ</th><th>รายการ</th><th>หน่วย</th>${docs.map((d) => `<th class="num">${esc(d.department_code)}</th>`).join("")}<th class="num">รวม</th></tr></thead>
      <tbody>${list.map((it, i) => `<tr><td>${i + 1}</td><td>${esc(it.name)}</td><td>${esc(it.unit)}</td>
        ${docs.map((d) => { const q = qty(d, it.item_id); return `<td class="num">${q == null ? "–" : num(q)}</td>`; }).join("")}
        <td class="num"><b>${num(docs.reduce((a, d) => a + (Number(qty(d, it.item_id)) || 0), 0))}</b></td></tr>`).join("")}</tbody>
    </table>
    <div class="legend-list">${docs.map((d) => `<span>${esc(d.department_code)} = ${esc(d.department_name)} (${esc(d.doc_no)}, ${esc(REQ_TYPE[d.req_type]?.[0] || "-")}) ผู้เบิก ${esc(d.requester_name)}</span>`).join("")}</div>
    <div class="signs">
      <div class="sign">ลงชื่อ ................................................ ผู้อนุมัติ<br>( ${esc(approver?.full_name || "................................................")} )<br>${esc(approver?.position || "ตำแหน่ง ........................................")}</div>
      <div class="sign">ลงชื่อ ................................................ ผู้จ่าย<br>( ................................................ )<br>ตำแหน่ง ........................................</div>
    </div>`;
}

// ดาวน์โหลด PDF ผ่านหน้าพิมพ์ของเบราว์เซอร์ (เลือก "บันทึกเป็น PDF") ไม่ต้องใช้ไลบรารีเพิ่ม
function openSummary(docs, approver) {
  if (!docs.length) return;
  const html = summaryHtml(docs, approver);
  dlg.className = "wide";
  dlg.innerHTML = dialogShell("ตัวอย่างไฟล์ PDF",
    `<p class="hint">A4 ขาวดำ เฉพาะใบเบิกที่อนุมัติแล้ว พร้อมช่องลงชื่อ · กด "ดาวน์โหลด PDF" แล้วเลือกเครื่องพิมพ์ <b>บันทึกเป็น PDF</b> (Save as PDF)</p>
     <div class="paper print-doc">${html}</div>`, "ดาวน์โหลด PDF", "ปิด");
  wireDialog(() => {
    $("#print").innerHTML = html;
    const title = document.title;
    const [y, m, d] = nowTs().slice(0, 10).split("-");
    document.title = `สรุปอนุมัติเบิก_${d}-${m}-${Number(y) + 543}`;
    window.print();
    document.title = title;
  });
}

// ---------- สินค้าและสต็อก (ผู้ดูแล) ----------

async function itemsView() {
  const items = await api("GET", "/items?all=1");
  const units = [...new Set(items.map((i) => i.unit))].sort();
  view.innerHTML = `${pageHead("สินค้าและสต็อก", {
      right: `<select id="wh" aria-label="กรองตามคลัง" style="width:auto">${option("", "ทุกคลัง")}${warehouses.map((w) => option(w.id, w.name)).join("")}</select>
        <input type="search" id="q" placeholder="ค้นหารหัสหรือชื่อ" aria-label="ค้นหาสินค้า" style="width:auto;min-width:200px">
        <button type="button" class="btn primary" data-act="new">+ เพิ่มสินค้า</button>`,
    })}
    <datalist id="units">${units.map((u) => `<option value="${esc(u)}">`).join("")}</datalist>
    <div class="list" id="list"></div>`;
  const state = (i) => !i.active ? badge("งดเบิก", "muted")
    : i.min_qty > 0 && i.qty <= i.min_qty ? badge("ใกล้หมด", "warn") : badge("ปกติ", "ok");
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    const wh = $("#wh").value;
    $("#list").innerHTML = table(
      ["รหัส", "รายการ", "คลัง", "หน่วย", ["คงเหลือ", "num"], ["จุดสั่งซื้อ", "num"], "สถานะ", ""],
      items.filter((i) => (!q || `${i.code} ${i.name}`.toLowerCase().includes(q)) && (!wh || i.warehouse_id === Number(wh))).map((i) => [
        esc(i.code), esc(i.name), esc(i.warehouse_name || "-"), esc(i.unit), [num(i.qty), "num"], [num(i.min_qty), "num"], state(i),
        actions(btn("adjust", "รับเข้า/ปรับ", i.id), btn("edit", "แก้ไข", i.id), btn("history", "ประวัติ", i.id)),
      ]),
      q || wh ? "ไม่พบสินค้าที่ค้นหา" : 'ยังไม่มีสินค้า กด "+ เพิ่มสินค้า" เพื่อเริ่ม');
  };
  $("#q").oninput = draw;
  $("#wh").onchange = draw;
  draw();

  const byId = (id) => items.find((i) => String(i.id) === String(id));
  const fields = [
    { name: "code", label: "รหัสสินค้า", required: true, placeholder: "เช่น MED-0001" },
    { name: "name", label: "ชื่อสินค้า", required: true, placeholder: "เช่น ถุงมือยาง ไซส์ M" },
    { name: "warehouse_id", label: "คลัง", type: "select", required: true, options: [["", "— เลือกคลัง —"], ...warehouses.map((w) => [w.id, w.name])] },
    { name: "unit", label: "หน่วยนับ", required: true, list: "units", placeholder: "เช่น กล่อง, ชิ้น, ขวด, รีม", hint: "สินค้าละหน่วยนับเดียว" },
    { name: "min_qty", label: "จุดสั่งซื้อ", type: "number", min: 0, value: 0, hint: "คงเหลือเท่านี้หรือน้อยกว่าจะแจ้งเตือนว่าใกล้หมด" },
  ];
  bind({
    new: () => openForm({
      title: "เพิ่มสินค้า",
      fields: [...fields, { name: "initial_qty", label: "ยอดคงเหลือตอนนี้", type: "number", min: 0 }],
      values: { warehouse_id: $("#wh").value },
      onSubmit: async (d) => { await api("POST", "/items", d); toast("เพิ่มสินค้าแล้ว"); refresh(); },
    }),
    edit: (id) => {
      const item = byId(id);
      openForm({
        title: `แก้ไขสินค้า ${item.code}`,
        fields: [...fields, { name: "active", label: "การเบิก", type: "select", options: [["1", "เปิดให้เบิก"], ["0", "งดเบิก (ซ่อนจากหน่วยงาน)"]] }],
        values: { ...item, active: String(item.active) },
        onSubmit: async (d) => { await api("PUT", `/items/${id}`, { ...d, active: d.active === "1" }); toast("บันทึกแล้ว"); refresh(); },
      });
    },
    adjust: (id) => {
      const item = byId(id);
      openForm({
        title: `รับเข้า/ปรับสต็อก ${item.code}`,
        intro: `<p class="hint">${esc(item.name)} — คงเหลือ <b>${num(item.qty)} ${esc(item.unit)}</b></p>`,
        fields: [
          { name: "direction", label: "ประเภท", type: "select", options: [["in", "รับเข้า (+)"], ["out", "ปรับลด (−) เช่น หมดอายุ ชำรุด ตรวจนับ"]] },
          { name: "amount", label: `จำนวน (${item.unit})`, type: "number", min: 0, required: true },
          { name: "reason", label: "หมายเหตุ", placeholder: "เช่น รับจากใบส่งของเลขที่ 123, หมดอายุ" },
        ],
        onSubmit: async (d) => {
          const amount = Number(d.amount);
          await api("POST", `/items/${id}/adjust`, { delta: d.direction === "out" ? -amount : amount, reason: d.reason });
          toast("ปรับสต็อกแล้ว"); refresh();
        },
      });
    },
    history: async (id) => {
      const item = byId(id);
      const list = await api("GET", `/movements?item_id=${id}&limit=200`);
      dlg.className = "wide";
      dlg.innerHTML = dialogShell(`ประวัติ ${esc(item.code)} ${esc(item.name)}`, movementTable(list, false), null, "ปิด");
      wireDialog(() => {});
    },
  });
}

function movementTable(list, withItem = true) {
  return table(
    ["วันที่", ...(withItem ? ["รายการ"] : []), ["จำนวน", "num"], ["คงเหลือ", "num"], "หมายเหตุ", "ผู้บันทึก"],
    list.map((m) => [
      when(m.ts), ...(withItem ? [`${esc(m.name)} <small>${esc(m.code)}</small>`] : []),
      [`<span class="${m.delta > 0 ? "plus" : "minus"}">${m.delta > 0 ? "+" : ""}${num(m.delta)}</span> <small>${esc(m.unit)}</small>`, "num"],
      [num(m.balance), "num"], esc(m.reason), esc(m.user_name || "-"),
    ]),
    "ยังไม่มีความเคลื่อนไหว");
}

async function movementsView() {
  const list = await api("GET", "/movements?limit=1000");
  view.innerHTML = `${pageHead("ประวัติสต็อก", {
      right: `<input type="search" id="q" placeholder="ค้นหาสินค้า เลขที่ใบเบิก หรือหมายเหตุ" aria-label="ค้นหา" style="width:auto;min-width:260px">`,
    })}<div class="list" id="list"></div>`;
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    $("#list").innerHTML = movementTable(list.filter((m) => !q || `${m.code} ${m.name} ${m.reason}`.toLowerCase().includes(q)));
  };
  $("#q").oninput = draw;
  bind({});
  draw();
}

// ---------- ทะเบียน ----------

async function peopleView(kind) {
  const admin = me.role === "admin";
  const [list, departments, positions] = await Promise.all([
    api("GET", `/people?kind=${kind}`),
    kind === "central" ? [] : api("GET", "/departments"),
    api("GET", `/positions?scope=${scopeOf(kind)}`),
  ]);
  let editing = null; // null | {} (เพิ่มใหม่) | รายชื่อที่กำลังแก้
  const draw = () => {
    const withDept = kind !== "central";
    const deptField = !withDept ? "" : admin
      ? `<label class="field"><span>หน่วยงาน</span><select name="department_id" required>${option("", "— เลือกหน่วยงาน —", editing?.department_id)}${
        departments.filter((d) => d.active || d.id === editing?.department_id).map((d) => option(d.id, d.name, editing?.department_id)).join("")}</select></label>`
      : `<label class="field"><span>หน่วยงาน</span><input value="${esc(me.department_name || "")}" disabled></label>`;
    view.innerHTML = `${pageHead(REG_NAME[kind], {
        over: `ทะเบียน · ใช้เป็นรายการให้เลือกในใบเบิก${!admin ? ` · ${esc(me.department_name || "")}` : ""}`,
        right: `<button type="button" class="btn primary" data-act="new">+ เพิ่มรายชื่อ</button>`,
      })}
      ${editing ? `<form class="inline-form" id="p-form" style="${withDept ? "" : "grid-template-columns:minmax(0,1.2fr) minmax(0,1.2fr) auto"}">
        <label class="field"><span>ชื่อ-นามสกุล</span><input name="full_name" required placeholder="ชื่อ นามสกุล" value="${esc(editing.full_name || "")}"></label>
        <label class="field"><span>ตำแหน่ง</span><input name="position" list="pos-list" placeholder="เลือกหรือพิมพ์ตำแหน่ง" value="${esc(editing.position || "")}"></label>
        ${deptField}
        <div class="btns"><button type="submit" class="btn primary">บันทึก</button><button type="button" class="btn" data-act="close">ยกเลิก</button></div>
        <datalist id="pos-list">${positions.map((p) => `<option value="${esc(p.name)}">`).join("")}</datalist>
      </form>` : ""}
      <div class="list">${table([["ลำดับ", "num"], "ชื่อ-นามสกุล", "ตำแหน่ง", ...(withDept ? ["หน่วยงาน"] : []), ""],
        list.map((p, i) => [[i + 1, "num"], `<b style="font-weight:500">${esc(p.full_name)}</b>`, esc(p.position || "-"),
          ...(withDept ? [`<span class="muted">${esc(p.department_name || "-")}</span>`] : []),
          actions(btn("edit", "แก้ไข", p.id), btn("remove", "ลบ", p.id, "danger"))]),
        'ยังไม่มีรายชื่อ กด "+ เพิ่มรายชื่อ"')}</div>`;
    const form = $("#p-form");
    if (!form) return;
    $("input", form).focus();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(form));
      try {
        const body = { ...d, kind, department_id: d.department_id ? Number(d.department_id) : me.department_id };
        await api(editing.id ? "PUT" : "POST", editing.id ? `/people/${editing.id}` : "/people", body);
        toast(`บันทึก ${d.full_name} ลง${REG_NAME[kind]}แล้ว`);
        refresh();
      } catch (err) { toast(err.message, true); }
    };
  };
  const byId = (id) => list.find((p) => String(p.id) === String(id));
  bind({
    new: () => { editing = {}; draw(); },
    edit: (id) => { editing = byId(id); draw(); },
    close: () => { editing = null; draw(); },
    remove: async (id) => {
      const p = byId(id);
      if (!confirm(`ลบ ${p.full_name} ออกจาก${REG_NAME[kind]}? ใบเบิกเดิมยังเก็บชื่อไว้ตามเดิม`)) return;
      try { await api("DELETE", `/people/${id}`); toast("ลบรายชื่อแล้ว"); refresh(); } catch (err) { toast(err.message, true); }
    },
  });
  draw();
}

async function departmentsView() {
  const admin = me.role === "admin";
  const list = await api("GET", "/departments");
  const groups = [...new Set(["กลุ่มการพยาบาล", "กลุ่มงานบริการด้านปฐมภูมิ", "กลุ่มงานเทคนิคการแพทย์", "กลุ่มงานทันตกรรม", "กลุ่มงานบริหารทั่วไป",
    ...list.map((d) => d.group_name).filter(Boolean)])];
  let editing = null;
  const draw = () => {
    view.innerHTML = `${pageHead("ทะเบียนหน่วยเบิกในรพ.", {
        over: "ทะเบียน · หน่วยงานที่เบิกจากคลังกลางได้",
        right: admin ? `<button type="button" class="btn primary" data-act="new">+ เพิ่มหน่วยเบิก</button>` : "",
      })}
      ${editing ? `<form class="inline-form" id="d-form" style="grid-template-columns:120px minmax(0,1.4fr) minmax(0,1fr)${editing.id ? " 130px" : ""} auto">
        <label class="field"><span>รหัสหน่วย</span><input name="code" required placeholder="เช่น PCU" value="${esc(editing.code || "")}" style="text-transform:uppercase"></label>
        <label class="field"><span>ชื่อหน่วยเบิก</span><input name="name" required placeholder="เช่น หน่วยบริการปฐมภูมิ" value="${esc(editing.name || "")}"></label>
        <label class="field"><span>กลุ่มงาน</span><input name="group_name" list="group-list" placeholder="เลือกหรือพิมพ์กลุ่มงาน" value="${esc(editing.group_name || "")}"></label>
        ${editing.id ? `<label class="field"><span>สถานะ</span><select name="active">${option("1", "ใช้งาน", editing.active)}${option("0", "ปิดใช้งาน", editing.active)}</select></label>` : ""}
        <div class="btns"><button type="submit" class="btn primary">บันทึก</button><button type="button" class="btn" data-act="close">ยกเลิก</button></div>
        <datalist id="group-list">${groups.map((g) => `<option value="${esc(g)}">`).join("")}</datalist>
      </form>` : ""}
      <div class="list">${table(["รหัสหน่วย", "ชื่อหน่วยเบิก", "กลุ่มงาน", ["ผู้เบิกสินค้า", "num"], ["ผู้รับสินค้า", "num"], ...(admin ? ["สถานะ", ""] : [])],
        list.map((d) => [`<span class="code-cell">${esc(d.code || "-")}</span>`, `<b style="font-weight:500">${esc(d.name)}</b>`,
          `<span class="muted">${esc(d.group_name || "-")}</span>`, [`${num(d.requester_count)} คน`, "num"], [`${num(d.receiver_count)} คน`, "num"],
          ...(admin ? [d.active ? badge("ใช้งาน", "ok") : badge("ปิดใช้งาน", "muted"), actions(btn("edit", "แก้ไข", d.id))] : [])]),
        "ยังไม่มีหน่วยเบิก")}</div>`;
    const form = $("#d-form");
    if (!form) return;
    $("input", form).focus();
    form.onsubmit = async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(form));
      try {
        await api(editing.id ? "PUT" : "POST", editing.id ? `/departments/${editing.id}` : "/departments",
          { ...d, active: d.active !== "0" });
        toast("บันทึกหน่วยเบิกแล้ว");
        refresh();
      } catch (err) { toast(err.message, true); }
    };
  };
  bind({
    new: () => { editing = {}; draw(); },
    edit: (id) => { editing = { ...list.find((d) => String(d.id) === id) }; editing.active = String(editing.active); draw(); },
    close: () => { editing = null; draw(); },
  });
  draw();
}

async function usersView() {
  const [users, departments] = await Promise.all([api("GET", "/users"), api("GET", "/departments")]);
  view.innerHTML = `${pageHead("บัญชีผู้ใช้", { right: `<button type="button" class="btn primary" data-act="new">+ เพิ่มผู้ใช้</button>` })}
    <p class="hint">เข้าสู่ระบบด้วย <b>เลขบัตรประชาชน 13 หลัก</b> ครั้งแรกใช้รหัสผ่าน <b>เลข 5 ตัวท้ายของบัตร</b> แล้วระบบจะบังคับให้ตั้งรหัสผ่านใหม่ · ถ้าลืมรหัสผ่าน กด "แก้ไข" แล้วเลือกรีเซ็ตรหัสผ่าน · บัญชี <b>หน่วยงาน</b> เบิกสินค้าและดูได้เฉพาะใบเบิกของหน่วยงานตัวเอง บัญชี <b>ผู้ดูแลคลังกลาง</b> อนุมัติ จ่ายของ และจัดการสต็อกได้</p>
    <div class="list">${table(["เลขบัตรประชาชน", "ชื่อ-นามสกุล", "สิทธิ์", "หน่วยงาน", "สถานะ", ""],
      users.map((u) => [`<span style="font-variant-numeric:tabular-nums">${esc(maskId(u.username))}</span>`, esc(u.full_name),
        u.role === "admin" ? badge("ผู้ดูแลคลังกลาง", "info") : "หน่วยงาน",
        esc(u.department_name || "-"), u.active ? badge("ใช้งาน", "ok") : badge("ปิดใช้งาน", "muted"),
        actions(btn("edit", "แก้ไข", u.id))]), "ยังไม่มีผู้ใช้")}</div>`;
  const deptOptions = [["", "— ไม่ระบุ —"], ...departments.map((d) => [d.id, d.name + (d.active ? "" : " (ปิดใช้งาน)")])];
  const form = (u) => openForm({
    title: u ? `แก้ไขผู้ใช้ ${u.full_name}` : "เพิ่มผู้ใช้",
    fields: [
      ...(u ? [] : [{ name: "username", label: "เลขบัตรประชาชน 13 หลัก", required: true, placeholder: "x-xxxx-xxxxx-xx-x", autocomplete: "off",
        inputmode: "numeric", hint: "รหัสผ่านครั้งแรกคือเลข 5 ตัวท้ายของบัตร แล้วต้องตั้งรหัสใหม่" }]),
      { name: "full_name", label: "ชื่อ-นามสกุล", required: true },
      { name: "role", label: "สิทธิ์", type: "select", options: [["dept", "หน่วยงาน (เบิกสินค้า)"], ["admin", "ผู้ดูแลคลังกลาง"]] },
      { name: "department_id", label: "หน่วยงาน", type: "select", options: deptOptions, hint: "จำเป็นสำหรับสิทธิ์หน่วยงาน" },
      ...(u ? [{ name: "active", label: "สถานะ", type: "select", options: [["1", "ใช้งาน"], ["0", "ปิดใช้งาน"]] },
        { name: "reset_password", label: "รหัสผ่าน", type: "select", options: [["0", "ไม่เปลี่ยน"], ["1", "รีเซ็ตเป็นเลข 5 ตัวท้ายของบัตร (ผู้ใช้ต้องตั้งใหม่)"]],
          hint: "ใช้เมื่อผู้ใช้ลืมรหัสผ่าน · การบันทึกจะปลดล็อกบัญชีที่ใส่รหัสผิดหลายครั้งด้วย" }] : []),
    ],
    values: u ? { ...u, active: String(u.active) } : { role: "dept" },
    onSubmit: async (v) => {
      if (!u) v.username = v.username.replace(/\D/g, "");
      await api(u ? "PUT" : "POST", u ? `/users/${u.id}` : "/users", { ...v, active: v.active !== "0", reset_password: v.reset_password === "1" });
      toast(v.reset_password === "1" ? `รีเซ็ตรหัสผ่านของ ${v.full_name} แล้ว` : "บันทึกแล้ว"); refresh();
    },
  });
  bind({ new: () => form(), edit: (id) => form(users.find((u) => String(u.id) === id)) });
}

// ---------- Dashboard วิเคราะห์การเบิก ----------

async function analyticsView() {
  const admin = me.role === "admin";
  const [a, s] = await Promise.all([api("GET", "/analytics"), admin ? api("GET", "/summary") : null]);
  const t = a.totals;
  const dur = (h) => (h == null ? "-" : h >= 24 ? `${num(Math.round((h / 24) * 10) / 10)} วัน` : `${num(Math.round(h * 10) / 10)} ชั่วโมง`);
  const maxW = Math.max(1, ...a.weeks.map((w) => w.emergency + w.routine));
  const maxC = Math.max(1, ...a.by_warehouse.map((w) => w.lines));
  const maxD = Math.max(1, ...a.by_department.map((d) => d.total));
  const pctE = t.requisitions ? Math.round((t.emergency / t.requisitions) * 100) : 0;
  const kpi = (label, value, sub, cls = "") => `<div class="kpi"><span>${label}</span><b class="${cls}">${value}</b><small>${sub}</small></div>`;
  view.innerHTML = `${pageHead("Dashboard วิเคราะห์การเบิก", { over: `ข้อมูล ${a.weeks.length} สัปดาห์ล่าสุด · ${when(a.from, false)} – ${when(a.to, false)}` })}
    <div class="kpis">
      ${kpi("ใบเบิกทั้งหมด", num(t.requisitions), `เฉลี่ย ${num(Math.round(t.requisitions / Math.max(1, a.weeks.length)))} ใบ/สัปดาห์`)}
      ${kpi("เบิกฉุกเฉิน", num(t.emergency), `${pctE}% ของใบเบิกทั้งหมด`, "tone-bad")}
      ${kpi("รายการที่จ่ายออก", num(t.lines_issued), `จาก ${num(a.by_warehouse.filter((w) => w.lines).length)} คลัง`)}
      ${kpi("เวลาเฉลี่ยจนได้รับของ", dur(t.avg_hours), `ฉุกเฉินเฉลี่ย ${dur(t.avg_hours_emergency)}`, "tone-brand")}
    </div>
    <div class="charts">
      <section class="chart" aria-label="ความถี่การเบิกฉุกเฉิน รายสัปดาห์">
        <div class="chart-title"><b>ความถี่การเบิกฉุกเฉิน รายสัปดาห์</b>
          <span class="legend"><i class="sw-emerg"></i>ฉุกเฉิน</span><span class="legend"><i class="sw-routine"></i>ตามรอบปกติ</span></div>
        <div class="weeks">${a.weeks.map((w) => `<div class="week" title="สัปดาห์เริ่ม ${when(w.start, false)}: ฉุกเฉิน ${w.emergency} ใบ, ตามรอบ ${w.routine} ใบ">
          <span class="e-n">${w.emergency || ""}</span>
          <div class="bar e" style="height:${Math.round((w.emergency / maxW) * 160)}px"></div>
          <div class="bar n" style="height:${Math.round((w.routine / maxW) * 160)}px"></div></div>`).join("")}</div>
        <div class="week-labels">${a.weeks.map((w) => `<span>${when(w.start, false).slice(0, 5)}</span>`).join("")}</div>
      </section>
      <section class="chart">
        <div class="chart-title"><b>สถิติการใช้สินค้าตามประเภทคลัง</b><small>จำนวนรายการที่จ่ายออก</small></div>
        ${a.by_warehouse.map((w) => `<div class="hbar"><span title="${esc(w.name)}">${esc(w.name)}</span>
          <div class="track"><div class="fill" style="width:${(w.lines / maxC) * 100}%;--h:${Number(w.hue) || 0}"></div></div><b>${num(w.lines)}</b></div>`).join("")}
      </section>
    </div>
    <div class="charts even">
      <section class="chart">
        <div class="chart-title"><b>หน่วยงานที่เบิกมากที่สุด</b><small>จำนวนใบเบิก · ส่วนสีแดงคือเบิกฉุกเฉิน</small></div>
        ${a.by_department.length ? a.by_department.map((d) => `<div class="hbar"><span title="${esc(d.name)}">${esc(d.name)}</span>
          <div class="track split"><div class="fill e" style="width:${(d.emergency / maxD) * 100}%"></div><div class="fill n" style="width:${((d.total - d.emergency) / maxD) * 100}%${d.emergency ? "" : ";border-radius:99px"}"></div></div>
          <span class="v"><b>${num(d.total)}</b> <small>(${num(d.emergency)})</small></span></div>`).join("") : `<p class="empty">ยังไม่มีข้อมูล</p>`}
      </section>
      <section class="chart" style="gap:4px">
        <div class="chart-title" style="padding-bottom:8px"><b>สินค้าที่เบิกมากที่สุด</b></div>
        ${a.top_items.length ? a.top_items.map((it, i) => `<div class="top-row"><b>${i + 1}</b><div><span>${esc(it.name)}</span><small>${esc(it.warehouse_name)}</small></div>
          <span class="qty-u">${num(it.qty)} <small>${esc(it.unit)}</small></span></div>`).join("") : `<p class="empty">ยังไม่มีข้อมูล</p>`}
      </section>
    </div>
    ${s ? `<div class="charts even">
      <section class="chart"><div class="chart-title"><b>ใบเบิกที่ต้องดำเนินการ</b>
          <button type="button" class="link" data-act="go" data-id="approve">ไปหน้าอนุมัติ →</button></div>
        ${table(["เลขที่", "หน่วยงาน", "ประเภท", "สถานะ"], s.waiting.map((r) => [`<b class="doc-no">${esc(r.doc_no)}</b>`, esc(r.department_name), typeBadge(r.req_type), statusBadge(r.status)]), "ไม่มีใบเบิกค้าง")}</section>
      <section class="chart"><div class="chart-title"><b>สินค้าใกล้หมด</b>
          <button type="button" class="link" data-act="go" data-id="items">สินค้า/สต็อก →</button></div>
        ${table(["รายการ", "คลัง", ["คงเหลือ", "num"], ["จุดสั่งซื้อ", "num"]], s.low_stock.map((i) => [esc(i.name), esc(i.warehouse_name || "-"),
          [`<span class="${i.qty <= 0 ? "minus" : ""}">${num(i.qty)}</span> ${esc(i.unit)}`, "num"], [num(i.min_qty), "num"]]), "สต็อกปกติทุกรายการ")}</section>
    </div>` : ""}`;
  bind({ go: (tab) => show(tab) });
}

// ---------- เข้าสู่ระบบ: เลขบัตรประชาชน 13 หลัก + รหัสผ่าน (ครั้งแรกคือ 5 ตัวท้าย แล้วต้องตั้งใหม่) ----------

function authScreen(setupMode) {
  document.body.classList.add("auth");
  $("#tabs").innerHTML = "";
  $("#userbox").innerHTML = "";
  view.onclick = view.onchange = view.oninput = view.onkeydown = null;
  view.innerHTML = `<div class="login">
    <div class="login-brand">
      <div class="logo"></div>
      <div class="login-copy">
        <small>โรงพยาบาลตาพระยา</small>
        <h1>งานบริหารเวชภัณฑ์<br>(คลังกลาง)</h1>
        <p>เบิกยา เวชภัณฑ์ และพัสดุจากคลังกลางให้หน่วยงาน ติดตามสถานะใบเบิกได้ในที่เดียว</p>
      </div>
    </div>
    <div class="login-main">
      <form class="login-form" id="auth-form" novalidate>
        <div><h2>${setupMode ? "ตั้งค่าระบบครั้งแรก" : "เข้าสู่ระบบ"}</h2>
          <span class="sub">${setupMode ? "สร้างบัญชีผู้ดูแลคลังกลางคนแรก" : "ใช้เลขบัตรประจำตัวประชาชนของเจ้าหน้าที่"}</span></div>
        ${setupMode ? fieldHtml({ name: "full_name", label: "ชื่อ-นามสกุล", required: true }) : ""}
        <label class="field"><span>เลขบัตรประจำตัวประชาชน 13 หลัก</span>
          <input class="nid" id="nid" inputmode="numeric" autocomplete="username" placeholder="x-xxxx-xxxxx-xx-x" aria-describedby="nid-count">
          <small id="nid-count">กรอกแล้ว 0/13 หลัก</small></label>
        ${setupMode ? `<p class="hint">รหัสผ่านเริ่มต้นคือเลข 5 ตัวท้ายของบัตรประชาชน ระบบจะให้ตั้งรหัสผ่านใหม่ทันทีหลังสร้างบัญชี</p>` : `<div class="field">
          <span><label for="pw">รหัสผ่าน</label></span>
          <div class="pw"><input id="pw" type="password" autocomplete="current-password" placeholder="รหัสผ่าน" aria-describedby="pw-hint">
            <button type="button" id="pw-toggle" aria-pressed="false" aria-controls="pw">แสดง</button></div>
          <small id="pw-hint">เข้าครั้งแรกใช้เลข 5 ตัวท้ายของบัตรประชาชน แล้วระบบจะให้ตั้งรหัสผ่านใหม่</small></div>`}
        <p class="form-error" role="alert" hidden></p>
        <button type="submit" class="btn primary block">${setupMode ? "สร้างบัญชีและเข้าสู่ระบบ" : "เข้าสู่ระบบ"}</button>
        <small class="center">ลืมรหัสผ่านหรือยังไม่มีบัญชี ติดต่อเจ้าหน้าที่คลังกลาง</small>
      </form>
    </div>
  </div>`;
  const form = $("#auth-form");
  const nid = $("#nid");
  const pw = $("#pw");
  const error = $(".form-error", form);
  const digits = () => nid.value.replace(/\D/g, "").slice(0, 13);
  nid.oninput = () => {
    const d = digits();
    nid.value = fmtId(d);
    $("#nid-count").textContent = `กรอกแล้ว ${d.length}/13 หลัก`;
    nid.classList.remove("invalid");
    error.hidden = true;
  };
  if (pw) {
    pw.oninput = () => { error.hidden = true; };
    $("#pw-toggle").onclick = (e) => {
      const show = pw.type === "password";
      pw.type = show ? "text" : "password";
      e.target.textContent = show ? "ซ่อน" : "แสดง";
      e.target.setAttribute("aria-pressed", String(show));
    };
  }
  $("input", form).focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const d = digits();
    const fullName = form.full_name?.value.trim();
    const fail = (msg, bad) => {
      error.textContent = msg;
      error.hidden = false;
      if (bad) { bad.classList.add("invalid"); bad.focus(); }
    };
    if (setupMode && !fullName) return fail("กรุณาระบุชื่อ-นามสกุล", form.full_name);
    if (d.length !== 13) return fail("กรุณากรอกเลขบัตรประชาชนให้ครบ 13 หลัก", nid);
    if (!setupMode && !pw.value) return fail("กรุณากรอกรหัสผ่าน", pw);
    const submit = $("button[type=submit]", form);
    submit.disabled = true;
    try {
      me = await api("POST", setupMode ? "/setup" : "/login", setupMode
        ? { full_name: fullName, username: d, password: d.slice(-5) }
        : { username: d, password: pw.value });
      await startApp(setupMode ? d.slice(-5) : pw.value);
    } catch (err) {
      fail(err.message);
      submit.disabled = false;
    }
  };
}

// ---------- เมนูและการสลับหน้า ----------

const VIEWS = {
  approve: ["อนุมัติและสรุปการเบิก", approveView, "admin"],
  request: ["เบิกสินค้า", requestView],
  requisitions: [() => (me.role === "admin" ? "ใบเบิก / จ่ายสินค้า" : "ใบเบิกของหน่วยงาน"), requisitionsView],
  items: ["สินค้า/สต็อก", itemsView, "admin"],
  movements: ["ประวัติสต็อก", movementsView, "admin"],
  regRequester: ["ทะเบียนผู้เบิกสินค้า", () => peopleView("requester")],
  regReceiver: ["ทะเบียนผู้รับสินค้า", () => peopleView("receiver")],
  regCentral: ["ทะเบียนเจ้าหน้าที่คลังกลาง", () => peopleView("central"), "admin"],
  departments: ["ทะเบียนหน่วยเบิกในรพ.", departmentsView],
  users: ["บัญชีผู้ใช้", usersView, "admin"],
  analytics: ["Dashboard", analyticsView],
};
// [หน้า, หัวข้อกลุ่มในแถบซ้าย]
const NAV = {
  dept: [["request"], ["requisitions"], ["regRequester", "ทะเบียน"], ["regReceiver"], ["departments"], ["analytics", "รายงาน"]],
  admin: [["approve"], ["requisitions"], ["request"], ["items", "คลังสินค้า"], ["movements"],
    ["regRequester", "ทะเบียน"], ["regReceiver"], ["regCentral"], ["departments"], ["users"], ["analytics", "รายงาน"]],
};
const allowed = (key) => !VIEWS[key][2] || me?.role === VIEWS[key][2];
const navLabel = (key) => (typeof VIEWS[key][0] === "function" ? VIEWS[key][0]() : VIEWS[key][0]);
let current = null;

async function show(tab) {
  if (!me) return;
  const nav = (NAV[me.role] || NAV.dept).filter(([k]) => allowed(k));
  if (!nav.some(([k]) => k === tab)) tab = nav[0][0];
  if (current !== tab) window.scrollTo(0, 0);
  current = tab;
  if (dlg.open) dlg.close();
  view.onclick = view.onkeydown = view.onchange = view.oninput = null;
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  $("#tabs").innerHTML = nav.map(([key, head]) => `${head ? `<div class="nav-head">${head}</div>` : ""}<button type="button" data-tab="${key}" ${
    key === tab ? 'aria-current="page"' : ""}>${esc(navLabel(key))}</button>`).join("");
  try {
    await VIEWS[tab][1]();
  } catch (e) {
    if (me) view.innerHTML = `<p class="form-error">โหลดข้อมูลไม่สำเร็จ: ${esc(e.message)}</p>`;
  }
}

// โหลดหน้าปัจจุบันใหม่โดยไม่ปิดกล่องข้อความที่เปิดอยู่
function refresh() {
  if (current && me) VIEWS[current][1]().catch((e) => toast(e.message, true));
}

async function startApp(currentPassword = "") {
  if (me.must_change_password) return passwordScreen(currentPassword);
  document.body.classList.remove("auth");
  try { warehouses = await api("GET", "/warehouses"); } catch { warehouses = []; }
  $("#userbox").innerHTML = `<b>${esc(me.full_name)}</b>
    <small>${esc(me.role === "admin" ? "ผู้ดูแลคลังกลาง (Admin)" : me.department_name || "")}</small>
    <button type="button" id="change-pw">เปลี่ยนรหัสผ่าน</button>
    <button type="button" id="logout">ออกจากระบบ</button>`;
  $("#logout").onclick = logout;
  $("#change-pw").onclick = () => openForm({
    title: "เปลี่ยนรหัสผ่าน",
    fields: passwordFields(),
    submitLabel: "บันทึกรหัสผ่านใหม่",
    onSubmit: async (d) => { me = await savePassword(d); toast("เปลี่ยนรหัสผ่านแล้ว เครื่องอื่นที่เข้าระบบค้างไว้จะถูกออกจากระบบ"); },
  });
  current = null;
  await show(location.hash.slice(1));
}

async function logout() {
  try { await api("POST", "/logout", {}); } catch {}
  me = null;
  current = null;
  resetFlow();
  history.replaceState(null, "", location.pathname + location.search);
  authScreen(false);
}

// ---------- รหัสผ่าน ----------

const MIN_PASSWORD = 8;
const passwordFields = (current = "") => [
  { name: "old_password", label: "รหัสผ่านปัจจุบัน", type: "password", required: true, value: current, autocomplete: "current-password" },
  { name: "new_password", label: "รหัสผ่านใหม่", type: "password", required: true, autocomplete: "new-password",
    hint: `อย่างน้อย ${MIN_PASSWORD} ตัวอักษร มีตัวอักษรปน ห้ามมีเลขบัตรประชาชน` },
  { name: "confirm_password", label: "ยืนยันรหัสผ่านใหม่", type: "password", required: true, autocomplete: "new-password" },
];
async function savePassword(d) {
  const pw = d.new_password || "";
  if (pw.length < MIN_PASSWORD) throw new Error(`รหัสผ่านใหม่ต้องยาวอย่างน้อย ${MIN_PASSWORD} ตัวอักษร`);
  if (/^\d+$/.test(pw)) throw new Error("รหัสผ่านใหม่ต้องมีตัวอักษรปนอยู่ด้วย ไม่ใช่ตัวเลขล้วน");
  if (pw !== d.confirm_password) throw new Error("ยืนยันรหัสผ่านไม่ตรงกัน");
  return api("POST", "/me/password", { old_password: d.old_password, new_password: pw });
}

// บัญชีที่ยังใช้รหัสเริ่มต้น (5 ตัวท้ายของบัตร) ต้องตั้งรหัสใหม่ก่อนใช้งาน
function passwordScreen(current) {
  document.body.classList.add("auth");
  $("#tabs").innerHTML = "";
  $("#userbox").innerHTML = "";
  view.onclick = view.onchange = view.oninput = view.onkeydown = null;
  view.innerHTML = `<div class="login">
    <div class="login-brand"><div class="logo"></div>
      <div class="login-copy"><small>โรงพยาบาลตาพระยา</small><h1>งานบริหารเวชภัณฑ์<br>(คลังกลาง)</h1>
        <p>เพื่อความปลอดภัยของข้อมูล กรุณาตั้งรหัสผ่านของคุณเองก่อนเริ่มใช้งาน</p></div></div>
    <div class="login-main"><form class="login-form" id="pw-form" novalidate>
      <div><h2>ตั้งรหัสผ่านใหม่</h2><span class="sub">${esc(me.full_name)} · รหัสผ่านเริ่มต้น (เลข 5 ตัวท้ายของบัตร) ใช้ได้แค่ครั้งแรก</span></div>
      <div class="fields">${passwordFields(current).map((f) => fieldHtml(f)).join("")}</div>
      <p class="form-error" role="alert" hidden></p>
      <button type="submit" class="btn primary block">บันทึกและเริ่มใช้งาน</button>
      <button type="button" class="link" id="pw-logout" style="justify-self:center">ออกจากระบบ</button>
    </form></div></div>`;
  const form = $("#pw-form");
  const error = $(".form-error", form);
  $(current ? "[name=new_password]" : "input", form).focus();
  $("#pw-logout").onclick = logout;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const submit = $("button[type=submit]", form);
    submit.disabled = true;
    error.hidden = true;
    try {
      me = await savePassword(Object.fromEntries(new FormData(form)));
      toast("ตั้งรหัสผ่านใหม่แล้ว ครั้งต่อไปให้ใช้รหัสผ่านนี้เข้าสู่ระบบ");
      await startApp();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      submit.disabled = false;
    }
  };
}

unauthorized = () => {
  if (!me) return;
  me = null;
  current = null;
  resetFlow();
  if (dlg.open) dlg.close();
  toast("หมดเวลาการใช้งาน กรุณาเข้าสู่ระบบใหม่", true);
  authScreen(false);
};

$("#tabs").onclick = (e) => {
  const b = e.target.closest("[data-tab]");
  if (!b) return;
  if (b.dataset.tab === "request" && current === "request" && flow.step !== "co") flow.step = flow.wh ? "shop" : "wh";
  show(b.dataset.tab);
};
window.addEventListener("hashchange", () => { if (location.hash.slice(1) !== current) show(location.hash.slice(1)); });

(async function boot() {
  try {
    const { needs_setup } = await api("GET", "/setup");
    if (needs_setup) return authScreen(true);
    me = await api("GET", "/me");
    if (!me) throw new Error();
    await startApp();
  } catch {
    me = null;
    authScreen(false);
  }
})();
