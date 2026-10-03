/* Guided tour for the browser demo. Demo-only: it is not part of the real app.
   Spotlights a part of each screen, navigates between pages, and explains what the viewer is looking at. */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const ss = { get: k => { try { return sessionStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { } } };
  const panel = prefix => $$("#main .panel").find(p => (p.querySelector("h2")?.textContent || "").trim().startsWith(prefix)) || null;
  const firstPanels = n => { const ps = $$("#main .panel"); return ps.length >= n ? ps.slice(0, n) : null; };
  const setDashView = async v => {
    const b = await waitFor(() => $(`#seg-dash [data-v=${v}]`));
    if (b && !b.classList.contains("on")) b.click();
  };

  const STEPS = [
    { route: "#/dashboard", expect: "Dashboard", center: true, title: "Welcome to the Public Finance CRM demo",
      body: "A CRM built around how a public finance banker works: issuers first, then their people, then your pipeline. Everything here is fictional sample data, and it runs entirely in your browser. Want a one-minute tour?",
      buttons: [{ label: "Explore on my own", act: "end" }, { label: "Take the tour", act: "next", primary: 1 }] },
    { route: "#/dashboard", expect: "Dashboard", title: "Your Monday screen",
      body: "Overdue follow-ups come first, ranked by priority. The cadence is automatic (A-list every 30 days, B every 90, C every 180) and you can override it with a specific date on anyone. One click logs the contact.",
      target: () => panel("Overdue") },
    { route: "#/dashboard", expect: "Dashboard", title: "Dates that matter",
      body: "Elections, budget adoptions, bond elections, charter renewals, term expirations, RFP deadlines and expected pricing dates, plus birthdays and anniversaries. Each date can start reminding you weeks ahead.",
      before: () => setDashView("list"), target: () => $("#body-dash table") && panel("Dates") },
    { route: "#/dashboard", expect: "Dashboard", title: "...or see it as a calendar",
      body: "Same dates on a month grid, color-coded by type. Click a day for details, or hover a day and press + to add a date. This List / Calendar switch is on the dashboard and on the Dates page.",
      before: () => setDashView("calendar"), target: () => $("#body-dash .cal") },
    { route: "#/deals/standard", expect: "Pipeline", title: "Pipeline as a list",
      body: "Every financing with stage, par, probability, RFP due date, municipal advisor and bond counsel. Change a stage right in the row, filter by stage, sort any column. Developer deals get their own tab with their own stages (validation, internal committee, and so on).",
      target: () => $("#tbl table") && $("#tbl") },
    { route: "#/issuers/1", expect: "City of Riverbend", title: "Issuer, then people",
      body: "Each issuer page splits its contacts into Elected, Staff and Related. A person can be in more than one group and linked to more than one issuer, like bond counsel who covers several. The primary banker and your coverage banker are tracked on the issuer.",
      target: () => { const ps = $$("#related .panel"); return ps.length >= 3 ? ps.slice(0, 3) : null; } },
    { route: "#/issuers/1", expect: "City of Riverbend", title: "Developer projects link to issuers",
      body: "A developer's project connects to the district, city or county behind it, so you can see who is pitching there. This section only appears when a project is actually linked.",
      target: () => panel("Developer projects behind") },
    { route: "#/people/2", expect: "Marcus Ellery", title: "Relationship details",
      body: "Who they report to, term dates, birthday, spouse and kids, personal notes, and a log of every interaction. Logging a call or meeting resets the follow-up clock automatically.",
      target: () => { const ps = $$("#main .panel"); return ps.length >= 2 ? ps.slice(0, 2) : null; } },
    { route: "#/import", expect: "Import contacts", title: "Bring your contacts in",
      body: "Export from Outlook or Excel as a CSV. The import previews first, creates issuers from the organization column, guesses sector and group from names and titles, and skips duplicates.",
      target: () => firstPanels(1) },
    { route: "#/settings", expect: "Settings", title: "Settings and the Monday digest",
      body: "Tune the follow-up cadence, and preview the weekly email digest: overdue follow-ups, the next two weeks of dates, and pipeline totals. In the local version it can be emailed to you on a schedule.",
      target: () => firstPanels(2) },
    { route: "#/dashboard", expect: "Dashboard", center: true, title: "That's the tour",
      body: "Everything here is clickable. Try adding a contact or moving a deal to a new stage. Nothing is saved, and reloading resets the demo.",
      before: () => setDashView("list"),
      buttons: [{ label: "Restart tour", act: "restart" }, { label: "Explore the demo", act: "end", primary: 1 }] },
  ];

  let root, spot, card, cur = -1, token = 0, els = null, initialView = null;

  async function waitFor(fn, ms = 6000) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { const v = fn(); if (v) return v; await sleep(80); }
    return null;
  }
  const asList = v => (!v ? null : Array.isArray(v) ? v : [v]);
  const union = list => {
    const rs = list.map(e => e.getBoundingClientRect());
    const left = Math.min(...rs.map(r => r.left)), top = Math.min(...rs.map(r => r.top));
    const right = Math.max(...rs.map(r => r.right)), bottom = Math.max(...rs.map(r => r.bottom));
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  };

  function build() {
    root = document.createElement("div");
    root.id = "tour-root";
    root.innerHTML = '<div id="tour-block"></div><div id="tour-spot"></div><div id="tour-card" role="dialog" aria-modal="true" aria-live="polite"></div>';
    document.body.appendChild(root);
    spot = $("#tour-spot"); card = $("#tour-card");
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, { passive: true });
    document.addEventListener("keydown", onKey);
  }

  function end() {
    token++;
    root?.remove(); root = null; cur = -1;
    window.removeEventListener("resize", reposition);
    window.removeEventListener("scroll", reposition);
    document.removeEventListener("keydown", onKey);
    try { initialView ? localStorage.setItem("view:dashboard", initialView) : localStorage.removeItem("view:dashboard"); } catch { }
  }

  function onKey(e) {
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight" && cur < STEPS.length - 1) show(cur + 1);
    else if (e.key === "ArrowLeft" && cur > 1) show(cur - 1);
  }

  function renderCard(s, n) {
    const tourSteps = STEPS.length - 2;
    const counter = s.center ? "" : `<div class="tour-count">${n} of ${tourSteps}</div>`;
    const btns = s.buttons || [{ label: "Back", act: "back", off: n <= 1 }, { label: n === tourSteps ? "Finish" : "Next", act: "next", primary: 1 }];
    const dots = s.center ? "" : `<div class="tour-dots">${Array.from({ length: tourSteps }, (_, i) => `<i class="${i + 1 === n ? "on" : ""}"></i>`).join("")}</div>`;
    card.innerHTML = `<button class="tour-x" data-act="end" aria-label="Close tour">&times;</button>${counter}<h3>${s.title}</h3><p>${s.body}</p>
      ${dots}<div class="tour-btns">${btns.map(b => `<button class="btn ${b.primary ? "primary" : ""}" data-act="${b.act}" ${b.off ? "disabled" : ""}>${b.label}</button>`).join("")}</div>`;
    card.querySelector(".primary")?.focus({ preventScroll: true });
  }

  function reposition() {
    if (!root) return;
    const block = $("#tour-block");
    if (!els) {  // no target: dim the whole page and centre the card
      spot.style.display = "none"; block.classList.add("dim");
      const cw = Math.min(440, innerWidth - 24); card.style.width = cw + "px";
      card.style.left = (innerWidth - cw) / 2 + "px"; card.style.top = Math.max(16, (innerHeight - card.offsetHeight) / 2.4) + "px";
      return;
    }
    block.classList.remove("dim");
    const r = union(els), pad = 8;
    const top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, innerHeight - 4);
    const left = Math.max(r.left - pad, 4), right = Math.min(r.right + pad, innerWidth - 4);
    Object.assign(spot.style, { display: "block", left: left + "px", top: top + "px", width: Math.max(right - left, 0) + "px", height: Math.max(bottom - top, 0) + "px" });
    const cw = Math.min(380, innerWidth - 24); card.style.width = cw + "px";
    const ch = card.offsetHeight;
    let cx = Math.min(Math.max(left, 12), innerWidth - cw - 12), cy;
    if (bottom + 14 + ch <= innerHeight - 8) cy = bottom + 14;
    else if (top - 14 - ch >= 8) cy = top - 14 - ch;
    else { cy = innerHeight - ch - 16; cx = innerWidth - cw - 16; }  // very large target: dock in the corner
    card.style.left = cx + "px"; card.style.top = cy + "px";
  }

  async function show(n) {
    const my = ++token, s = STEPS[n];
    cur = n;
    if (!root) build();
    if (s.route && location.hash !== s.route) location.hash = s.route;
    await waitFor(() => !s.expect || ($("#main h1")?.textContent || "").includes(s.expect));
    if (my !== token) return;
    if (s.before) await s.before();
    if (my !== token) return;
    els = s.target ? asList(await waitFor(() => s.target())) : null;
    if (my !== token) return;
    if (els) {
      const tall = union(els).height > innerHeight * 0.7;
      els[0].scrollIntoView({ block: tall ? "start" : "center", behavior: "instant" });
      await sleep(60);
    }
    renderCard(s, n);
    reposition();
  }

  document.addEventListener("click", e => {
    const a = e.target.closest("#tour-card [data-act]");
    if (a) {
      const act = a.dataset.act;
      if (act === "next") show(cur + 1);
      else if (act === "back") show(cur - 1);
      else if (act === "restart") show(1);
      else if (act === "end") end();
      return;
    }
    if (e.target.closest("#demo-tour-link")) { e.preventDefault(); start(1); }
  });

  function start(from) {
    try { initialView = localStorage.getItem("view:dashboard"); } catch { }
    ss.set("tourSeen", "1");
    show(from);
  }

  // Offer the tour once per browser session, as soon as the demo has finished loading.
  (async () => {
    await waitFor(() => !$("#demo-loading") && $("#main h1"), 90000);
    if (!ss.get("tourSeen")) start(0);
  })();
})();
