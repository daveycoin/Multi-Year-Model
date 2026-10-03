"use strict";
/* Public Finance CRM front end: vanilla JS, hash routing, no build step. */

// ------------------------------------------------------------------ helpers
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const fdate = s => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ""); return m ? `${MONTHS[+m[2] - 1]} ${+m[3]}${m[1] === "1900" ? "" : ", " + m[1]}` : ""; };
const money = n => { n = +n || 0; return n >= 1e9 ? `$${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n ? `$${n.toLocaleString()}` : ""; };
const num = n => (n == null || n === "" ? "" : (+n).toLocaleString());
const link = (entity, id, text) => id ? `<a href="#/${entity}/${id}">${esc(text)}</a>` : "";
const editLink = (entity, id, text) => `<a href="#" data-edit="${entity}:${id}">${esc(text)}</a>`;
const chip = (t, cls = "") => t ? `<span class="chip ${cls}">${esc(t)}</span>` : "";
const whenText = d => d === 0 ? "today" : d > 0 ? `in ${d}d` : `${-d}d ago`;

async function api(method, path, body, raw) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.body = raw ? body : JSON.stringify(body); opts.headers["Content-Type"] = raw ? "text/csv" : "application/json"; }
  const r = await fetch("/api" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

let META = null;

// ------------------------------------------------------------ entity config
const SECTOR_FIELDS = {
  "City": [["population", "Population", "number"]],
  "County": [["population", "Population", "number"]],
  "K-12 School District": [["enrollment", "Enrollment", "number"], ["remaining_authorization", "Remaining voted authorization ($)", "number"]],
  "Higher Education": [["control", "Public / Private"], ["enrollment", "Enrollment", "number"]],
  "Utility": [["utility_type", "Utility type (water, electric, etc.)"]],
  "Private School": [["affiliation", "Affiliation"], ["enrollment", "Enrollment", "number"]],
  "Charter School": [["authorizer", "Authorizer"], ["enrollment", "Enrollment", "number"]],
  "Special District": [["district_type", "District type (MUD, PID, CDD...)"]],
  "Other": [],
};
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const KEY_KINDS = ["Election", "Bond Election", "Budget Adoption", "Fiscal Year End", "Charter Renewal", "Term Expiration", "RFP Deadline", "Call Date", "Rate Study", "Board Meeting", "Other"];

const F = (k, label, type = "text", extra = {}) => ({ k, label, type, ...extra });
const ENT = {
  issuers: {
    label: "Issuer", plural: "Issuers", detail: true, title: r => r.name,
    fields: [F("name", "Name", "text", { req: 1 }), F("sector", "Sector", "select", { options: () => META.sectors, req: 1 }),
      F("state", "State"), F("fiscal_year_end", "Fiscal year end", "select", { options: MONTH_NAMES }),
      F("primary_banker", "Primary banker (firm)"), F("our_coverage_banker", "Our coverage banker"),
      F("other_bankers", "Other banks that cover them", "text", { full: 1 }), F("website", "Website"),
      F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [
      { h: "Issuer", v: r => link("issuers", r.id, r.name), s: r => r.name.toLowerCase() },
      { h: "Sector", v: r => chip(r.sector), s: r => r.sector }, { h: "State", v: r => esc(r.state) },
      { h: "Primary banker", v: r => esc(r.primary_banker), s: r => r.primary_banker || "" },
      { h: "Our coverage", v: r => esc(r.our_coverage_banker) },
      { h: "People", v: r => r.n_people, s: r => r.n_people }, { h: "Active deals", v: r => r.n_active_deals, s: r => r.n_active_deals }],
  },
  people: {
    label: "Person", plural: "People", detail: true, title: r => r.name,
    fields: [F("name", "Name", "text", { req: 1 }), F("title", "Title"),
      F("__links", "Issuers & groups", "links", { full: 1 }), F("developer_id", "Developer (if not an issuer contact)", "ref", { ref: "developers" }),
      F("email", "Email"), F("phone", "Phone"), F("reports_to_id", "Reports to", "ref", { ref: "people" }),
      F("priority", "Priority (sets follow-up cadence)", "select", { options: ["A", "B", "C"] }),
      F("term_start", "Term start", "date"), F("term_end", "Term end", "date"),
      F("last_contact", "Last contact", "date"), F("next_followup", "Next follow-up (overrides cadence)", "date"),
      F("birthday", "Birthday", "date"), F("anniversary", "Anniversary", "date"),
      F("spouse", "Spouse"), F("kids", "Kids"),
      F("personal_notes", "Personal notes", "textarea", { full: 1 }), F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [
      { h: "Name", v: r => link("people", r.id, r.name), s: r => r.name.toLowerCase() }, { h: "Title", v: r => esc(r.title) },
      { h: "Organization", v: r => r.links.length ? r.links.map(l => link("issuers", l.issuer_id, l.issuer_name)).join(", ") : link("developers", r.developer_id, r.developer_name), s: r => r.links[0]?.issuer_name || r.developer_name || "" },
      { h: "Groups", v: r => [...new Set(r.links.flatMap(l => l.groups))].map(g => chip(g)).join(" "), s: r => r.links.flatMap(l => l.groups).join() },
      { h: "Pri", v: r => chip(r.priority), s: r => r.priority || "C" },
      { h: "Last contact", v: r => fdate(r.last_contact), s: r => r.last_contact || "" },
      { h: "Next follow-up", v: r => fdate(r.next_followup), s: r => r.next_followup || "9" },
      { h: "Term ends", v: r => fdate(r.term_end), s: r => r.term_end || "9" }],
  },
  developers: {
    label: "Developer", plural: "Developers", detail: true, title: r => r.name,
    fields: [F("name", "Name", "text", { req: 1 }), F("website", "Website"), F("phone", "Phone"), F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [{ h: "Developer", v: r => link("developers", r.id, r.name), s: r => r.name.toLowerCase() },
      { h: "Projects", v: r => r.n_projects, s: r => r.n_projects }, { h: "People", v: r => r.n_people, s: r => r.n_people }, { h: "Website", v: r => esc(r.website) }],
  },
  projects: {
    label: "Developer project", plural: "Developer projects", detail: true, title: r => r.name,
    fields: [F("name", "Project name", "text", { req: 1 }), F("developer_id", "Developer", "ref", { ref: "developers" }),
      F("issuer_id", "Issuer behind it (district / city / county)", "ref", { ref: "issuers" }),
      F("structure", "Structure", "select", { options: ["Assessment-backed (PID/MUD/CDD)", "Sales Tax Rebate Monetization", "Other"] }),
      F("location", "Location"), F("est_par", "Estimated par ($)", "number"), F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [{ h: "Project", v: r => link("projects", r.id, r.name), s: r => r.name.toLowerCase() },
      { h: "Developer", v: r => link("developers", r.developer_id, r.developer_name), s: r => r.developer_name || "" },
      { h: "Issuer", v: r => link("issuers", r.issuer_id, r.issuer_name), s: r => r.issuer_name || "" },
      { h: "Structure", v: r => esc(r.structure) }, { h: "Est. par", v: r => money(r.est_par), s: r => r.est_par || 0 }],
  },
  deals: {
    label: "Financing", plural: "Financings", detail: false, title: r => r.name,
    fields: [F("name", "Name", "text", { req: 1, full: 1 }),
      F("pipeline", "Pipeline", "select", { options: () => [["standard", "Issuer financing"], ["developer", "Developer deal"]], req: 1 }),
      F("stage", "Stage", "select", { options: "stages", req: 1 }),
      F("issuer_id", "Issuer", "ref", { ref: "issuers" }), F("project_id", "Developer project", "ref", { ref: "projects" }),
      F("purpose", "Purpose", "select", { options: ["New Money", "Refunding", "New Money & Refunding", "Working Capital (TAN/RAN)", "Capital Lease / Note", "Other"] }),
      F("security_type", "Security", "select", { options: ["GO", "Revenue", "Sales Tax", "Lease / COP", "Assessment", "Tax Increment", "Sales Tax Rebate", "Other"] }),
      F("par", "Estimated par ($)", "number"), F("role", "Our role", "select", { options: ["Senior Manager", "Co-Manager", "Underwriter", "Placement Agent", "Other"] }),
      F("probability", "Probability", "select", { options: ["10", "25", "40", "50", "60", "75", "90", "100"] }),
      F("expected_date", "Expected pricing date", "date"), F("rfp_deadline", "RFP deadline", "date"),
      F("ma_name", "Municipal advisor"), F("bond_counsel", "Bond counsel"), F("trustee", "Trustee"),
      F("competing_banks", "Competing banks"), F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [{ h: "Financing", v: r => editLink("deals", r.id, r.name), s: r => r.name.toLowerCase() },
      { h: "Stage", v: r => chip(r.stage), s: r => r.stage },
      { h: "Issuer / project", v: r => esc(r.project_name ? `${r.project_name}${r.issuer_name ? " / " + r.issuer_name : ""}` : r.issuer_name) },
      { h: "Par", v: r => money(r.par), s: r => r.par || 0 }, { h: "Expected", v: r => fdate(r.expected_date), s: r => r.expected_date || "9" },
      { h: "RFP due", v: r => fdate(r.rfp_deadline), s: r => r.rfp_deadline || "9" }],
  },
  key_dates: {
    label: "Date", plural: "Key dates", detail: false, title: r => r.title,
    fields: [F("title", "Title", "text", { req: 1, full: 1 }), F("kind", "Type", "select", { options: KEY_KINDS }),
      F("date", "Date", "date", { req: 1 }), F("issuer_id", "Issuer", "ref", { ref: "issuers" }),
      F("remind_days_before", "Start reminding (days before)", "number"),
      F("recurs_annually", "Repeats every year", "bool"), F("done", "Done / no longer relevant", "bool"),
      F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [{ h: "Date", v: r => editLink("key_dates", r.id, fdate(r.date)), s: r => r.date },
      { h: "Title", v: r => esc(r.title) }, { h: "Type", v: r => chip(r.kind), s: r => r.kind || "" },
      { h: "Issuer", v: r => link("issuers", r.issuer_id, r.issuer_name) },
      { h: "", v: r => `${r.recurs_annually ? chip("yearly") : ""} ${r.done ? chip("done", "ok") : ""}` }],
  },
  interactions: {
    label: "Interaction", plural: "Interactions", detail: false, title: () => "interaction",
    fields: [F("person_id", "Person", "ref", { ref: "people", req: 1 }), F("date", "Date", "date", { req: 1 }),
      F("type", "Type", "select", { options: ["Call", "Email", "Meeting", "Conference / Event", "Lunch / Dinner", "Note"] }),
      F("next_followup", "Next follow-up (optional)", "date"), F("notes", "Notes", "textarea", { full: 1 })],
    cols: () => [{ h: "Date", v: r => editLink("interactions", r.id, fdate(r.date)), s: r => r.date },
      { h: "Type", v: r => chip(r.type) }, { h: "Person", v: r => link("people", r.person_id, r.person_name) },
      { h: "Notes", v: r => esc(r.notes) }],
  },
};

// what each detail page shows below the fields
const PEOPLE_PICK = ["Name", "Title", "Pri", "Last contact", "Next follow-up", "Term ends"];
const RELATED = {
  issuers: [
    { title: "Elected", group: "Elected", entity: "people", pick: PEOPLE_PICK },
    { title: "Staff", group: "Staff", entity: "people", pick: PEOPLE_PICK },
    { title: "Related (advisors, counsel, trustees, etc.)", group: "Related", entity: "people", pick: PEOPLE_PICK },
    { title: "Ungrouped (assign a group by editing the person)", group: "Ungrouped", entity: "people", pick: PEOPLE_PICK, hideIfEmpty: 1, noAdd: 1 },
    { title: "Financings", entity: "deals", key: "issuer_id", pick: ["Financing", "Stage", "Par", "Expected", "RFP due"] },
    { title: "Developer projects behind this issuer", entity: "projects", key: "issuer_id", pick: ["Project", "Developer", "Structure", "Est. par"], noAdd: 1, hideIfEmpty: 1 },
    { title: "Key dates", entity: "key_dates", key: "issuer_id", pick: ["Date", "Title", "Type", ""] },
    { title: "Recent interactions", entity: "interactions", key: "issuer_id", pick: ["Date", "Type", "Person", "Notes"], noAdd: 1 },
  ],
  people: [
    { title: "Interactions", entity: "interactions", key: "person_id", pick: ["Date", "Type", "Notes"], addLabel: "Log interaction" },
    { title: "Direct reports", entity: "people", key: "reports_to_id", pick: ["Name", "Title", "Last contact"], noAdd: 1 },
  ],
  developers: [
    { title: "People", entity: "people", key: "developer_id", pick: ["Name", "Title", "Pri", "Last contact", "Next follow-up"] },
    { title: "Projects", entity: "projects", key: "developer_id", pick: ["Project", "Issuer", "Structure", "Est. par"] },
  ],
  projects: [
    { title: "Financings", entity: "deals", key: "project_id", pick: ["Financing", "Stage", "Par", "Expected", "RFP due"], prefill: { pipeline: "developer" } },
  ],
};

// ----------------------------------------------------------------- rendering
function table(cols, rows, empty = "Nothing here yet.") {
  if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
  const head = cols.map((c, i) => `<th class="${c.s ? "sortable" : ""}" data-col="${i}">${esc(c.h)}</th>`).join("");
  const body = rows.map(r => `<tr>${cols.map(c => `<td>${c.v(r) ?? ""}</td>`).join("")}</tr>`).join("");
  return `<div class="tablewrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function sortable(root, cols, rows) {
  root.querySelectorAll("th.sortable").forEach(th => th.addEventListener("click", () => {
    const i = +th.dataset.col, asc = th.dataset.asc !== "1";
    const k = cols[i].s;
    const sorted = [...rows].sort((a, b) => { const x = k(a), y = k(b); return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1); });
    root.querySelector("tbody").innerHTML = sorted.map(r => `<tr>${cols.map(c => `<td>${c.v(r) ?? ""}</td>`).join("")}</tr>`).join("");
    root.querySelectorAll("th").forEach(t => delete t.dataset.asc); th.dataset.asc = asc ? "1" : "0";
  }));
}

function eventRow(e) {
  const cls = e.days < 0 ? "bad" : e.reminder ? "warn" : "";
  const title = e.link ? (e.link.entity === "deals" ? editLink("deals", e.link.id, e.title) : link(e.link.entity, e.link.id, e.title)) : esc(e.title);
  return `<tr><td>${fdate(e.date)}</td><td>${chip(whenText(e.days), cls)}</td><td>${chip(e.kind)}</td><td>${title}</td><td class="muted">${esc(e.detail)}</td></tr>`;
}
const eventsTable = (evs, empty) => evs.length ? `<div class="tablewrap"><table><tbody>${evs.map(eventRow).join("")}</tbody></table></div>` : `<div class="empty">${empty}</div>`;

// -------------------------------------------------------------------- pages
const pages = {};

pages.dashboard = async main => {
  const d = await api("GET", "/dashboard");
  const pipe = (key, label) => {
    const p = d.pipeline[key];
    const rows = p.stages.filter(s => s.count).map(s => `<div>${esc(s.stage)}</div><div>${s.count}</div><div>${money(s.par) || "–"}</div>`).join("");
    return `<div class="panel"><div class="head"><h2>${label}</h2><a href="#/deals/${key}">Open pipeline →</a></div>
      ${rows ? `<div class="bar">${rows}</div>` : `<div class="empty">No financings yet.</div>`}
      <div class="muted" style="margin-top:8px">Active par ${money(p.active_par) || "$0"} · probability-weighted ${money(p.weighted_par) || "$0"}</div></div>`;
  };
  const od = d.overdue.map(r => `<tr><td>${link("people", r.id, r.name)}<div class="muted">${esc(r.title)}</div></td><td>${esc(r.issuer_name)}</td><td>${chip(r.priority)}</td>
    <td>${fdate(r.last_contact) || '<span class="muted">never</span>'}</td><td>${chip(r.days_overdue ? `${r.days_overdue}d overdue` : "due today", "bad")}<div class="muted">${esc(r.why)}</div></td>
    <td><button class="btn sm" data-log="${r.id}">Log contact</button></td></tr>`).join("");
  main.innerHTML = `<div class="head"><div><h1>Dashboard</h1><div class="sub">${new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</div></div></div>
    <div class="stats">${Object.entries(d.stats).map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join("")}</div>
    <div class="panel"><div class="head"><h2>Overdue follow-ups (${d.overdue.length})</h2></div>
      ${od ? `<div class="tablewrap"><table><thead><tr><th>Contact</th><th>Organization</th><th>Pri</th><th>Last contact</th><th>Status</th><th></th></tr></thead><tbody>${od}</tbody></table></div>` : `<div class="empty">You're caught up.</div>`}</div>
    <div class="panel"><div class="head"><h2>Upcoming dates &amp; reminders (next ${d.window} days)</h2><a href="#/dates">All dates →</a></div>
      ${eventsTable(d.events, "Nothing coming up.")}</div>
    <div class="grid2">${pipe("standard", "Issuer financings")}${pipe("developer", "Developer deals")}</div>`;
};

async function listPage(main, entity, opts = {}) {
  const E = ENT[entity];
  const rows = await api("GET", "/" + entity);
  const cols = E.cols();
  const sectorFilter = entity === "issuers" ? `<select id="f-sector"><option value="">All sectors</option>${META.sectors.map(s => `<option>${esc(s)}</option>`).join("")}</select>` : "";
  main.innerHTML = `<div class="head"><div><h1>${E.plural}</h1><div class="sub" id="count"></div></div>
    <button class="btn primary" data-add="${entity}">+ Add ${E.label.toLowerCase()}</button></div>
    <div class="toolbar"><input id="q" placeholder="Search..." type="search">${sectorFilter}</div><div class="panel" id="tbl"></div>`;
  const draw = () => {
    const q = $("#q").value.toLowerCase(), sec = $("#f-sector")?.value;
    const shown = rows.filter(r => (!sec || r.sector === sec) && (!q || JSON.stringify(Object.values(r)).toLowerCase().includes(q)));
    $("#tbl").innerHTML = table(cols, shown, "No matches.");
    $("#count").textContent = `${shown.length} of ${rows.length}`;
    sortable($("#tbl"), cols, shown);
  };
  $("#q").addEventListener("input", draw); $("#f-sector")?.addEventListener("change", draw); draw();
}

async function detailPage(main, entity, id) {
  const E = ENT[entity], r = await api("GET", `/${entity}/${id}`);
  const rows = E.fields.filter(f => f.k !== "name" && r[f.k] != null && r[f.k] !== "").map(f => {
    let v = r[f.k];
    if (f.type === "ref") v = link(f.ref, v, r[f.k.replace(/_id$/, "") + "_name"] || v);
    else if (f.type === "date") v = esc(fdate(v));
    else if (f.k === "est_par") v = esc(money(v));
    else v = esc(v);
    return `<dt>${esc(f.label)}</dt><dd>${v}</dd>`;
  });
  if (entity === "issuers" && r.extra) for (const [k, label, type] of SECTOR_FIELDS[r.sector] || []) if (r.extra[k] != null && r.extra[k] !== "") rows.push(`<dt>${esc(label)}</dt><dd>${esc(type === "number" ? num(r.extra[k]) : r.extra[k])}</dd>`);
  if (entity === "people" && r.links.length) rows.unshift(`<dt>Issuers</dt><dd>${r.links.map(l => `${link("issuers", l.issuer_id, l.issuer_name)} ${l.groups.map(g => chip(g)).join(" ")}`).join("<br>")}</dd>`);
  const sub = { issuers: () => `${chip(r.sector)} ${esc(r.state)}`, people: () => esc([r.title, r.issuer_name || r.developer_name].filter(Boolean).join(", ")), developers: () => "", projects: () => esc(r.developer_name || "") }[entity]();
  main.innerHTML = `<div class="head"><div><h1>${esc(E.title(r))}</h1><div class="sub">${sub}</div></div>
    <div><button class="btn" data-edit="${entity}:${id}">Edit</button> <button class="btn danger" data-del="${entity}:${id}">Delete</button></div></div>
    <div class="panel"><dl class="kv">${rows.join("") || '<span class="muted">No details yet.</span>'}</dl></div>
    <div id="related"></div>`;
  let atIssuer = null;
  for (const sec of RELATED[entity]) {
    const E2 = ENT[sec.entity];
    let data;
    if (sec.group) {  // people at this issuer, split by group; a person tagged to several groups appears in each
      atIssuer ??= await api("GET", `/people?linked_issuer=${id}`);
      data = atIssuer.filter(p => sec.group === "Ungrouped" ? !p.groups.length : p.groups.includes(sec.group));
    } else data = await api("GET", `/${sec.entity}?${sec.key}=${id}`);
    if (sec.hideIfEmpty && !data.length) continue;
    const cols = E2.cols().filter(c => sec.pick.includes(c.h));
    const prefill = sec.group ? { links: [{ issuer_id: +id, groups: [sec.group] }] } : { [sec.key]: +id, ...(sec.prefill || {}) };
    if (entity === "projects" && r.issuer_id) prefill.issuer_id = r.issuer_id;
    if (entity === "people" && sec.entity === "interactions") prefill.person_id = +id;
    const div = document.createElement("div"); div.className = "panel";
    div.innerHTML = `<div class="head"><h2>${sec.title} (${data.length})</h2>${sec.noAdd ? "" : `<button class="btn sm" data-add="${sec.entity}" data-prefill='${esc(JSON.stringify(prefill))}'>+ ${sec.addLabel || "Add"}</button>`}</div>${table(cols, data)}`;
    $("#related").appendChild(div);
  }
}

const INACTIVE = ["Closed", "Lost", "On Hold"];
pages.deals = async (main, which) => {
  const pl = which === "developer" ? "developer" : "standard", stages = META.stages[pl];
  const all = (await api("GET", "/deals")).filter(d => d.pipeline === pl);
  const cols = [
    { h: "Financing", v: r => editLink("deals", r.id, r.name), s: r => r.name.toLowerCase() },
    { h: "Stage", v: r => `<select data-move="${r.id}" style="width:auto">${stages.map(s => `<option ${s === r.stage ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>`, s: r => stages.indexOf(r.stage) },
    { h: pl === "developer" ? "Project / issuer" : "Issuer", v: r => esc([r.project_name, r.issuer_name].filter(Boolean).join(" / ")), s: r => r.issuer_name || "" },
    { h: "Par", v: r => money(r.par), s: r => r.par || 0 },
    { h: "Prob.", v: r => r.probability ? r.probability + "%" : "", s: r => r.probability || 0 },
    { h: "Expected", v: r => fdate(r.expected_date), s: r => r.expected_date || "9" },
    { h: "RFP due", v: r => r.rfp_deadline ? chip(fdate(r.rfp_deadline), "warn") : "", s: r => r.rfp_deadline || "9" },
    { h: "MA", v: r => esc(r.ma_name), s: r => r.ma_name || "" },
    { h: "Bond counsel", v: r => esc(r.bond_counsel), s: r => r.bond_counsel || "" }];
  const saved = sessionStorage.getItem("dealfilter") || "active";
  main.innerHTML = `<div class="head"><div><h1>Pipeline</h1><div class="sub" id="count"></div></div>
    <button class="btn primary" data-add="deals" data-prefill='${JSON.stringify({ pipeline: pl })}'>+ Add financing</button></div>
    <div class="tabs"><a class="btn ${pl === "standard" ? "active" : ""}" href="#/deals/standard">Issuer financings</a>
    <a class="btn ${pl === "developer" ? "active" : ""}" href="#/deals/developer">Developer deals</a></div>
    <div class="toolbar"><input id="q" type="search" placeholder="Search..."><select id="f-stage">
      <option value="active">Active (hide closed / lost / on hold)</option><option value="all">All stages</option>
      ${stages.map(s => `<option ${s === saved ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></div>
    <div class="panel" id="tbl"></div>`;
  $("#f-stage").value = [...$("#f-stage").options].some(o => o.value === saved) ? saved : "active";
  const draw = () => {
    const f = $("#f-stage").value, q = $("#q").value.toLowerCase();
    const rows = all.filter(d => (f === "active" ? !INACTIVE.includes(d.stage) : f === "all" || d.stage === f) && (!q || JSON.stringify(Object.values(d)).toLowerCase().includes(q)))
      .sort((a, b) => stages.indexOf(a.stage) - stages.indexOf(b.stage) || (a.expected_date || "9").localeCompare(b.expected_date || "9"));
    const par = rows.reduce((t, d) => t + (d.par || 0), 0), w = rows.reduce((t, d) => t + (d.par || 0) * (d.probability || 0) / 100, 0);
    $("#count").textContent = `${rows.length} financings · ${money(par) || "$0"} par · ${money(w) || "$0"} probability-weighted`;
    $("#tbl").innerHTML = table(cols, rows, "No financings match.");
    sortable($("#tbl"), cols, rows);
  };
  $("#q").addEventListener("input", draw);
  $("#f-stage").addEventListener("change", () => { sessionStorage.setItem("dealfilter", $("#f-stage").value); draw(); });
  draw();
};

pages.dates = async main => {
  const win = +(sessionStorage.getItem("win") || 90);
  const [evs, kd] = await Promise.all([api("GET", `/events?window=${win}`), api("GET", "/key_dates")]);
  const cols = ENT.key_dates.cols();
  main.innerHTML = `<div class="head"><div><h1>Dates &amp; reminders</h1><div class="sub">Includes term ends, birthdays, anniversaries, RFP deadlines and expected pricing dates pulled from your records.</div></div>
    <button class="btn primary" data-add="key_dates">+ Add date</button></div>
    <div class="panel"><div class="head"><h2>Coming up</h2><select id="win" style="width:auto">${[30, 60, 90, 180, 365].map(n => `<option value="${n}" ${n === win ? "selected" : ""}>Next ${n} days</option>`).join("")}</select></div>
    ${eventsTable(evs, "Nothing in this window.")}</div>
    <div class="panel"><h2>Key dates you've entered (${kd.length})</h2>${table(cols, kd)}</div>`;
  $("#win").addEventListener("change", e => { sessionStorage.setItem("win", e.target.value); route(); });
};

pages.import = async main => {
  main.innerHTML = `<h1>Import contacts</h1><div class="sub">Upload a CSV (Outlook contacts export, Excel "Save as CSV", etc.). Issuers are created automatically from the organization column; duplicates (same email, or same name at the same issuer) are skipped.</div>
    <div class="panel"><p class="muted">Recognized columns: Name (or First Name + Last Name), Title, Issuer / Organization / Company, Sector, State, Email, Phone, Priority (A/B/C), Birthday, Anniversary, Spouse, Kids, Term End, Notes.</p>
    <input type="file" id="file" accept=".csv,text/csv"><div id="out" style="margin-top:14px"></div></div>`;
  $("#file").addEventListener("change", async e => {
    const f = e.target.files[0]; if (!f) return;
    const text = await f.text(), out = $("#out");
    try {
      const r = await api("POST", "/import/people?dry=1", text, true);
      out.innerHTML = `<p><b>${r.total}</b> rows: <b>${r.new_people}</b> new people, <b>${r.new_issuers}</b> new issuers, ${r.duplicates} duplicates skipped, ${r.skipped} blank rows.</p>
        <p class="muted">Column mapping: ${Object.entries(r.mapping).map(([k, v]) => `${esc(v)} → ${k}`).join(", ")}</p>
        ${r.sample.length ? `<div class="pre">${r.sample.map(s => esc(`${s.name} | ${s.title} | ${s.issuer}`)).join("<br>")}</div>` : ""}
        <p><button class="btn primary" id="go" ${r.new_people ? "" : "disabled"}>Import ${r.new_people} people</button></p>`;
      $("#go").addEventListener("click", async () => {
        const done = await api("POST", "/import/people", text, true);
        out.innerHTML = `<p>Imported ${done.new_people} people and ${done.new_issuers} issuers. <a href="#/people">View people →</a></p>`;
      });
    } catch (err) { out.innerHTML = `<p style="color:var(--danger)">${esc(err.message)}</p>`; }
  });
};

pages.settings = async main => {
  const s = META.settings;
  main.innerHTML = `<h1>Settings</h1><div class="sub">&nbsp;</div>
    <div class="panel"><h2>Follow-up cadence</h2><p class="muted">A contact is overdue when this many days pass since the last logged contact, unless you set a manual next follow-up date.</p>
    <form id="sf" style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;max-width:760px">
    ${[["cadence_A", "A-list (days)"], ["cadence_B", "B-list (days)"], ["cadence_C", "C-list (days)"], ["dash_window", "Dashboard look-ahead (days)"], ["digest_window", "Email digest look-ahead (days)"]]
      .map(([k, l]) => `<div><label>${l}</label><input name="${k}" type="number" min="1" value="${esc(s[k])}"></div>`).join("")}
    <div style="grid-column:1/-1"><button class="btn primary">Save</button> <span id="saved" class="muted"></span></div></form></div>
    <div class="panel"><h2>Weekly email digest</h2><p class="muted">Run <code>python3 digest.py</code> on a schedule (see README) to email this summary.</p>
    <a class="btn" href="/api/digest.html" target="_blank">Preview digest</a></div>
    <div class="panel"><h2>Backup</h2><p class="muted">Everything lives in one file, <code>data/crm.db</code>. Download a copy regularly.</p><a class="btn" href="/api/backup">Download backup</a></div>`;
  $("#sf").addEventListener("submit", async e => {
    e.preventDefault();
    try { META.settings = await api("PUT", "/settings", Object.fromEntries(new FormData(e.target))); $("#saved").textContent = "Saved."; }
    catch (err) { $("#saved").textContent = err.message; }
  });
};

// -------------------------------------------------------------------- forms
async function openForm(entity, rec = {}, prefill = {}) {
  const E = ENT[entity], dlg = $("#dlg"), editing = !!rec.id;
  const data = { ...(entity === "interactions" ? { date: todayISO() } : {}), ...(entity === "key_dates" ? { remind_days_before: 14 } : {}), ...(entity === "people" ? { priority: "C" } : {}), ...prefill, ...rec };
  if (entity === "deals" && !data.pipeline) data.pipeline = "standard";
  if (entity === "deals" && !data.stage) data.stage = META.stages[data.pipeline][0];
  if (entity === "issuers" && !data.sector) data.sector = "City";
  const refs = {};
  await Promise.all(E.fields.filter(f => f.type === "ref").map(async f => refs[f.ref] ??= await api("GET", "/" + f.ref)));
  if (entity === "people") refs.issuers ??= await api("GET", "/issuers");
  const opt = (v, label, sel) => `<option value="${esc(v)}" ${String(sel) === String(v) ? "selected" : ""}>${esc(label)}</option>`;
  const linkRow = l => `<div class="linkrow"><select class="lk-issuer"><option value="">— issuer —</option>${refs.issuers.map(o => opt(o.id, o.name, l.issuer_id)).join("")}</select>
    ${META.groups.map(g => `<label><input type="checkbox" value="${g}" ${(l.groups || []).includes(g) ? "checked" : ""}> ${g}</label>`).join("")}
    <button type="button" class="btn sm lk-del" title="Remove this issuer">✕</button></div>`;
  const input = f => {
    if (f.type === "links") return `<div class="full"><label>${esc(f.label)} (tag each issuer with one or more groups; the first is the primary issuer)</label>
      <div id="links">${(data.links?.length ? data.links : [{}]).map(linkRow).join("")}</div><button type="button" class="btn sm" id="addlink">+ Link another issuer</button></div>`;
    const v = data[f.k] ?? "", id = `f_${f.k}`;
    let ctl;
    if (f.type === "textarea") ctl = `<textarea id="${id}" name="${f.k}" rows="3">${esc(v)}</textarea>`;
    else if (f.type === "bool") return `<div><label><input type="checkbox" id="${id}" name="${f.k}" ${+v ? "checked" : ""}> ${esc(f.label)}</label></div>`;
    else if (f.type === "ref") ctl = `<select id="${id}" name="${f.k}"><option value="">—</option>${refs[f.ref].filter(o => o.id !== rec.id || f.ref !== entity).map(o => opt(o.id, o.name + (o.issuer_name && f.ref === "people" ? ` (${o.issuer_name})` : ""), v)).join("")}</select>`;
    else if (f.type === "select") {
      let os = f.options === "stages" ? META.stages[data.pipeline] : typeof f.options === "function" ? f.options() : f.options;
      ctl = `<select id="${id}" name="${f.k}">${f.type === "select" && !f.req ? '<option value="">—</option>' : ""}${os.map(o => Array.isArray(o) ? opt(o[0], o[1], v) : opt(o, o, v)).join("")}</select>`;
    } else ctl = `<input id="${id}" name="${f.k}" type="${f.type === "number" ? "number" : f.type === "date" ? "date" : "text"}" ${f.type === "number" ? 'step="any"' : ""} value="${esc(v)}">`;
    return `<div class="${f.full ? "full" : ""}"><label for="${id}">${esc(f.label)}${f.req ? " *" : ""}</label>${ctl}</div>`;
  };
  const extraHTML = sector => (SECTOR_FIELDS[sector] || []).map(([k, label, type]) =>
    `<div><label>${esc(label)}</label><input name="x_${k}" type="${type === "number" ? "number" : "text"}" step="any" value="${esc((data.extra || {})[k] ?? "")}"></div>`).join("");
  dlg.innerHTML = `<form method="dialog" id="ff"><div class="dlg-head">${editing ? "Edit" : "Add"} ${E.label.toLowerCase()}</div>
    <div class="dlg-body">${E.fields.map(input).join("")}${entity === "issuers" ? `<h3>Sector details</h3><span id="extra" style="display:contents">${extraHTML(data.sector)}</span>` : ""}</div>
    <div class="dlg-err" id="ferr"></div>
    <div class="dlg-foot"><div>${editing ? `<button type="button" class="btn danger" id="fdel">Delete</button>` : ""}</div>
    <div><button type="button" class="btn" id="fcancel">Cancel</button> <button class="btn primary" id="fsave">Save</button></div></div></form>`;
  const form = $("#ff");
  if (entity === "people") {
    $("#addlink").addEventListener("click", () => $("#links").insertAdjacentHTML("beforeend", linkRow({})));
    $("#links").addEventListener("click", e => { if (e.target.classList.contains("lk-del")) e.target.closest(".linkrow").remove(); });
  }
  if (entity === "issuers") form.elements.sector.addEventListener("change", e => { data.sector = e.target.value; data.extra = {}; $("#extra").innerHTML = extraHTML(data.sector); });
  if (entity === "deals") form.elements.pipeline.addEventListener("change", e => {
    const st = form.elements.stage; st.innerHTML = META.stages[e.target.value].map(s => opt(s, s, "")).join("");
  });
  if (entity === "deals") form.elements.project_id.addEventListener("change", e => {
    const p = refs.projects.find(x => x.id == e.target.value);
    if (p) { form.elements.pipeline.value = "developer"; form.elements.pipeline.dispatchEvent(new Event("change")); if (p.issuer_id && !form.elements.issuer_id.value) form.elements.issuer_id.value = p.issuer_id; }
  });
  $("#fcancel").addEventListener("click", () => dlg.close());
  $("#fdel")?.addEventListener("click", async () => { if (confirm(`Delete this ${E.label.toLowerCase()}?`)) { await api("DELETE", `/${entity}/${rec.id}`); dlg.close(); if (E.detail) location.hash = `#/${entity}`; else route(); } });
  form.addEventListener("submit", async e => {
    e.preventDefault();
    const body = {};
    for (const f of E.fields) {
      const el = form.elements[f.k]; if (!el) continue;
      body[f.k] = f.type === "bool" ? (el.checked ? 1 : 0) : el.value === "" ? null : (f.type === "number" || f.type === "ref" || f.k === "probability") ? +el.value : el.value;
    }
    if (entity === "people") body.links = [...form.querySelectorAll(".linkrow")].map(row => ({
      issuer_id: +row.querySelector(".lk-issuer").value || null,
      groups: [...row.querySelectorAll("input:checked")].map(i => i.value) })).filter(l => l.issuer_id);
    if (entity === "issuers") body.extra = Object.fromEntries((SECTOR_FIELDS[body.sector] || []).map(([k, , t]) => { const v = form.elements["x_" + k].value; return [k, v === "" ? null : t === "number" ? +v : v]; }));
    try {
      if (editing) await api("PUT", `/${entity}/${rec.id}`, body); else await api("POST", "/" + entity, body);
      dlg.close(); route();
    } catch (err) { $("#ferr").textContent = err.message; }
  });
  dlg.showModal();
}

// ------------------------------------------------------------------- routing
async function route() {
  const [page = "dashboard", id] = (location.hash.slice(2) || "dashboard").split("/");
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.nav === page || (page === "deals" && a.dataset.nav === "deals")));
  const main = $("#main");
  try {
    META ??= await api("GET", "/meta");
    if (pages[page]) await pages[page](main, id);
    else if (ENT[page]?.detail) id ? await detailPage(main, page, id) : await listPage(main, page);
    else location.hash = "#/dashboard";
  } catch (err) { main.innerHTML = `<div class="panel" style="color:var(--danger)">${esc(err.message)}</div>`; }
}
window.addEventListener("hashchange", route);

document.addEventListener("click", async e => {
  const t = e.target.closest("[data-edit],[data-add],[data-log],[data-del]");
  if (!t) return;
  try {
    if (t.dataset.edit) { e.preventDefault(); const [en, id] = t.dataset.edit.split(":"); await openForm(en, await api("GET", `/${en}/${id}`)); }
    else if (t.dataset.add) { await openForm(t.dataset.add, {}, t.dataset.prefill ? JSON.parse(t.dataset.prefill) : {}); }
    else if (t.dataset.log) { await openForm("interactions", {}, { person_id: +t.dataset.log }); }
    else if (t.dataset.del) {
      const [en, id] = t.dataset.del.split(":");
      if (confirm(`Delete this ${ENT[en].label.toLowerCase()}? This also removes related interaction history.`)) { await api("DELETE", `/${en}/${id}`); location.hash = `#/${en}`; }
    }
  } catch (err) { alert(err.message); }
});
document.addEventListener("change", async e => {
  if (!e.target.dataset.move) return;
  try { await api("PUT", `/deals/${e.target.dataset.move}`, { stage: e.target.value }); route(); } catch (err) { alert(err.message); route(); }
});

route();
