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
  toastTimer = setTimeout(() => (el.hidden = true), isError ? 6000 : 2500);
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
    if (b && handlers[b.dataset.act]) handlers[b.dataset.act](b.dataset.id, b);
  };
}

function fieldHtml(f, values = {}) {
  const v = values[f.name] ?? f.value ?? "";
  const attrs = [
    `name="${f.name}"`,
    f.required ? "required" : "",
    f.min != null ? `min="${f.min}"` : "",
    f.type === "number" ? `step="${f.step || "any"}"` : "",
    f.placeholder ? `placeholder="${esc(f.placeholder)}"` : "",
    f.list ? `list="${f.list}"` : "",
    f.autocomplete ? `autocomplete="${f.autocomplete}"` : "",
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

// ---------- ใบเบิก: สถานะ รายละเอียด และการพิมพ์ ----------

const STATUS = {
  pending: ["รออนุมัติ", "warn"],
  approved: ["อนุมัติแล้ว รอจ่าย", "info"],
  issued: ["จ่ายแล้ว", "ok"],
  rejected: ["ไม่อนุมัติ", "bad"],
  cancelled: ["ยกเลิก", "muted"],
};
const statusBadge = (s) => badge(...STATUS[s]);

function infoGrid(doc) {
  const cell = (label, value) => `<div><small>${label}</small><div>${value}</div></div>`;
  const person = (name, ts) => (name ? `${esc(name)}${ts ? ` <small>${when(ts)}</small>` : ""}` : "-");
  return `<div class="info-grid">
    ${cell("หน่วยงาน", esc(doc.department_name))}
    ${cell("วันที่ขอเบิก", when(doc.created_at))}
    ${cell("ผู้เบิก", esc(doc.requester_name))}
    ${cell(doc.status === "rejected" ? "ผู้พิจารณา" : "ผู้อนุมัติ", person(doc.approver_name, doc.approved_at))}
    ${cell("ผู้จ่าย", person(doc.issuer_name, doc.issued_at))}
    ${cell("ผู้รับ", esc(doc.receiver_name || "-"))}
  </div>
  ${doc.note ? `<p class="hint"><b>หมายเหตุ:</b> ${esc(doc.note)}</p>` : ""}
  ${doc.reject_reason ? `<p class="form-error"><b>เหตุผลที่ไม่อนุมัติ:</b> ${esc(doc.reject_reason)}</p>` : ""}`;
}

// mode: view | approve | issue
function linesTable(doc, mode) {
  const admin = me.role === "admin";
  const input = (line, field, value, max) =>
    `<input class="qty-input" type="number" step="any" min="0" max="${max}" data-line="${line.id}" data-field="${field}" value="${value}" required>`;
  const headers = ["#", "รหัส", "รายการ", "หน่วย", ["ขอเบิก", "num"], ["อนุมัติ", "num"], ["จ่ายจริง", "num"]];
  if (admin && doc.status !== "issued") headers.push(["คงเหลือในคลัง", "num"]);
  return table(headers, doc.lines.map((l, i) => {
    const approved = mode === "approve" ? input(l, "qty_approved", l.qty_requested, l.qty_requested) : num(l.qty_approved);
    const issued = mode === "issue" ? input(l, "qty_issued", Math.min(l.qty_approved, l.stock), l.qty_approved) : num(l.qty_issued);
    const cells = [i + 1, esc(l.code), esc(l.name), esc(l.unit), [num(l.qty_requested), "num"], [approved, "num"], [issued, "num"]];
    if (admin && doc.status !== "issued") {
      const need = mode === "issue" || doc.status === "approved" ? l.qty_approved : l.qty_requested;
      cells.push([`<span class="${l.stock < need ? "minus" : ""}">${num(l.stock)}</span>`, "num"]);
    }
    return cells;
  }), "ไม่มีรายการ");
}

async function openRequisition(id, mode = "view") {
  let doc;
  try { doc = await api("GET", `/requisitions/${id}`); } catch (e) { return toast(e.message, true); }
  const admin = me.role === "admin";
  const title = `ใบเบิก ${esc(doc.doc_no)} ${statusBadge(doc.status)}`;
  let body = infoGrid(doc) + linesTable(doc, mode);
  let submit = null;

  if (mode === "approve") {
    body += `<div class="fields step">${fieldHtml({ name: "approver_name", label: "ชื่อผู้อนุมัติ", required: true, value: me.full_name })}</div>`;
    submit = "ยืนยันอนุมัติ";
  } else if (mode === "issue") {
    body += `<div class="fields step two">
      ${fieldHtml({ name: "issuer_name", label: "ชื่อผู้จ่าย", required: true, value: me.full_name })}
      ${fieldHtml({ name: "receiver_name", label: "ชื่อผู้รับของ", required: true, value: doc.requester_name, hint: "คนที่มารับของจากคลัง" })}
    </div>`;
    submit = "ยืนยันจ่ายของ (ตัดสต็อก)";
  } else {
    const buttons = [];
    if (admin && doc.status === "pending") buttons.push(btn("approve", "อนุมัติ", "", "primary"), btn("reject", "ไม่อนุมัติ", "", "danger"));
    if (admin && doc.status === "approved") buttons.push(btn("issue", "จ่ายของ", "", "primary"), btn("reject", "ไม่อนุมัติ", "", "danger"));
    if (doc.status === "pending") buttons.push(btn("cancel", "ยกเลิกใบเบิก", "", "danger"));
    buttons.push(btn("print", "พิมพ์ใบเบิก"));
    body += `<div class="doc-actions">${buttons.join("")}</div>`;
  }

  dlg.className = "wide";
  dlg.innerHTML = dialogShell(title, body, submit, mode === "view" ? "ปิด" : "ย้อนกลับ");
  const form = wireDialog(async (d, f) => {
    const lines = $$(".qty-input", f).map((i) => ({ line_id: i.dataset.line, [i.dataset.field]: i.value }));
    if (mode === "approve") {
      await api("POST", `/requisitions/${id}/approve`, { approver_name: d.approver_name, lines });
      toast("อนุมัติแล้ว");
    } else {
      await api("POST", `/requisitions/${id}/issue`, { issuer_name: d.issuer_name, receiver_name: d.receiver_name, lines });
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
    if (act === "cancel") {
      if (!confirm(`ยกเลิกใบเบิก ${doc.doc_no}?`)) return;
      try { await api("POST", `/requisitions/${id}/cancel`, {}); toast("ยกเลิกใบเบิกแล้ว"); dlg.close(); refresh(); }
      catch (err) { toast(err.message, true); }
    }
    if (act === "reject") {
      openForm({
        title: `ไม่อนุมัติใบเบิก ${doc.doc_no}`,
        fields: [
          { name: "approver_name", label: "ชื่อผู้พิจารณา", required: true, value: me.full_name },
          { name: "reason", label: "เหตุผล", required: true, placeholder: "เช่น ของหมด ให้เบิกใหม่เดือนหน้า" },
        ],
        submitLabel: "ยืนยันไม่อนุมัติ",
        onSubmit: async (d) => { await api("POST", `/requisitions/${id}/reject`, d); toast("บันทึกไม่อนุมัติแล้ว"); refresh(); },
      });
    }
  };
}

function printRequisition(doc) {
  const sign = (role, name, ts) => `<div class="sign">
      <div class="sign-line">ลงชื่อ ....................................... ${role}</div>
      <div>( ${esc(name || "......................................")} )</div>
      <div>วันที่ ${ts ? when(ts, false) : "......../......../........"}</div>
    </div>`;
  $("#print").innerHTML = `
    <h1>ใบเบิกพัสดุ</h1>
    <p class="center">โรงพยาบาลตาพระยา</p>
    <div class="print-head">
      <div><b>เลขที่:</b> ${esc(doc.doc_no)}</div>
      <div><b>วันที่:</b> ${when(doc.created_at, false)}</div>
      <div><b>หน่วยงาน:</b> ${esc(doc.department_name)}</div>
      <div><b>สถานะ:</b> ${esc(STATUS[doc.status][0])}</div>
    </div>
    <table>
      <thead><tr><th>ลำดับ</th><th>รหัส</th><th>รายการ</th><th>หน่วย</th><th class="num">ขอเบิก</th><th class="num">อนุมัติ</th><th class="num">จ่ายจริง</th></tr></thead>
      <tbody>${doc.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.code)}</td><td>${esc(l.name)}</td><td>${esc(l.unit)}</td>
        <td class="num">${num(l.qty_requested)}</td><td class="num">${l.qty_approved == null ? "" : num(l.qty_approved)}</td>
        <td class="num">${l.qty_issued == null ? "" : num(l.qty_issued)}</td></tr>`).join("")}</tbody>
    </table>
    ${doc.note ? `<p><b>หมายเหตุ:</b> ${esc(doc.note)}</p>` : ""}
    <div class="signs">
      ${sign("ผู้เบิก", doc.requester_name, doc.created_at)}
      ${sign("ผู้อนุมัติ", doc.status === "rejected" ? "" : doc.approver_name, doc.status === "rejected" ? null : doc.approved_at)}
      ${sign("ผู้จ่าย", doc.issuer_name, doc.issued_at)}
      ${sign("ผู้รับ", doc.receiver_name, doc.issued_at)}
    </div>`;
  window.print();
}

// ---------- เบิกสินค้า (ตะกร้า) ----------

const cart = new Map(); // item_id -> { item, qty }

async function requestView() {
  const [items, departments] = await Promise.all([
    api("GET", "/items"),
    me.role === "admin" ? api("GET", "/departments") : Promise.resolve([]),
  ]);
  const byId = new Map(items.map((i) => [String(i.id), i]));
  for (const [id, entry] of cart) {
    if (!byId.has(String(id))) cart.delete(id); else entry.item = byId.get(String(id));
  }
  const categories = [...new Set(items.map((i) => i.category).filter(Boolean))].sort();

  view.innerHTML = `<div class="request-layout">
    <section>
      <div class="toolbar">
        <h2>เลือกสินค้าที่จะเบิก</h2>
        <input type="search" id="q" placeholder="ค้นหารหัสหรือชื่อสินค้า">
        ${categories.length ? `<select id="cat">${option("", "ทุกหมวดหมู่")}${categories.map((c) => option(c, c)).join("")}</select>` : ""}
      </div>
      <div class="list" id="catalog"></div>
    </section>
    <aside class="card cart" id="cart"></aside>
  </div>`;

  const drawCatalog = () => {
    const q = $("#q").value.trim().toLowerCase();
    const cat = $("#cat")?.value || "";
    const shown = items.filter((i) => (!q || `${i.code} ${i.name}`.toLowerCase().includes(q)) && (!cat || i.category === cat));
    $("#catalog").innerHTML = table(
      ["รหัส", "รายการ", "หมวดหมู่", ["คงเหลือ", "num"], "จำนวน / หน่วย", ""],
      shown.map((i) => [
        esc(i.code), esc(i.name), esc(i.category || "-"),
        [`<span class="${i.qty <= 0 ? "minus" : ""}">${num(i.qty)}</span>`, "num"],
        `<span class="qty-unit"><input type="number" class="pick-qty" data-id="${i.id}" min="0" step="any" value="${cart.get(i.id)?.qty ?? ""}" placeholder="0" aria-label="จำนวน ${esc(i.name)}"><span>${esc(i.unit)}</span></span>`,
        actions(btn("add", cart.has(i.id) ? "แก้จำนวน" : "เพิ่ม", i.id, cart.has(i.id) ? "" : "primary")),
      ]),
      items.length ? "ไม่พบสินค้าที่ค้นหา" : "ยังไม่มีสินค้าในคลัง");
  };

  const drawCart = () => {
    const entries = [...cart.values()];
    $("#cart").innerHTML = `<h2>ใบเบิก <small>(${entries.length} รายการ)</small></h2>
      ${entries.length ? `<ul class="cart-lines">${entries.map(({ item, qty }) => `<li>
          <div><b>${esc(item.name)}</b><br><small>${esc(item.code)}</small></div>
          <span class="qty-unit"><input type="number" class="cart-qty" data-id="${item.id}" min="0" step="any" value="${qty}" aria-label="จำนวน ${esc(item.name)}"><span>${esc(item.unit)}</span></span>
          <button type="button" class="btn small danger" data-act="remove" data-id="${item.id}" aria-label="ลบ ${esc(item.name)}">×</button>
        </li>`).join("")}</ul>` : `<p class="empty">ยังไม่ได้เลือกสินค้า ใส่จำนวนแล้วกด "เพิ่ม"</p>`}
      <form id="req-form" class="fields">
        ${me.role === "admin" ? fieldHtml({ name: "department_id", label: "หน่วยงานที่เบิก", type: "select", required: true,
          options: [["", "— เลือกหน่วยงาน —"], ...departments.filter((d) => d.active).map((d) => [d.id, d.name])] }) :
          `<div class="field"><span>หน่วยงาน</span><div>${esc(me.department_name || "-")}</div></div>`}
        ${fieldHtml({ name: "requester_name", label: "ชื่อผู้เบิก", required: true, value: me.full_name })}
        ${fieldHtml({ name: "note", label: "หมายเหตุ", placeholder: "เช่น ใช้สำหรับเดือนตุลาคม" })}
        <button type="submit" class="btn primary block" ${entries.length ? "" : "disabled"}>ส่งใบเบิก</button>
      </form>`;
    $("#req-form").onsubmit = submitCart;
  };

  const setQty = (id, value) => {
    const qty = Number(value);
    if (!value || !(qty > 0)) cart.delete(id);
    else cart.set(id, { item: byId.get(String(id)), qty });
  };

  async function submitCart(e) {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    const submit = $("button[type=submit]", e.target);
    submit.disabled = true;
    try {
      const doc = await api("POST", "/requisitions", {
        ...d, lines: [...cart.values()].map(({ item, qty }) => ({ item_id: item.id, qty })),
      });
      cart.clear();
      toast(`ส่งใบเบิก ${doc.doc_no} แล้ว`);
      show("requisitions");
      openRequisition(doc.id);
    } catch (err) {
      toast(err.message, true);
      submit.disabled = false;
    }
  }

  $("#q").oninput = drawCatalog;
  if ($("#cat")) $("#cat").onchange = drawCatalog;
  view.onkeydown = (e) => {
    if (e.key === "Enter" && e.target.matches(".pick-qty")) {
      e.preventDefault();
      e.target.closest("tr").querySelector("[data-act=add]").click();
    }
  };
  view.onchange = (e) => {
    if (e.target.matches(".cart-qty")) { setQty(Number(e.target.dataset.id), e.target.value); drawCart(); drawCatalog(); }
  };
  bind({
    add: (id, b) => {
      const input = b.closest("tr").querySelector(".pick-qty");
      if (!(Number(input.value) > 0)) { input.focus(); return toast("ใส่จำนวนที่จะเบิกก่อน", true); }
      setQty(Number(id), input.value);
      drawCart(); drawCatalog();
      toast(`เพิ่ม ${byId.get(id).name} แล้ว`);
    },
    remove: (id) => { cart.delete(Number(id)); drawCart(); drawCatalog(); },
  });
  drawCatalog();
  drawCart();
}

// ---------- รายการใบเบิก ----------

async function requisitionsView() {
  const admin = me.role === "admin";
  let saved = null;
  try { saved = sessionStorage.getItem("req-status"); } catch {}
  saved ??= admin ? "pending" : "";
  view.innerHTML = `<div class="toolbar">
      <h2>${admin ? "ใบเบิกทั้งหมด" : `ใบเบิกของ ${esc(me.department_name || "")}`}</h2>
      <select id="status">${option("", "ทุกสถานะ", saved)}${Object.entries(STATUS).map(([k, [t]]) => option(k, t, saved)).join("")}</select>
      <button class="btn primary" data-act="new">+ เบิกสินค้า</button>
    </div><div class="list" id="list"></div>`;
  const load = async () => {
    const status = $("#status").value;
    try { sessionStorage.setItem("req-status", status); } catch {}
    const list = await api("GET", `/requisitions${status ? "?status=" + status : ""}`);
    $("#list").innerHTML = table(
      ["เลขที่", "วันที่", ...(admin ? ["หน่วยงาน"] : []), "ผู้เบิก", ["รายการ", "num"], "สถานะ", ""],
      list.map((r) => [
        `<b>${esc(r.doc_no)}</b>`, when(r.created_at), ...(admin ? [esc(r.department_name)] : []),
        esc(r.requester_name), [num(r.line_count), "num"], statusBadge(r.status),
        actions(btn("open", admin && r.status === "pending" ? "พิจารณา" : admin && r.status === "approved" ? "จ่ายของ" : "ดู", r.id,
          admin && ["pending", "approved"].includes(r.status) ? "primary" : "")),
      ]),
      status ? `ไม่มีใบเบิกสถานะ "${STATUS[status][0]}"` : "ยังไม่มีใบเบิก");
  };
  $("#status").onchange = () => load().catch((e) => toast(e.message, true));
  bind({ open: (id) => openRequisition(id), new: () => show("request") });
  await load();
}

// ---------- สินค้าและสต็อก (ผู้ดูแล) ----------

async function itemsView() {
  const items = await api("GET", "/items?all=1");
  const units = [...new Set(items.map((i) => i.unit))].sort();
  const categories = [...new Set(items.map((i) => i.category).filter(Boolean))].sort();
  view.innerHTML = `<div class="toolbar">
      <h2>สินค้าและสต็อก</h2>
      <input type="search" id="q" placeholder="ค้นหารหัสหรือชื่อ">
      <button class="btn primary" data-act="new">+ เพิ่มสินค้า</button>
    </div>
    <datalist id="units">${units.map((u) => `<option value="${esc(u)}">`).join("")}</datalist>
    <datalist id="cats">${categories.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
    <div class="list" id="list"></div>`;
  const state = (i) => !i.active ? badge("งดเบิก", "muted")
    : i.min_qty > 0 && i.qty <= i.min_qty ? badge("ใกล้หมด", "warn") : badge("ปกติ", "ok");
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    $("#list").innerHTML = table(
      ["รหัส", "รายการ", "หมวดหมู่", "หน่วย", ["คงเหลือ", "num"], ["จุดสั่งซื้อ", "num"], "สถานะ", ""],
      items.filter((i) => !q || `${i.code} ${i.name}`.toLowerCase().includes(q)).map((i) => [
        esc(i.code), esc(i.name), esc(i.category || "-"), esc(i.unit), [num(i.qty), "num"], [num(i.min_qty), "num"], state(i),
        actions(btn("adjust", "รับเข้า/ปรับ", i.id), btn("edit", "แก้ไข", i.id), btn("history", "ประวัติ", i.id)),
      ]),
      q ? "ไม่พบสินค้าที่ค้นหา" : 'ยังไม่มีสินค้า กด "+ เพิ่มสินค้า" เพื่อเริ่ม');
  };
  $("#q").oninput = draw;
  draw();

  const byId = (id) => items.find((i) => String(i.id) === String(id));
  const fields = [
    { name: "code", label: "รหัสสินค้า", required: true, placeholder: "เช่น MED-0001" },
    { name: "name", label: "ชื่อสินค้า", required: true, placeholder: "เช่น ถุงมือยาง ไซส์ M" },
    { name: "category", label: "หมวดหมู่", list: "cats", placeholder: "เช่น วัสดุการแพทย์, วัสดุสำนักงาน" },
    { name: "unit", label: "หน่วยนับ", required: true, list: "units", placeholder: "เช่น กล่อง, ชิ้น, ขวด, รีม" },
    { name: "min_qty", label: "จุดสั่งซื้อ", type: "number", min: 0, value: 0, hint: "คงเหลือเท่านี้หรือน้อยกว่าจะแจ้งเตือนว่าใกล้หมด" },
  ];
  bind({
    new: () => openForm({
      title: "เพิ่มสินค้า",
      fields: [...fields, { name: "initial_qty", label: "ยอดคงเหลือตอนนี้", type: "number", min: 0 }],
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
  view.innerHTML = `<div class="toolbar"><h2>ประวัติสต็อก</h2><input type="search" id="q" placeholder="ค้นหาสินค้า เลขที่ใบเบิก หรือหมายเหตุ"></div><div class="list" id="list"></div>`;
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    $("#list").innerHTML = movementTable(list.filter((m) => !q || `${m.code} ${m.name} ${m.reason}`.toLowerCase().includes(q)));
  };
  $("#q").oninput = draw;
  bind({});
  draw();
}

// ---------- หน่วยงานและผู้ใช้ (ผู้ดูแล) ----------

async function departmentsView() {
  const [departments, users] = await Promise.all([api("GET", "/departments"), api("GET", "/users")]);
  view.innerHTML = `<div class="toolbar"><h2>หน่วยงาน</h2><button class="btn primary" data-act="new">+ เพิ่มหน่วยงาน</button></div>
    <div class="list">${table(["หน่วยงาน", ["ผู้ใช้", "num"], "สถานะ", ""],
      departments.map((d) => [esc(d.name), [num(users.filter((u) => u.department_id === d.id).length), "num"],
        d.active ? badge("ใช้งาน", "ok") : badge("ปิดใช้งาน", "muted"), actions(btn("edit", "แก้ไข", d.id))]),
      'ยังไม่มีหน่วยงาน กด "+ เพิ่มหน่วยงาน" เช่น ห้องฉุกเฉิน, ผู้ป่วยใน, ทันตกรรม')}</div>`;
  const form = (d = { active: 1 }) => openForm({
    title: d.id ? "แก้ไขหน่วยงาน" : "เพิ่มหน่วยงาน",
    fields: [
      { name: "name", label: "ชื่อหน่วยงาน", required: true, placeholder: "เช่น งานผู้ป่วยนอก (OPD)" },
      { name: "active", label: "สถานะ", type: "select", options: [["1", "ใช้งาน"], ["0", "ปิดใช้งาน"]] },
    ],
    values: { ...d, active: String(d.active) },
    onSubmit: async (v) => {
      await api(d.id ? "PUT" : "POST", d.id ? `/departments/${d.id}` : "/departments", { ...v, active: v.active === "1" });
      toast("บันทึกแล้ว"); refresh();
    },
  });
  bind({ new: () => form(), edit: (id) => form(departments.find((d) => String(d.id) === id)) });
}

async function usersView() {
  const [users, departments] = await Promise.all([api("GET", "/users"), api("GET", "/departments")]);
  view.innerHTML = `<div class="toolbar"><h2>ผู้ใช้</h2><button class="btn primary" data-act="new">+ เพิ่มผู้ใช้</button></div>
    <p class="hint">บัญชี <b>หน่วยงาน</b> เบิกสินค้าและดูได้เฉพาะใบเบิกของหน่วยงานตัวเอง บัญชี <b>ผู้ดูแลคลัง</b> อนุมัติ จ่ายของ และจัดการสต็อกได้</p>
    <div class="list">${table(["ชื่อผู้ใช้", "ชื่อ-นามสกุล", "สิทธิ์", "หน่วยงาน", "สถานะ", ""],
      users.map((u) => [esc(u.username), esc(u.full_name), u.role === "admin" ? badge("ผู้ดูแลคลัง", "info") : "หน่วยงาน",
        esc(u.department_name || "-"), u.active ? badge("ใช้งาน", "ok") : badge("ปิดใช้งาน", "muted"),
        actions(btn("edit", "แก้ไข", u.id))]), "ยังไม่มีผู้ใช้")}</div>`;
  const deptOptions = [["", "— ไม่ระบุ —"], ...departments.map((d) => [d.id, d.name + (d.active ? "" : " (ปิดใช้งาน)")])];
  const form = (u) => openForm({
    title: u ? `แก้ไขผู้ใช้ ${u.username}` : "เพิ่มผู้ใช้",
    fields: [
      ...(u ? [] : [{ name: "username", label: "ชื่อผู้ใช้ (ใช้ล็อกอิน)", required: true, placeholder: "เช่น opd01", autocomplete: "off",
        hint: "ภาษาอังกฤษ ตัวเลข . _ - เท่านั้น" }]),
      { name: "full_name", label: "ชื่อ-นามสกุล", required: true },
      { name: "role", label: "สิทธิ์", type: "select", options: [["dept", "หน่วยงาน (เบิกสินค้า)"], ["admin", "ผู้ดูแลคลัง"]] },
      { name: "department_id", label: "หน่วยงาน", type: "select", options: deptOptions, hint: "จำเป็นสำหรับสิทธิ์หน่วยงาน" },
      ...(u ? [{ name: "active", label: "สถานะ", type: "select", options: [["1", "ใช้งาน"], ["0", "ปิดใช้งาน"]] }] : []),
      { name: "password", label: u ? "ตั้งรหัสผ่านใหม่" : "รหัสผ่าน", type: "password", required: !u, autocomplete: "new-password",
        hint: u ? "เว้นว่างถ้าไม่เปลี่ยน" : "อย่างน้อย 6 ตัวอักษร" },
    ],
    values: u ? { ...u, active: String(u.active) } : { role: "dept" },
    onSubmit: async (v) => {
      await api(u ? "PUT" : "POST", u ? `/users/${u.id}` : "/users", { ...v, active: v.active !== "0" });
      toast("บันทึกแล้ว"); refresh();
    },
  });
  bind({ new: () => form(), edit: (id) => form(users.find((u) => String(u.id) === id)) });
}

// ---------- ภาพรวม (ผู้ดูแล) ----------

async function dashboardView() {
  const s = await api("GET", "/summary");
  const c = s.status_counts;
  const stat = (label, value, tab, status, cls = "") =>
    `<button class="stat ${cls}" data-act="go" data-id="${tab}" data-status="${status ?? ""}"><b>${num(value || 0)}</b><span>${label}</span></button>`;
  view.innerHTML = `
    <section class="stats">
      ${stat("ใบเบิกรออนุมัติ", c.pending, "requisitions", "pending", c.pending ? "attn" : "")}
      ${stat("อนุมัติแล้ว รอจ่าย", c.approved, "requisitions", "approved", c.approved ? "attn" : "")}
      ${stat("สินค้าใกล้หมด", s.low_stock.length, "items")}
      ${stat("สินค้าที่เปิดให้เบิก", s.item_count, "items")}
      ${stat("หน่วยงาน", s.department_count, "departments")}
    </section>
    <section class="card"><h2>ใบเบิกที่ต้องดำเนินการ</h2>${table(["เลขที่", "วันที่", "หน่วยงาน", "ผู้เบิก", "สถานะ", ""],
      s.waiting.map((r) => [`<b>${esc(r.doc_no)}</b>`, when(r.created_at), esc(r.department_name), esc(r.requester_name),
        statusBadge(r.status), actions(btn("open", r.status === "pending" ? "พิจารณา" : "จ่ายของ", r.id, "primary"))]),
      "ไม่มีใบเบิกค้าง")}</section>
    <div class="grid2">
      <section class="card"><h2>สินค้าใกล้หมด</h2>${table(["รหัส", "รายการ", ["คงเหลือ", "num"], ["จุดสั่งซื้อ", "num"]],
        s.low_stock.map((i) => [esc(i.code), esc(i.name), [`${num(i.qty)} ${esc(i.unit)}`, "num"], [num(i.min_qty), "num"]]),
        "สต็อกปกติทุกรายการ")}</section>
      <section class="card"><h2>จ่ายออกมากที่สุด 30 วัน</h2>${table(["รหัส", "รายการ", ["จ่ายออก", "num"]],
        s.top_items.map((i) => [esc(i.code), esc(i.name), [`${num(i.issued)} ${esc(i.unit)}`, "num"]]),
        "ยังไม่มีการจ่ายของใน 30 วันที่ผ่านมา")}</section>
    </div>`;
  bind({
    go: (tab, b) => {
      if (b.dataset.status) try { sessionStorage.setItem("req-status", b.dataset.status); } catch {}
      show(tab);
    },
    open: (id) => openRequisition(id),
  });
}

// ---------- เข้าสู่ระบบ ----------

function authScreen(setupMode) {
  document.body.classList.add("auth");
  $("#tabs").innerHTML = "";
  $("#userbox").innerHTML = "";
  view.onclick = null;
  view.innerHTML = `<form class="card auth-card" id="auth-form">
      <h2>${setupMode ? "ตั้งค่าระบบครั้งแรก" : "เข้าสู่ระบบ"}</h2>
      ${setupMode ? `<p class="hint">สร้างบัญชีผู้ดูแลคลังคนแรก จากนั้นเพิ่มหน่วยงานและบัญชีผู้ใช้ของแต่ละหน่วยงานได้ในเมนู "ผู้ใช้"</p>` : ""}
      <div class="fields">
        ${setupMode ? fieldHtml({ name: "full_name", label: "ชื่อ-นามสกุล", required: true }) : ""}
        ${fieldHtml({ name: "username", label: "ชื่อผู้ใช้", required: true, autocomplete: "username" })}
        ${fieldHtml({ name: "password", label: "รหัสผ่าน", type: "password", required: true,
          autocomplete: setupMode ? "new-password" : "current-password", hint: setupMode ? "อย่างน้อย 6 ตัวอักษร" : "" })}
      </div>
      <p class="form-error" hidden></p>
      <button type="submit" class="btn primary block">${setupMode ? "สร้างบัญชีและเข้าสู่ระบบ" : "เข้าสู่ระบบ"}</button>
    </form>`;
  const form = $("#auth-form");
  $("input", form).focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const error = $(".form-error", form);
    error.hidden = true;
    try {
      me = await api("POST", setupMode ? "/setup" : "/login", Object.fromEntries(new FormData(form)));
      startApp();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  };
}

function changePassword() {
  openForm({
    title: "เปลี่ยนรหัสผ่าน",
    fields: [
      { name: "old_password", label: "รหัสผ่านเดิม", type: "password", required: true, autocomplete: "current-password" },
      { name: "new_password", label: "รหัสผ่านใหม่", type: "password", required: true, autocomplete: "new-password", hint: "อย่างน้อย 6 ตัวอักษร" },
    ],
    onSubmit: async (d) => { await api("POST", "/me/password", d); toast("เปลี่ยนรหัสผ่านแล้ว"); },
  });
}

// ---------- เมนูและการสลับหน้า ----------

const VIEWS = {
  dashboard: ["ภาพรวม", dashboardView, "admin"],
  requisitions: ["ใบเบิก", requisitionsView],
  request: ["เบิกสินค้า", requestView],
  items: ["สินค้า/สต็อก", itemsView, "admin"],
  movements: ["ประวัติสต็อก", movementsView, "admin"],
  departments: ["หน่วยงาน", departmentsView, "admin"],
  users: ["ผู้ใช้", usersView, "admin"],
};
const allowed = (key) => !VIEWS[key][2] || me?.role === VIEWS[key][2];
let current = null;

async function show(tab) {
  if (!me) return;
  if (!VIEWS[tab] || !allowed(tab)) tab = me.role === "admin" ? "dashboard" : "request";
  current = tab;
  if (dlg.open) dlg.close();
  view.onkeydown = view.onchange = null;
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  $("#tabs").innerHTML = Object.entries(VIEWS).filter(([k]) => allowed(k))
    .map(([key, [text]]) => `<button data-tab="${key}" ${key === tab ? 'aria-current="page"' : ""}>${text}</button>`).join("");
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

function startApp() {
  document.body.classList.remove("auth");
  $("#userbox").innerHTML = `<span><b>${esc(me.full_name)}</b><small>${esc(me.role === "admin" ? "ผู้ดูแลคลัง" : me.department_name || "")}</small></span>
    <button class="btn small" id="pw">เปลี่ยนรหัสผ่าน</button>
    <button class="btn small" id="logout">ออกจากระบบ</button>`;
  $("#pw").onclick = changePassword;
  $("#logout").onclick = async () => {
    try { await api("POST", "/logout", {}); } catch {}
    me = null;
    cart.clear();
    authScreen(false);
  };
  show(location.hash.slice(1));
}

unauthorized = () => {
  if (!me) return;
  me = null;
  if (dlg.open) dlg.close();
  toast("หมดเวลาการใช้งาน กรุณาเข้าสู่ระบบใหม่", true);
  authScreen(false);
};

$("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) show(b.dataset.tab); };
window.addEventListener("hashchange", () => { if (location.hash.slice(1) !== current) show(location.hash.slice(1)); });

(async function boot() {
  try {
    const { needs_setup } = await api("GET", "/setup");
    if (needs_setup) return authScreen(true);
    me = await api("GET", "/me");
    startApp();
  } catch {
    authScreen(false);
  }
})();
