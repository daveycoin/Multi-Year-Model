"use strict";
/* Tasks, global search, saved views, activity timeline, and reports & charts.
   Loaded after app.js and shares its helpers ($, esc, api, link, chip, money, ENT, pages ...). */

const parFmt = n => money(n) || "$0";

// ----------------------------------------------------------------- timeline
function timelineHTML(items, empty = "No activity yet.") {
  if (!items.length) return `<div class="empty">${empty}</div>`;
  const rows = items.map(i => {
    let text = esc(i.text);
    if (i.edit) text = editLink(i.edit.entity, i.edit.id, i.text);
    else if (i.link) text = EDIT_ONLY.includes(i.link.entity) ? editLink(i.link.entity, i.link.id, i.text) : link(i.link.entity, i.link.id, i.text);
    const who = i.person_name && i.edit ? ` <span class="muted">· ${link("people", i.person_id, i.person_name)}</span>` : "";
    return `<tr><td class="tl-date">${fdate(i.date)}</td><td>${chip(i.kind)}</td><td>${text}${who}</td></tr>`;
  }).join("");
  return `<div class="tablewrap"><table class="tl"><tbody>${rows}</tbody></table></div>`;
}

// -------------------------------------------------------------------- tasks
function dashTasksHTML(tasks) {
  if (!tasks.length) return '<div class="empty">Nothing due in the next 7 days.</div>';
  const rows = tasks.map(t => {
    const who = t.person_id ? link("people", t.person_id, t.person_name) : t.issuer_id ? link("issuers", t.issuer_id, t.issuer_name) : esc(t.deal_name || "");
    const when = t.days < 0 ? `${-t.days}d overdue` : t.days === 0 ? "today" : `in ${t.days}d`;
    return `<tr><td style="width:28px"><input type="checkbox" data-done="${t.id}" aria-label="Mark done"></td>
      <td>${editLink("tasks", t.id, t.title)}${t.priority === "High" ? " " + chip("High", "warn") : ""}</td>
      <td class="muted">${who}</td><td>${chip(when, t.days < 0 ? "bad" : "")}</td></tr>`;
  }).join("");
  return `<div class="tablewrap"><table><tbody>${rows}</tbody></table></div>`;
}

pages.tasks = async main => {
  const rows = await api("GET", "/tasks"), cols = ENT.tasks.cols();
  main.innerHTML = `<div class="head"><div><h1>Tasks</h1><div class="sub" id="count"></div></div>
    <button class="btn primary" data-add="tasks">+ Add task</button></div>
    <div class="toolbar"><input id="q" type="search" placeholder="Search tasks..."><select id="f-status">
      <option value="open">Open</option><option value="done">Done</option><option value="all">All</option></select><span class="views" id="views"></span></div>
    <div class="panel" id="tbl"></div>`;
  const draw = () => {
    const q = $("#q").value.toLowerCase(), st = $("#f-status").value, today = todayISO();
    const shown = rows.filter(r => (st === "all" || (st === "done") === !!r.done) && (!q || JSON.stringify(Object.values(r)).toLowerCase().includes(q)));
    const late = shown.filter(r => !r.done && r.due_date && r.due_date < today).length;
    $("#count").textContent = `${shown.length} tasks${late ? ` · ${late} overdue` : ""}`;
    $("#tbl").innerHTML = table(cols, shown, st === "open" ? "No open tasks. Nice." : "No tasks match.");
    sortable($("#tbl"), cols, shown);
  };
  $("#q").addEventListener("input", draw); $("#f-status").addEventListener("change", draw); draw();
  await mountViews($("#views"), "tasks", () => ({ q: $("#q").value, status: $("#f-status").value }),
    st => { $("#q").value = st.q || ""; $("#f-status").value = st.status || "open"; draw(); });
};

// -------------------------------------------------------------- saved views
async function mountViews(host, page, getState, applyState) {
  const render = async (selectId) => {
    const views = await api("GET", `/saved_views?page=${encodeURIComponent(page)}`);
    host.innerHTML = `<select aria-label="Saved views"><option value="">Saved views…</option>${views.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join("")}</select>
      <button class="btn sm" data-sv="save">Save view</button> <button class="btn sm danger" data-sv="del" hidden>Delete view</button>`;
    const sel = host.querySelector("select"), del = host.querySelector('[data-sv="del"]');
    if (selectId) { sel.value = String(selectId); del.hidden = false; }
    sel.onchange = () => {
      const v = views.find(x => String(x.id) === sel.value);
      del.hidden = !v;
      if (v) applyState(v.state || {});
    };
    host.querySelector('[data-sv="save"]').onclick = async () => {
      const name = prompt("Name this view (it saves the current search and filters):");
      if (!name || !name.trim()) return;
      try { const row = await api("POST", "/saved_views", { page, name: name.trim(), state: getState() }); await render(row.id); } catch (err) { alert(err.message); }
    };
    del.onclick = async () => {
      if (!confirm("Delete this saved view?")) return;
      try { await api("DELETE", `/saved_views/${sel.value}`); await render(); } catch (err) { alert(err.message); }
    };
  };
  await render();
}

// ------------------------------------------------------------- global search
const DETAIL_PAGES = ["issuers", "people", "developers", "projects"];
const searchHit = (g, r) => {
  const body = `<b>${esc(r.title)}</b><span>${esc(r.sub)}</span>`;
  return DETAIL_PAGES.includes(g.entity) ? `<a href="#/${g.entity}/${r.id}" class="gs-hit">${body}</a>`
    : `<a href="#" data-edit="${g.entity}:${r.id}" class="gs-hit">${body}</a>`;
};

(function initSearch() {
  const input = $("#gs");
  if (!input) return;
  const pop = document.createElement("div");
  pop.id = "gs-pop"; pop.hidden = true;
  document.body.appendChild(pop);
  let timer = 0, seq = 0, active = -1;
  const hide = () => { pop.hidden = true; active = -1; };
  const hits = () => [...pop.querySelectorAll(".gs-hit, .gs-all")];
  const mark = () => hits().forEach((el, i) => el.classList.toggle("active", i === active));
  const place = () => { const r = input.getBoundingClientRect(); pop.style.left = Math.max(8, r.left) + "px"; pop.style.top = r.bottom + 6 + "px"; };
  const openAll = q => { hide(); location.hash = "#/search/" + encodeURIComponent(q); };

  async function run() {
    const q = input.value.trim(), my = ++seq;
    if (!q) return hide();
    let res;
    try { res = await api("GET", `/search?q=${encodeURIComponent(q)}&limit=5`); } catch { return; }
    if (my !== seq) return;
    place(); pop.hidden = false; active = -1;
    pop.innerHTML = res.total
      ? res.groups.map(g => `<div class="gs-group"><h4>${esc(g.label)}</h4>${g.results.map(r => searchHit(g, r)).join("")}</div>`).join("")
        + `<a href="#/search/${encodeURIComponent(q)}" class="gs-all">See all results</a>`
      : `<div class="gs-none">No matches for “${esc(q)}”.</div>`;
  }
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 150); });
  input.addEventListener("focus", () => { if (input.value.trim() && pop.hidden) run(); });
  input.addEventListener("keydown", e => {
    const list = hits();
    if (e.key === "ArrowDown" && list.length) { e.preventDefault(); active = (active + 1) % list.length; mark(); list[active].scrollIntoView({ block: "nearest" }); }
    else if (e.key === "ArrowUp" && list.length) { e.preventDefault(); active = (active - 1 + list.length) % list.length; mark(); list[active].scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); if (active >= 0 && list[active]) { list[active].click(); } else if (input.value.trim()) openAll(input.value.trim()); }
    else if (e.key === "Escape") { hide(); input.blur(); }
  });
  pop.addEventListener("click", e => { if (e.target.closest("a")) setTimeout(hide, 0); });
  document.addEventListener("click", e => { if (!pop.hidden && !e.target.closest("#gs-pop, #gs")) hide(); });
  document.addEventListener("keydown", e => {  // "/" jumps to search, like GitHub and Gmail
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) && !$("#dlg[open]")) { e.preventDefault(); input.focus(); input.select(); }
  });
  window.addEventListener("resize", () => { if (!pop.hidden) place(); });
})();

pages.search = async (main, raw) => {
  const q = decodeURIComponent(raw || "");
  if ($("#gs")) $("#gs").value = q;
  const res = await api("GET", `/search?q=${encodeURIComponent(q)}&limit=50`);
  main.innerHTML = `<div class="head"><div><h1>Search</h1><div class="sub">${res.total} result${res.total === 1 ? "" : "s"} for “${esc(q)}”</div></div></div>`
    + (res.groups.map(g => `<div class="panel"><div class="head"><h2>${esc(g.label)} (${g.results.length})</h2></div><div class="gs-list">${g.results.map(r => searchHit(g, r)).join("")}</div></div>`).join("")
      || '<div class="panel"><div class="empty">No matches. Search looks at names, titles, notes, bankers, advisors, counsel and more.</div></div>');
};

// ---------------------------------------------------------------- charts
// Marks follow the dataviz spec: thin (<=24px) bars with a rounded data-end and a square baseline, a 2px gap
// between touching marks, text in text colors (never the series color), and a legend whenever there are 2+ series.
const legendHTML = series => series.length < 2 ? "" :
  `<div class="lg">${series.map((s, i) => `<span><i style="background:var(--series-${i + 1})"></i>${esc(s)}</span>`).join("")}</div>`;

function hbars(items, fmt = parFmt) {
  if (!items.length || items.every(i => !i.value)) return '<div class="empty">Nothing to chart yet.</div>';
  const max = Math.max(...items.map(i => i.value), 1);
  return `<div class="hbars">${items.map(i => `<div class="hb" title="${esc(i.label)}: ${esc(fmt(i.value))}">
    <div class="hb-l">${esc(i.label)}</div><div class="hb-t"><div class="hb-b" style="width:${i.value ? Math.max(i.value / max * 100, 1.5) : 0}%"></div></div>
    <div class="hb-v">${esc(fmt(i.value))}</div></div>`).join("")}</div>`;
}

function stackedBars(items, series, fmt = parFmt) {  // items: [{label, values:[a, b]}]
  const totals = items.map(i => i.values.reduce((a, b) => a + b, 0)), max = Math.max(...totals, 1);
  if (!totals.some(Boolean)) return '<div class="empty">Nothing to chart yet.</div>';
  return `<div class="hbars">${items.map((i, n) => `<div class="hb" title="${esc(i.label)}: ${series.map((s, k) => `${s} ${fmt(i.values[k])}`).join(", ")}">
    <div class="hb-l">${esc(i.label)}</div><div class="hb-t stack">${i.values.map((v, k) => v ? `<div class="hb-b s${k + 1}" style="width:${v / max * 100}%"></div>` : "").join("")}</div>
    <div class="hb-v">${esc(fmt(totals[n]))}</div></div>`).join("")}</div>`;
}

function columns(items, series, fmt = parFmt, labelAll = true) {  // items: [{label, values:[...]}]
  const flat = items.flatMap(i => i.values), max = Math.max(...flat, 1);
  if (!flat.some(Boolean)) return '<div class="empty">Nothing to chart yet.</div>';
  const peak = flat.indexOf(Math.max(...flat)), last = items.length - 1;
  return `<div class="cols" style="--n:${items.length}">${items.map((i, n) => `<div class="cg" title="${esc(i.label)}: ${series.map((s, k) => `${s} ${fmt(i.values[k])}`).join(", ")}">
    <div class="cg-bars">${i.values.map((v, k) => {
      const show = series.length === 1 && (labelAll || flat.indexOf(v) === peak || n === last);
      return `<div class="cb"><span class="cv">${v && show ? esc(fmt(v)) : ""}</span><div class="cplot"><div class="cbar s${k + 1}" style="height:${v ? Math.max(v / max * 100, 2) : 0}%"></div></div></div>`;
    }).join("")}</div><div class="cl">${esc(i.label)}${i.sub ? `<small>${esc(i.sub)}</small>` : ""}${series.length > 1
      ? `<div class="cvals">${i.values.map((v, k) => `<span><i style="background:var(--series-${k + 1})"></i>${esc(fmt(v))}</span>`).join("")}</div>` : ""}</div></div>`).join("")}</div>`;
}

const dataTable = (heads, rows) => rows.length
  ? `<div class="tablewrap"><table><thead><tr>${heads.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
  : '<div class="empty">No data.</div>';

function chartCard(title, sub, chart, tableHTML, legend = "", panel = true) {
  return `<div class="${panel ? "panel " : ""}cc" data-view="chart"><div class="head"><div><h2>${esc(title)}</h2><div class="muted">${sub}</div></div>
    <span class="seg"><button class="on" data-cc="chart">Chart</button><button data-cc="table">Table</button></span></div>
    ${legend}<div class="cc-chart">${chart}</div><div class="cc-table">${tableHTML}</div></div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-cc]");
  if (!b) return;
  const card = b.closest(".cc");
  card.dataset.view = b.dataset.cc;
  card.querySelectorAll("[data-cc]").forEach(x => x.classList.toggle("on", x === b));
});

const shortMonth = ym => { const [y, m] = ym.split("-"); return `${MONTHS[+m - 1]} ${y.slice(2)}`; };
const monthCols = list => list.map((m, n) => { const [y, mo] = m.label.split("-"); return { label: MONTHS[+mo - 1], sub: n === 0 || mo === "01" ? y : "", values: [m.count] }; });

// ---------------------------------------------------------------- reports
const BUILDER = {
  deals: { label: "Financings", measures: [["count", "Number of financings"], ["par", "Total par"], ["weighted", "Probability-weighted par"]],
    groups: [["stage", "Stage"], ["sector", "Issuer sector"], ["issuer", "Issuer"], ["pipeline", "Pipeline"], ["purpose", "Purpose"], ["security", "Security type"],
      ["role", "Our role"], ["ma", "Municipal advisor"], ["bond_counsel", "Bond counsel"], ["trustee", "Trustee"], ["quarter", "Expected pricing quarter"],
      ["year", "Expected pricing year"], ["probability", "Probability"]] },
  people: { label: "People", measures: [["count", "Number of people"]],
    groups: [["priority", "Priority"], ["group", "Group (Elected / Staff / Related)"], ["sector", "Primary issuer's sector"], ["issuer", "Primary issuer"]] },
  issuers: { label: "Issuers", measures: [["count", "Number of issuers"]],
    groups: [["sector", "Sector"], ["state", "State"], ["primary_banker", "Primary banker"], ["coverage", "Our coverage banker"], ["fiscal_year_end", "Fiscal year end"]] },
};

pages.reports = async main => {
  const r = await api("GET", "/reports"), k = r.kpis, year = new Date().getFullYear();
  const tile = (value, label, note = "") => `<div class="stat"><b>${value}</b><span>${label}</span>${note ? `<span class="note">${note}</span>` : ""}</div>`;
  const stageCard = (key, title) => {
    const st = r.pipeline[key].stages.filter(s => s.count && !INACTIVE.includes(s.stage));
    return chartCard(title, `Active par ${parFmt(r.pipeline[key].active_par)} · weighted ${parFmt(r.pipeline[key].weighted_par)}`,
      hbars(st.map(s => ({ label: `${s.stage} (${s.count})`, value: s.par }))),
      dataTable(["Stage", "Financings", "Par"], st.map(s => [esc(s.stage), s.count, parFmt(s.par)])));
  };
  const quarters = r.by_quarter, outcomes = r.outcomes;
  const stale = r.stale.map(s => [link("issuers", s.id, s.name), esc(s.sector), esc(s.primary_banker || ""),
    s.last_contact ? fdate(s.last_contact) : '<span class="muted">never</span>',
    s.days == null ? "–" : chip(`${s.days}d`, s.days >= 120 ? "bad" : "warn"),
    s.n_active ? `${s.n_active} · ${parFmt(s.active_par)}` : '<span class="muted">none</span>']);
  main.innerHTML = `<div class="head"><div><h1>Reports</h1><div class="sub">Where the pipeline stands, how deals have turned out, and who needs attention.</div></div></div>
    <div class="stats">${tile(parFmt(k.active_par), "active pipeline")}${tile(parFmt(k.weighted_par), "probability-weighted")}
      ${tile(parFmt(k.closed_ytd_par), `closed in ${year}`)}${tile(k.win_rate == null ? "–" : k.win_rate + "%", "win rate", `${k.won} closed, ${k.lost} lost`)}
      ${tile(k.open_tasks, "open tasks")}${tile(k.overdue_followups, "overdue follow-ups")}</div>
    <div class="grid2">${stageCard("standard", "Issuer financings by stage")}${stageCard("developer", "Developer deals by stage")}</div>
    <div class="grid2">
      ${chartCard("Active pipeline by issuer sector", "Total par of financings still in play",
        hbars(r.by_sector.map(s => ({ label: `${s.label} (${s.count})`, value: s.par }))),
        dataTable(["Sector", "Financings", "Par", "Weighted"], r.by_sector.map(s => [esc(s.label), s.count, parFmt(s.par), parFmt(s.weighted)])))}
      ${chartCard("Forecast by expected pricing quarter", "Par and probability-weighted par of active financings",
        columns(quarters.map(q => ({ label: q.label, values: [q.par, q.weighted] })), ["Par", "Probability-weighted"]),
        dataTable(["Quarter", "Financings", "Par", "Weighted"], quarters.map(q => [esc(q.label), q.count, parFmt(q.par), parFmt(q.weighted)])),
        legendHTML(["Par", "Probability-weighted"]))}
    </div>
    <div class="grid2">
      ${chartCard("Closed vs. lost by year", k.win_rate == null ? "No closed or lost financings yet" : `Win rate ${k.win_rate}% by count (${k.won} closed, ${k.lost} lost). Year = date closed or lost.`,
        stackedBars(outcomes.map(y => ({ label: y.label, values: [y.closed_par, y.lost_par] })), ["Closed", "Lost"]),
        dataTable(["Year", "Closed", "Closed par", "Lost", "Lost par"], outcomes.map(y => [esc(y.label), y.closed_count, parFmt(y.closed_par), y.lost_count, parFmt(y.lost_par)])),
        legendHTML(["Closed", "Lost"]))}
      ${chartCard("Contacts logged per month", "Calls, meetings and emails you logged over the last 12 months",
        columns(monthCols(r.activity), ["Interactions"], num, false),
        dataTable(["Month", "Interactions"], r.activity.map(m => [esc(shortMonth(m.label)), m.count])))}
    </div>
    <div class="panel"><div class="head"><div><h2>Relationships that need attention (${r.stale.length})</h2>
      <div class="muted">Issuers with contacts or active deals and no logged contact in ${r.stale_days}+ days. Active deals first.</div></div></div>
      ${r.stale.length ? dataTable(["Issuer", "Sector", "Primary banker", "Last contact", "Days", "Active deals · par"], stale) : '<div class="empty">Every relationship has been touched recently.</div>'}</div>
    <div class="panel" id="builder"><div class="head"><div><h2>Build your own report</h2><div class="muted">Choose what to look at and how to group it.</div></div><span class="views" id="rv"></span></div>
      <div class="toolbar"><select id="rb-entity">${Object.entries(BUILDER).map(([v, b]) => `<option value="${v}">${b.label}</option>`).join("")}</select>
        <label class="inl">Group by <select id="rb-group"></select></label><label class="inl">Measure <select id="rb-measure"></select></label>
        <span id="rb-deals"><label class="chk"><input type="checkbox" id="rb-active" checked> Active only</label>
        <select id="rb-pipeline"><option value="">Both pipelines</option><option value="standard">Issuer financings</option><option value="developer">Developer deals</option></select></span>
        <button class="btn sm" id="rb-csv">Download CSV</button></div><div id="rb-out"></div></div>`;
  initBuilder();
};

function initBuilder() {
  let last = null;
  const entity = $("#rb-entity"), group = $("#rb-group"), measure = $("#rb-measure");
  const fill = (el, pairs, keep) => { el.innerHTML = pairs.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join(""); if (keep && pairs.some(p => p[0] === keep)) el.value = keep; };
  const sync = () => {
    const b = BUILDER[entity.value];
    fill(group, b.groups, group.value); fill(measure, b.measures, measure.value);
    $("#rb-deals").hidden = entity.value !== "deals";
  };
  async function run() {
    const q = new URLSearchParams({ entity: entity.value, group: group.value, measure: measure.value, active: $("#rb-active").checked ? "1" : "0", pipeline: $("#rb-pipeline").value });
    try { last = await api("GET", `/report?${q}`); } catch (err) { $("#rb-out").innerHTML = `<div class="empty" style="color:var(--danger)">${esc(err.message)}</div>`; return; }
    const money_ = last.measure !== "count", fmt = money_ ? parFmt : num;
    const gLabel = BUILDER[last.entity].groups.find(g => g[0] === last.group)[1], mLabel = BUILDER[last.entity].measures.find(m => m[0] === last.measure)[1];
    const timey = ["year", "quarter"].includes(last.group);
    const chart = timey ? columns(last.rows.map(x => ({ label: x.label, values: [x.value] })), [mLabel], fmt) : hbars(last.rows.map(x => ({ label: x.label, value: x.value })), fmt);
    const heads = last.entity === "deals" ? [gLabel, "Financings", "Par", "Weighted"] : [gLabel, "Count"];
    const rows = last.rows.map(x => last.entity === "deals" ? [esc(x.label), x.count, parFmt(x.par), parFmt(x.weighted)] : [esc(x.label), x.count]);
    $("#rb-out").innerHTML = chartCard(`${mLabel} by ${gLabel.toLowerCase()}`, `Total ${esc(fmt(last.total) || "0")}`, chart, dataTable(heads, rows), "", false);
  }
  const state = () => ({ entity: entity.value, group: group.value, measure: measure.value, active: $("#rb-active").checked, pipeline: $("#rb-pipeline").value });
  const apply = st => {
    entity.value = BUILDER[st.entity] ? st.entity : "deals"; sync();
    if (st.group) group.value = st.group; if (st.measure) measure.value = st.measure;
    $("#rb-active").checked = st.active !== false; $("#rb-pipeline").value = st.pipeline || ""; run();
  };
  entity.addEventListener("change", () => { sync(); run(); });
  [group, measure, $("#rb-active"), $("#rb-pipeline")].forEach(el => el.addEventListener("change", run));
  $("#rb-csv").addEventListener("click", () => {
    if (!last) return;
    const deals = last.entity === "deals", q = v => `"${String(v).replace(/"/g, '""')}"`;
    const lines = [(deals ? ["Group", "Financings", "Par", "Probability-weighted par"] : ["Group", "Count"]).map(q).join(",")]
      .concat(last.rows.map(x => (deals ? [x.label, x.count, x.par, x.weighted] : [x.label, x.count]).map(q).join(",")));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv" }));
    a.download = `report-${last.entity}-by-${last.group}.csv`; a.click();
  });
  sync(); run();
  mountViews($("#rv"), "report", state, apply);
}
