"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const view = $("#view");
const dlg = $("#dlg");

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v, digits = 2) =>
  v == null || v === "" ? "-" : Number(v).toLocaleString("th-TH", { maximumFractionDigits: digits });
const when = (ts) => (ts ? esc(ts.replace("T", " ").slice(0, 16)) : "-");

async function api(method, path, body) {
  const res = await fetch("/api" + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = (res.headers.get("Content-Type") || "").includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || `เกิดข้อผิดพลาด (${res.status})`);
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
  const th = headers.map((h) => {
    const [text, cls] = Array.isArray(h) ? h : [h, ""];
    return `<th class="${cls}">${esc(text)}</th>`;
  });
  return `<div class="table-wrap"><table><thead><tr>${th.join("")}</tr></thead><tbody>${rowsHtml
    .map((cells) => `<tr>${cells.map((c) => (Array.isArray(c) ? `<td class="${c[1]}">${c[0]}</td>` : `<td>${c}</td>`)).join("")}</tr>`)
    .join("")}</tbody></table></div>`;
}

function buttons(list, id) {
  return [
    list.map(([act, text, cls = ""]) => `<button class="btn small ${cls}" data-act="${act}" data-id="${id}">${esc(text)}</button>`).join(""),
    "actions",
  ];
}

function bind(handlers) {
  view.onclick = (e) => {
    const btn = e.target.closest("[data-act]");
    if (btn && handlers[btn.dataset.act]) handlers[btn.dataset.act](btn.dataset.id, btn);
  };
}

const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;

function lifeBar(t) {
  if (!t.life_minutes) return `${num(t.used_minutes, 0)} นาที <small>(ยังไม่ตั้งอายุ)</small>`;
  const pct = (t.used_minutes / t.life_minutes) * 100;
  const cls = pct >= 100 ? "bad" : pct >= 80 ? "warn" : "ok";
  return `<div class="bar ${cls}"><i style="width:${Math.min(100, pct)}%"></i></div>
    <small>${num(t.used_minutes, 0)} / ${num(t.life_minutes, 0)} นาที (${num(pct, 0)}%)</small>`;
}

function fieldHtml(f, values) {
  const v = values[f.name] ?? f.value ?? "";
  const attrs = [
    `name="${f.name}"`,
    f.required ? "required" : "",
    f.min != null ? `min="${f.min}"` : "",
    f.type === "number" ? `step="${f.step || "any"}"` : "",
    f.placeholder ? `placeholder="${esc(f.placeholder)}"` : "",
  ].join(" ");
  let input;
  if (f.type === "select") {
    input = `<select ${attrs}>${f.options
      .map(([val, text]) => `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(text)}</option>`)
      .join("")}</select>`;
  } else {
    input = `<input type="${f.type || "text"}" value="${esc(v)}" ${attrs}>`;
  }
  return `<label class="field"><span>${esc(f.label)}${f.required ? " *" : ""}</span>${input}${
    f.hint ? `<small>${esc(f.hint)}</small>` : ""}</label>`;
}

function dialogShell(title, inner, submitLabel = "บันทึก") {
  return `<form class="form">
    <h2>${esc(title)}</h2>
    ${inner}
    <p class="form-error" hidden></p>
    <div class="actions">
      <button type="button" class="btn" data-cancel>ยกเลิก</button>
      <button type="submit" class="btn primary">${esc(submitLabel)}</button>
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
    submit.disabled = true;
    error.hidden = true;
    try {
      await onSubmit(Object.fromEntries(new FormData(form)), form);
      dlg.close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  };
  dlg.showModal();
  return form;
}

function openForm({ title, fields, values = {}, submitLabel, intro = "", onSubmit }) {
  dlg.className = "";
  dlg.innerHTML = dialogShell(title, `${intro}<div class="fields">${fields.map((f) => fieldHtml(f, values)).join("")}</div>`, submitLabel);
  const form = wireDialog(onSubmit);
  $("input, select", form)?.focus();
}

// ---------- สต็อกสามประเภท: วัตถุดิบ / ดอกกัด / สินค้าสำเร็จรูป ----------

const RES = {
  materials: {
    label: "วัตถุดิบ",
    stock: "qty",
    unit: (i) => i.unit,
    fields: [
      { name: "code", label: "รหัส", required: true, placeholder: "เช่น AL-6061-10" },
      { name: "name", label: "ชื่อ", required: true, placeholder: "เช่น แผ่นอะลูมิเนียม 6061 หนา 10 มม." },
      { name: "unit", label: "หน่วย", value: "ชิ้น", placeholder: "ชิ้น, แผ่น, กก., เมตร" },
      { name: "min_qty", label: "จุดสั่งซื้อขั้นต่ำ", type: "number", min: 0, value: 0, hint: "เหลือเท่านี้หรือน้อยกว่าจะแจ้งเตือนว่าใกล้หมด" },
    ],
    headers: ["รหัส", "ชื่อ", ["คงเหลือ", "num"], ["ขั้นต่ำ", "num"], "สถานะ", ""],
    row: (i) => [
      esc(i.code), esc(i.name), [`${num(i.qty)} ${esc(i.unit)}`, "num"], [num(i.min_qty), "num"],
      i.min_qty > 0 && i.qty <= i.min_qty ? badge("ใกล้หมด", "warn") : badge("ปกติ", "ok"),
      buttons([["adjust", "รับ/เบิก"], ["edit", "แก้ไข"], ["del", "ลบ", "danger"]], i.id),
    ],
  },
  tools: {
    label: "ดอกกัด",
    stock: "spare_qty",
    step: 1,
    unit: () => "ดอก",
    fields: [
      { name: "code", label: "รหัส", required: true, placeholder: "เช่น EM-6-2F" },
      { name: "name", label: "ชื่อ", required: true, placeholder: "เช่น ดอกเอ็นมิล 6 มม. 2 ฟัน" },
      { name: "tool_number", label: "เบอร์ทูลในเครื่อง (T)", type: "number", step: 1, min: 0, hint: "ใช้จับคู่กับคำสั่ง T ในไฟล์ G-code อัตโนมัติ" },
      { name: "diameter", label: "เส้นผ่านศูนย์กลาง (มม.)", type: "number", min: 0 },
      { name: "life_minutes", label: "อายุการใช้งาน (นาทีตัด)", type: "number", min: 0, value: 0, hint: "ใช้ถึง 80% จะเตือน ใส่ 0 ถ้าไม่ต้องการติดตาม" },
    ],
    headers: ["รหัส", "ชื่อ", "T", ["Ø", "num"], "อายุที่ใช้ไป", ["ดอกสำรอง", "num"], ""],
    row: (t) => [
      esc(t.code), esc(t.name), t.tool_number != null ? `T${t.tool_number}` : "-", [t.diameter ? num(t.diameter) : "-", "num"],
      lifeBar(t), [num(t.spare_qty, 0), "num"],
      buttons([["replace", "เปลี่ยนดอก"], ["adjust", "รับ/เบิก"], ["edit", "แก้ไข"], ["del", "ลบ", "danger"]], t.id),
    ],
  },
  products: {
    label: "สินค้าสำเร็จรูป",
    stock: "qty",
    unit: (i) => i.unit,
    fields: [
      { name: "code", label: "รหัส", required: true, placeholder: "เช่น BRK-001" },
      { name: "name", label: "ชื่อ", required: true, placeholder: "เช่น ขายึดมอเตอร์" },
      { name: "unit", label: "หน่วย", value: "ชิ้น" },
    ],
    headers: ["รหัส", "ชื่อ", ["คงเหลือ", "num"], ""],
    row: (i) => [esc(i.code), esc(i.name), [`${num(i.qty)} ${esc(i.unit)}`, "num"],
      buttons([["adjust", "รับ/เบิก"], ["edit", "แก้ไข"], ["del", "ลบ", "danger"]], i.id)],
  },
};

async function resourceView(res) {
  const cfg = RES[res];
  const items = await api("GET", `/${res}`);
  view.innerHTML = `<div class="toolbar">
      <h2>${cfg.label}</h2>
      <input type="search" id="q" placeholder="ค้นหารหัสหรือชื่อ">
      <button class="btn primary" data-act="new">+ เพิ่ม${cfg.label}</button>
    </div><div class="list" id="list"></div>`;
  const draw = () => {
    const q = $("#q").value.trim().toLowerCase();
    const shown = items.filter((i) => !q || `${i.code} ${i.name}`.toLowerCase().includes(q));
    $("#list").innerHTML = table(cfg.headers, shown.map(cfg.row),
      q ? "ไม่พบรายการที่ค้นหา" : `ยังไม่มี${cfg.label} กด "+ เพิ่ม${cfg.label}" เพื่อเริ่ม`);
  };
  $("#q").oninput = draw;
  draw();
  const byId = (id) => items.find((i) => String(i.id) === String(id));
  const reload = (msg) => { toast(msg); show(res); };

  bind({
    new: () => openForm({
      title: `เพิ่ม${cfg.label}`,
      fields: [...cfg.fields, { name: "initial_qty", label: res === "tools" ? "จำนวนดอกสำรองตอนนี้" : "ยอดคงเหลือตอนนี้", type: "number", step: cfg.step, min: 0 }],
      onSubmit: async (d) => { await api("POST", `/${res}`, d); reload("เพิ่มรายการแล้ว"); },
    }),
    edit: (id) => openForm({
      title: `แก้ไข${cfg.label}`,
      fields: cfg.fields,
      values: byId(id),
      onSubmit: async (d) => { await api("PUT", `/${res}/${id}`, d); reload("บันทึกแล้ว"); },
    }),
    adjust: (id) => {
      const item = byId(id);
      openForm({
        title: `รับ/เบิก: ${item.code}`,
        intro: `<p class="hint">${esc(item.name)} — คงเหลือ <b>${num(item[cfg.stock])} ${esc(cfg.unit(item))}</b></p>`,
        fields: [
          { name: "direction", label: "ประเภท", type: "select", options: [["in", "รับเข้า (+)"], ["out", "เบิกออก (−)"]] },
          { name: "amount", label: "จำนวน", type: "number", step: cfg.step, min: 0, required: true },
          { name: "reason", label: "หมายเหตุ", placeholder: "เช่น ซื้อเข้า PO-123, ตรวจนับ, เสียหาย" },
        ],
        submitLabel: "บันทึก",
        onSubmit: async (d) => {
          const amount = Number(d.amount);
          await api("POST", `/${res}/${id}/adjust`, { delta: d.direction === "out" ? -amount : amount, reason: d.reason });
          reload("ปรับสต็อกแล้ว");
        },
      });
    },
    replace: async (id) => {
      const t = byId(id);
      if (!confirm(`เปลี่ยน ${t.code} เป็นดอกใหม่?\nระบบจะตัดดอกสำรอง 1 ดอก (เหลือ ${t.spare_qty}) และรีเซ็ตเวลาใช้งานเป็น 0`)) return;
      try { await api("POST", `/tools/${id}/replace`); reload("เปลี่ยนดอกแล้ว"); } catch (e) { toast(e.message, true); }
    },
    del: async (id) => {
      const item = byId(id);
      if (!confirm(`ลบ ${item.code} ${item.name}?`)) return;
      try { await api("DELETE", `/${res}/${id}`); reload("ลบแล้ว"); } catch (e) { toast(e.message, true); }
    },
  });
}

// ---------- โปรแกรม G-code ----------

const option = (value, text, selected) =>
  `<option value="${esc(value)}" ${String(value) === String(selected ?? "") ? "selected" : ""}>${esc(text)}</option>`;

async function programsView() {
  const programs = await api("GET", "/programs");
  view.innerHTML = `<div class="toolbar">
      <h2>โปรแกรม G-code</h2>
      <button class="btn primary" data-act="new">+ เพิ่มโปรแกรม</button>
    </div>
    <p class="hint">แต่ละโปรแกรมผูกไฟล์ G-code กับวัตถุดิบที่ใช้ต่อชิ้น ดอกกัดที่ใช้ และชิ้นงานที่ได้ เมื่อสั่งผลิตในแท็บ "งาน CNC" ระบบจะตัดสต็อกให้อัตโนมัติ</p>
    <div class="list">${table(
      ["ชื่อ", "ไฟล์", "ชิ้นงานที่ได้", ["นาที/ชิ้น", "num"], "วัตถุดิบต่อชิ้น", "ดอกกัด", ""],
      programs.map((p) => [
        `<b>${esc(p.name)}</b>`,
        p.filename ? `${esc(p.filename)}<br><small>${num(p.gcode_lines, 0)} บรรทัด</small>` : "-",
        p.product_code ? `${esc(p.product_code)} <small>${esc(p.product_name)}</small>` : `<small>ไม่รับเข้าคลัง</small>`,
        [num(p.est_minutes), "num"],
        `<div class="chips">${p.materials.map((m) => `<span class="chip">${esc(m.code)} × ${num(m.qty_per_piece)} ${esc(m.unit)}</span>`).join("") || "-"}</div>`,
        `<div class="chips">${p.tools.map((t) => `<span class="chip">${t.tool_number != null ? "T" + t.tool_number + " " : ""}${esc(t.code)}</span>`).join("") || "-"}</div>`,
        buttons([["edit", "แก้ไข"], ["download", "ดาวน์โหลด"], ["del", "ลบ", "danger"]], p.id),
      ]),
      'ยังไม่มีโปรแกรม กด "+ เพิ่มโปรแกรม" แล้วเลือกไฟล์ G-code')}</div>`;

  bind({
    new: () => programForm(),
    edit: (id) => programForm(id),
    download: (id) => { location.href = `/api/programs/${id}/gcode`; },
    del: async (id) => {
      const p = programs.find((x) => String(x.id) === id);
      if (!confirm(`ลบโปรแกรม ${p.name}?`)) return;
      try { await api("DELETE", `/programs/${id}`); toast("ลบแล้ว"); show("programs"); } catch (e) { toast(e.message, true); }
    },
  });
}

async function programForm(id) {
  const [materials, tools, products, program] = await Promise.all([
    api("GET", "/materials"), api("GET", "/tools"), api("GET", "/products"),
    id ? api("GET", `/programs/${id}`) : Promise.resolve({ materials: [], tools: [] }),
  ]);
  let gcode = null;
  let filename = program.filename || "";

  const matRow = (m = {}) => `<div class="row-line">
      <select class="m-id"><option value="">— เลือกวัตถุดิบ —</option>${materials.map((x) => option(x.id, `${x.code} ${x.name} (${x.unit})`, m.material_id)).join("")}</select>
      <input class="m-qty" type="number" step="any" min="0" placeholder="จำนวนต่อชิ้น" value="${esc(m.qty_per_piece ?? "")}">
      <button type="button" class="btn small danger" data-remove>ลบ</button></div>`;
  const toolRow = (t = {}, note = "") => `<div class="row-line">
      <select class="t-id"><option value="">— เลือกดอกกัด —</option>${tools.map((x) => option(x.id, `${x.tool_number != null ? "T" + x.tool_number + " " : ""}${x.code} ${x.name}`, t.tool_id)).join("")}</select>
      <input class="t-min" type="number" step="any" min="0" placeholder="นาทีต่อชิ้น" value="${esc(t.minutes_per_piece ?? "")}">
      <button type="button" class="btn small danger" data-remove>ลบ</button>
      ${note ? `<span class="note">${note}</span>` : ""}</div>`;

  dlg.className = "wide";
  dlg.innerHTML = dialogShell(id ? "แก้ไขโปรแกรม G-code" : "เพิ่มโปรแกรม G-code", `
    <div class="fields">
      <label class="field"><span>ไฟล์ G-code</span>
        <input type="file" id="gfile" accept=".nc,.gcode,.ngc,.tap,.cnc,.gc,.txt">
        <small id="ginfo">${id ? `ไฟล์ปัจจุบัน: ${esc(program.filename || "-")} (${num(program.gcode_lines, 0)} บรรทัด) เลือกไฟล์ใหม่ถ้าต้องการเปลี่ยน` : "เลือกไฟล์แล้วระบบจะประมาณเวลาเครื่องและหาเบอร์ทูล (T) ให้"}</small>
      </label>
      ${fieldHtml({ name: "name", label: "ชื่อโปรแกรม", required: true, placeholder: "เช่น ขายึดมอเตอร์ รุ่น A" }, program)}
      ${fieldHtml({ name: "product_id", label: "ชิ้นงานที่ได้ (รับเข้าคลังสินค้าสำเร็จรูป)", type: "select",
        options: [["", "— ไม่รับเข้าคลัง —"], ...products.map((p) => [p.id, `${p.code} ${p.name}`])] }, program)}
      ${fieldHtml({ name: "est_minutes", label: "เวลาเครื่องต่อชิ้น (นาที)", type: "number", min: 0,
        hint: "คำนวณจาก G-code ให้อัตโนมัติ (ประมาณการ) แก้ได้ถ้าเวลาจริงต่างไป" }, program)}
    </div>
    <h3>วัตถุดิบที่ใช้ต่อ 1 ชิ้น</h3>
    ${materials.length ? "" : `<p class="hint">ยังไม่มีวัตถุดิบในระบบ เพิ่มที่แท็บ "วัตถุดิบ" ก่อน</p>`}
    <div id="mat-rows">${program.materials.map((m) => matRow(m)).join("")}</div>
    <button type="button" class="btn small" id="add-mat">+ เพิ่มวัตถุดิบ</button>
    <h3>ดอกกัดที่ใช้</h3>
    <div id="tool-rows">${program.tools.map((t) => toolRow(t)).join("")}</div>
    <button type="button" class="btn small" id="add-tool">+ เพิ่มดอกกัด</button>`);

  const form = wireDialog(async (d) => {
    const body = {
      name: d.name,
      product_id: d.product_id,
      est_minutes: d.est_minutes,
      filename,
      materials: [...form.querySelectorAll("#mat-rows .row-line")]
        .map((r) => ({ material_id: $(".m-id", r).value, qty_per_piece: $(".m-qty", r).value }))
        .filter((m) => m.material_id),
      tools: [...form.querySelectorAll("#tool-rows .row-line")]
        .map((r) => ({ tool_id: $(".t-id", r).value, minutes_per_piece: $(".t-min", r).value }))
        .filter((t) => t.tool_id),
    };
    if (gcode !== null) body.gcode = gcode;
    await api(id ? "PUT" : "POST", id ? `/programs/${id}` : "/programs", body);
    toast("บันทึกโปรแกรมแล้ว");
    show("programs");
  });

  form.addEventListener("click", (e) => { if (e.target.matches("[data-remove]")) e.target.closest(".row-line").remove(); });
  $("#add-mat", form).onclick = () => $("#mat-rows", form).insertAdjacentHTML("beforeend", matRow());
  $("#add-tool", form).onclick = () => $("#tool-rows", form).insertAdjacentHTML("beforeend", toolRow());
  $("#gfile", form).onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const info = $("#ginfo", form);
    info.textContent = "กำลังอ่านไฟล์...";
    try {
      gcode = await file.text();
      filename = file.name;
      if (!form.elements.name.value) form.elements.name.value = file.name.replace(/\.[^.]+$/, "");
      const a = await api("POST", "/gcode/analyze", { gcode });
      form.elements.est_minutes.value = a.minutes;
      info.innerHTML = `${esc(file.name)} • ${num(a.lines, 0)} บรรทัด • ประมาณ <b>${num(a.minutes)} นาที/ชิ้น</b>` +
        (a.tools.length ? ` • ทูลที่พบ: ${a.tools.map((t) => (t.tool_number != null ? "T" + t.tool_number : "ไม่ระบุ T")).join(", ")}` : "") +
        a.warnings.map((w) => `<br>⚠ ${esc(w)}`).join("");
      if (a.tools.length) {
        $("#tool-rows", form).innerHTML = a.tools.map((t) => {
          const match = tools.find((x) => t.tool_number != null && x.tool_number === t.tool_number);
          const note = t.tool_number == null ? "ส่วนที่ไม่ได้ระบุเบอร์ทูลในไฟล์ เลือกดอกที่ใช้เอง"
            : match ? `จับคู่ T${t.tool_number} จาก G-code`
            : `ยังไม่มีดอกเบอร์ T${t.tool_number} ในระบบ เพิ่มที่แท็บ "ดอกกัด/ทูล" หรือเลือกเอง`;
          return toolRow({ tool_id: match?.id, minutes_per_piece: t.minutes }, esc(note));
        }).join("");
      }
    } catch (err) {
      gcode = null;
      info.textContent = "อ่านไฟล์ไม่สำเร็จ: " + err.message;
    }
  };
}

// ---------- งาน CNC ----------

const JOB_STATUS = {
  planned: ["รอผลิต", "muted"], running: ["กำลังผลิต", "info"], done: ["เสร็จแล้ว", "ok"], cancelled: ["ยกเลิก", "bad"],
};
const jobBadge = (s) => badge(...JOB_STATUS[s]);

function jobActions(j) {
  if (j.status === "planned") return buttons([["start", "เริ่มผลิต", "primary"], ["cancel", "ยกเลิก", "danger"]], j.id);
  if (j.status === "running") return buttons([["complete", "ผลิตเสร็จ", "primary"], ["cancel", "ยกเลิก", "danger"]], j.id);
  return ["", "actions"];
}

async function jobsView() {
  const [jobs, programs] = await Promise.all([api("GET", "/jobs"), api("GET", "/programs")]);
  view.innerHTML = `<div class="toolbar">
      <h2>งาน CNC</h2>
      <button class="btn primary" data-act="new">+ สั่งผลิต</button>
    </div>
    <p class="hint"><b>เริ่มผลิต</b> = เบิกวัตถุดิบออกจากสต็อก • <b>ผลิตเสร็จ</b> = รับชิ้นงานดีเข้าคลังและบันทึกเวลาใช้งานดอกกัด • <b>ยกเลิก</b> = คืนวัตถุดิบที่เบิกไป</p>
    <div class="list">${table(
      ["#", "โปรแกรม", "ชิ้นงาน", ["สั่ง", "num"], ["ได้ดี", "num"], "สถานะ", "เริ่ม", "เสร็จ", ""],
      jobs.map((j) => [
        j.id, esc(j.program_name) + (j.note ? `<br><small>${esc(j.note)}</small>` : ""),
        j.product_code ? esc(j.product_code) : "-",
        [num(j.quantity, 0), "num"], [j.good_qty == null ? "-" : num(j.good_qty, 0), "num"],
        jobBadge(j.status), when(j.started_at), when(j.finished_at), jobActions(j),
      ]),
      'ยังไม่มีงาน กด "+ สั่งผลิต" เพื่อเริ่ม')}</div>`;

  const byId = (id) => jobs.find((j) => String(j.id) === id);
  const act = async (id, action, body, msg) => {
    try { await api("POST", `/jobs/${id}/${action}`, body); toast(msg); show("jobs"); } catch (e) { toast(e.message, true); }
  };
  bind({
    new: () => {
      if (!programs.length) return toast('ต้องเพิ่มโปรแกรมในแท็บ "โปรแกรม G-code" ก่อน', true);
      openForm({
        title: "สั่งผลิตงาน CNC",
        fields: [
          { name: "program_id", label: "โปรแกรม", type: "select", required: true,
            options: programs.map((p) => [p.id, `${p.name}${p.product_code ? " → " + p.product_code : ""}`]) },
          { name: "quantity", label: "จำนวนที่จะผลิต (ชิ้น)", type: "number", step: 1, min: 1, required: true, value: 1 },
          { name: "note", label: "หมายเหตุ", placeholder: "เช่น ลูกค้า, เลขที่ใบสั่ง" },
        ],
        submitLabel: "สร้างงาน",
        onSubmit: async (d) => { await api("POST", "/jobs", d); toast("สร้างงานแล้ว"); show("jobs"); },
      });
    },
    start: (id) => {
      const j = byId(id);
      if (confirm(`เริ่มผลิตงาน #${id} (${j.program_name} × ${j.quantity})?\nระบบจะเบิกวัตถุดิบออกจากสต็อก`)) act(id, "start", null, "เริ่มผลิตแล้ว เบิกวัตถุดิบเรียบร้อย");
    },
    complete: (id) => {
      const j = byId(id);
      openForm({
        title: `ผลิตเสร็จ: งาน #${id}`,
        intro: `<p class="hint">${esc(j.program_name)} — สั่งผลิต ${num(j.quantity, 0)} ชิ้น</p>`,
        fields: [
          { name: "good_qty", label: "จำนวนชิ้นงานดี", type: "number", step: 1, min: 0, required: true, value: j.quantity,
            hint: j.product_code ? `จะรับเข้าคลัง ${j.product_code}` : "โปรแกรมนี้ไม่ได้ผูกกับสินค้าสำเร็จรูป จึงไม่รับเข้าคลัง" },
          { name: "machine_minutes", label: "เวลาเครื่องจริงทั้งงาน (นาที)", type: "number", min: 0,
            placeholder: `ประมาณ ${num(j.est_minutes * j.quantity)}`, hint: "เว้นว่างได้ ระบบจะใช้เวลาที่ประมาณจาก G-code" },
        ],
        submitLabel: "บันทึกผลิตเสร็จ",
        onSubmit: async (d) => { await api("POST", `/jobs/${id}/complete`, d); toast("บันทึกแล้ว รับชิ้นงานเข้าคลังเรียบร้อย"); show("jobs"); },
      });
    },
    cancel: (id) => {
      const j = byId(id);
      const extra = j.status === "running" ? "\nวัตถุดิบที่เบิกไปจะถูกคืนเข้าสต็อก" : "";
      if (confirm(`ยกเลิกงาน #${id}?${extra}`)) act(id, "cancel", null, "ยกเลิกงานแล้ว");
    },
  });
}

// ---------- ประวัติสต็อก ----------

const TYPE_LABEL = { materials: "วัตถุดิบ", tools: "ดอกกัด", products: "สินค้าสำเร็จรูป" };

function movementTable(list) {
  return table(
    ["เวลา", "ประเภท", "รายการ", ["จำนวน", "num"], ["คงเหลือ", "num"], "หมายเหตุ"],
    list.map((m) => [
      when(m.ts), esc(TYPE_LABEL[m.item_type]),
      m.item_code ? `${esc(m.item_code)} <small>${esc(m.item_name)}</small>` : "<small>(ถูกลบแล้ว)</small>",
      [`<span class="${m.delta > 0 ? "plus" : "minus"}">${m.delta > 0 ? "+" : ""}${num(m.delta)}</span> <small>${esc(m.unit)}</small>`, "num"],
      [num(m.balance), "num"], esc(m.reason),
    ]),
    "ยังไม่มีความเคลื่อนไหว");
}

async function movementsView() {
  view.innerHTML = `<div class="toolbar">
      <h2>ประวัติสต็อก</h2>
      <select id="type">${option("", "ทุกประเภท")}${Object.entries(TYPE_LABEL).map(([k, v]) => option(k, v)).join("")}</select>
    </div><div class="list" id="list"></div>`;
  const load = async () => {
    const type = $("#type").value;
    $("#list").innerHTML = movementTable(await api("GET", `/movements?limit=500${type ? "&type=" + type : ""}`));
  };
  $("#type").onchange = () => load().catch((e) => toast(e.message, true));
  bind({});
  await load();
}

// ---------- ภาพรวม ----------

async function dashboardView() {
  const s = await api("GET", "/summary");
  const stat = (label, value, tab) => `<button class="stat btn" data-act="go" data-id="${tab}"><b>${num(value, 0)}</b><span>${label}</span></button>`;
  view.innerHTML = `
    <section class="stats">
      ${stat("วัตถุดิบ", s.counts.materials, "materials")}
      ${stat("ดอกกัด/ทูล", s.counts.tools, "tools")}
      ${stat("สินค้าสำเร็จรูป", s.counts.products, "products")}
      ${stat("โปรแกรม G-code", s.counts.programs, "programs")}
      ${stat("งานกำลังผลิต", s.jobs.running || 0, "jobs")}
    </section>
    <div class="grid2">
      <section class="card"><h2>วัตถุดิบใกล้หมด</h2>${table(["รหัส", "ชื่อ", ["คงเหลือ", "num"], ["ขั้นต่ำ", "num"]],
        s.low_materials.map((m) => [esc(m.code), esc(m.name), [`${num(m.qty)} ${esc(m.unit)}`, "num"], [num(m.min_qty), "num"]]),
        "สต็อกวัตถุดิบปกติทุกรายการ")}</section>
      <section class="card"><h2>ดอกกัดใกล้หมดอายุ</h2>${table(["รหัส", "T", "อายุที่ใช้ไป", ["สำรอง", "num"]],
        s.worn_tools.map((t) => [esc(t.code), t.tool_number != null ? `T${t.tool_number}` : "-", lifeBar(t), [num(t.spare_qty, 0), "num"]]),
        "ไม่มีดอกกัดที่ใกล้หมดอายุ")}</section>
    </div>
    <section class="card"><h2>งานที่รอผลิต / กำลังผลิต</h2>${table(["#", "โปรแกรม", ["จำนวน", "num"], "สถานะ", "สร้างเมื่อ"],
      s.active_jobs.map((j) => [j.id, esc(j.program_name), [num(j.quantity, 0), "num"], jobBadge(j.status), when(j.created_at)]),
      "ไม่มีงานค้าง")}</section>
    <section class="card"><h2>ความเคลื่อนไหวล่าสุด</h2>${movementTable(s.recent_movements)}</section>`;
  bind({ go: (tab) => show(tab) });
}

// ---------- เมนูและการสลับหน้า ----------

const VIEWS = {
  dashboard: ["ภาพรวม", dashboardView],
  materials: ["วัตถุดิบ", () => resourceView("materials")],
  tools: ["ดอกกัด/ทูล", () => resourceView("tools")],
  products: ["สินค้าสำเร็จรูป", () => resourceView("products")],
  programs: ["โปรแกรม G-code", programsView],
  jobs: ["งาน CNC", jobsView],
  movements: ["ประวัติสต็อก", movementsView],
};

async function show(tab) {
  if (!VIEWS[tab]) tab = "dashboard";
  if (dlg.open) dlg.close();
  if (location.hash !== "#" + tab) history.replaceState(null, "", "#" + tab);
  $("#tabs").innerHTML = Object.entries(VIEWS)
    .map(([key, [text]]) => `<button data-tab="${key}" ${key === tab ? 'aria-current="page"' : ""}>${text}</button>`).join("");
  try {
    await VIEWS[tab][1]();
  } catch (e) {
    view.innerHTML = `<p class="form-error">โหลดข้อมูลไม่สำเร็จ: ${esc(e.message)}</p>`;
  }
}

$("#tabs").onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) show(b.dataset.tab); };
window.addEventListener("hashchange", () => show(location.hash.slice(1)));
show(location.hash.slice(1));
