#!/usr/bin/env python3
"""Public finance CRM: local, single-user proof of concept.

Standard library only. Run:  python3 server.py [--port 8765] [--demo]
Data lives in ./data/crm.db (SQLite). Binds to 127.0.0.1 only.
"""
import argparse
import csv
import datetime as dt
import html
import io
import json
import mimetypes
import os
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DB_PATH = os.environ.get("PFCRM_DB", os.path.join(HERE, "data", "crm.db"))

STAGES = {
    "standard": ["Idea", "Initial Conversation", "Structuring", "Proposal / RFP",
                 "Selected", "Pricing", "Closed", "Lost", "On Hold"],
    "developer": ["Developer Intro", "Project Scoped", "Entitlements / District Formation",
                  "Structuring", "Validation", "Internal Committee", "Approvals",
                  "Pricing", "Closed", "Lost", "On Hold"],
}
INACTIVE_STAGES = ("Closed", "Lost", "On Hold")
DEFAULT_SETTINGS = {"cadence_A": "30", "cadence_B": "90", "cadence_C": "180",
                    "dash_window": "30", "digest_window": "14"}
SECTORS = ["City", "County", "K-12 School District", "Higher Education", "Utility",
           "Private School", "Charter School", "Special District", "Other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS issuers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL DEFAULT 'City',
  state TEXT, primary_banker TEXT, our_coverage_banker TEXT, other_bankers TEXT,
  website TEXT, fiscal_year_end TEXT, notes TEXT, extra TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS developers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, website TEXT, phone TEXT, notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, title TEXT,
  issuer_id INTEGER REFERENCES issuers(id) ON DELETE SET NULL,
  developer_id INTEGER REFERENCES developers(id) ON DELETE SET NULL,
  email TEXT, phone TEXT, priority TEXT DEFAULT 'C',
  term_start TEXT, term_end TEXT,
  reports_to_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  last_contact TEXT, next_followup TEXT,
  birthday TEXT, anniversary TEXT, spouse TEXT, kids TEXT,
  personal_notes TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  developer_id INTEGER REFERENCES developers(id) ON DELETE SET NULL,
  issuer_id INTEGER REFERENCES issuers(id) ON DELETE SET NULL,
  structure TEXT, location TEXT, est_par REAL, notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS deals (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, pipeline TEXT NOT NULL DEFAULT 'standard',
  stage TEXT NOT NULL DEFAULT 'Idea',
  issuer_id INTEGER REFERENCES issuers(id) ON DELETE SET NULL,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  purpose TEXT, security_type TEXT, par REAL, expected_date TEXT, role TEXT,
  probability INTEGER, ma_name TEXT, bond_counsel TEXT, trustee TEXT,
  competing_banks TEXT, rfp_deadline TEXT, notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS key_dates (
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT, date TEXT NOT NULL,
  issuer_id INTEGER REFERENCES issuers(id) ON DELETE CASCADE,
  remind_days_before INTEGER DEFAULT 14, recurs_annually INTEGER DEFAULT 0,
  done INTEGER DEFAULT 0, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS interactions (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  issuer_id INTEGER REFERENCES issuers(id) ON DELETE SET NULL,
  date TEXT NOT NULL, type TEXT, notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_people_issuer ON people(issuer_id);
CREATE INDEX IF NOT EXISTS ix_deals_issuer ON deals(issuer_id);
CREATE INDEX IF NOT EXISTS ix_inter_person ON interactions(person_id);
"""

# Each table's list/detail query. Filters (?col=val) apply to the base table alias "t".
QUERIES = {
    "issuers": ("SELECT t.*, "
                "(SELECT COUNT(*) FROM people WHERE issuer_id=t.id) AS n_people, "
                "(SELECT COUNT(*) FROM deals WHERE issuer_id=t.id AND stage NOT IN ('Closed','Lost','On Hold')) AS n_active_deals "
                "FROM issuers t", "t.name COLLATE NOCASE"),
    "developers": ("SELECT t.*, "
                   "(SELECT COUNT(*) FROM projects WHERE developer_id=t.id) AS n_projects, "
                   "(SELECT COUNT(*) FROM people WHERE developer_id=t.id) AS n_people "
                   "FROM developers t", "t.name COLLATE NOCASE"),
    "people": ("SELECT t.*, i.name AS issuer_name, d.name AS developer_name, r.name AS reports_to_name "
               "FROM people t LEFT JOIN issuers i ON i.id=t.issuer_id "
               "LEFT JOIN developers d ON d.id=t.developer_id "
               "LEFT JOIN people r ON r.id=t.reports_to_id", "t.name COLLATE NOCASE"),
    "projects": ("SELECT t.*, d.name AS developer_name, i.name AS issuer_name "
                 "FROM projects t LEFT JOIN developers d ON d.id=t.developer_id "
                 "LEFT JOIN issuers i ON i.id=t.issuer_id", "t.name COLLATE NOCASE"),
    "deals": ("SELECT t.*, i.name AS issuer_name, p.name AS project_name "
              "FROM deals t LEFT JOIN issuers i ON i.id=t.issuer_id "
              "LEFT JOIN projects p ON p.id=t.project_id", "t.expected_date IS NULL, t.expected_date"),
    "key_dates": ("SELECT t.*, i.name AS issuer_name FROM key_dates t "
                  "LEFT JOIN issuers i ON i.id=t.issuer_id", "t.date"),
    "interactions": ("SELECT t.*, p.name AS person_name, i.name AS issuer_name FROM interactions t "
                     "LEFT JOIN people p ON p.id=t.person_id "
                     "LEFT JOIN issuers i ON i.id=t.issuer_id", "t.date DESC, t.id DESC"),
}


# --------------------------------------------------------------------------- db
def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    conn.commit()
    return conn


def row_dict(r):
    d = dict(r)
    if isinstance(d.get("extra"), str):
        try:
            d["extra"] = json.loads(d["extra"])
        except ValueError:
            d["extra"] = {}
    return d


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}


def table_columns(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def clean_body(conn, table, body):
    cols = set(table_columns(conn, table)) - {"id", "created_at"}
    out = {}
    for k, v in body.items():
        if k not in cols:
            continue
        if k == "extra" and isinstance(v, dict):
            v = json.dumps(v)
        if isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    return out


def list_rows(conn, table, filters=None, row_id=None):
    sql, order = QUERIES[table]
    cols = set(table_columns(conn, table))
    where, args = [], []
    if row_id is not None:
        where.append("t.id=?"); args.append(row_id)
    for k, v in (filters or {}).items():
        if k in cols:
            where.append(f"t.{k}=?"); args.append(v)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + order
    return [row_dict(r) for r in conn.execute(sql, args)]


def after_write(conn, table, row_id, body):
    """Cross-table side effects of a create/update."""
    if table == "deals":
        conn.execute("UPDATE deals SET issuer_id=(SELECT issuer_id FROM projects WHERE id=deals.project_id) "
                     "WHERE id=? AND issuer_id IS NULL AND project_id IS NOT NULL", (row_id,))


def create_row(conn, table, body):
    extra_followup = body.get("next_followup") if table == "interactions" else None
    data = clean_body(conn, table, body)
    if table == "deals":
        data.setdefault("pipeline", "standard")
        if data["pipeline"] not in STAGES:
            raise ValueError("unknown pipeline")
        if data.get("stage") and data["stage"] not in STAGES[data["pipeline"]]:
            raise ValueError(f"stage '{data['stage']}' is not valid for the {data['pipeline']} pipeline")
        data.setdefault("stage", STAGES[data["pipeline"]][0])
    if table == "interactions":
        data.setdefault("date", dt.date.today().isoformat())
        if data.get("person_id") and not data.get("issuer_id"):
            r = conn.execute("SELECT issuer_id FROM people WHERE id=?", (data["person_id"],)).fetchone()
            data["issuer_id"] = r["issuer_id"] if r else None
    cols = list(data)
    cur = conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                       [data[c] for c in cols])
    rid = cur.lastrowid
    if table == "interactions":
        pid, d = data["person_id"], data["date"]
        conn.execute("UPDATE people SET last_contact=? WHERE id=? AND (last_contact IS NULL OR last_contact<?)",
                     (d, pid, d))
        if extra_followup:
            conn.execute("UPDATE people SET next_followup=? WHERE id=?", (extra_followup, pid))
        else:  # a logged touch satisfies a follow-up that was due on or before it
            conn.execute("UPDATE people SET next_followup=NULL WHERE id=? AND next_followup<=?", (pid, d))
    after_write(conn, table, rid, data)
    conn.commit()
    return rid


def update_row(conn, table, rid, body):
    data = clean_body(conn, table, body)
    if table == "deals":
        cur = conn.execute("SELECT pipeline FROM deals WHERE id=?", (rid,)).fetchone()
        if not cur:
            raise LookupError("not found")
        pl = data.get("pipeline", cur["pipeline"])
        if pl not in STAGES:
            raise ValueError("unknown pipeline")
        if "stage" in data and data["stage"] not in STAGES[pl]:
            raise ValueError(f"stage '{data['stage']}' is not valid for the {pl} pipeline")
    if not data:
        return
    sets = ",".join(f"{c}=?" for c in data)
    cur = conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*data.values(), rid])
    if cur.rowcount == 0:
        raise LookupError("not found")
    after_write(conn, table, rid, data)
    conn.commit()


# ------------------------------------------------------------------------ dates
def parse_ymd(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def to_date(s):
    p = parse_ymd(s)
    if not p:
        return None
    try:
        return dt.date(*p)
    except ValueError:
        return None


def next_occurrence(s, today):
    """Next month/day anniversary of s on or after today (Feb 29 -> Feb 28 in common years)."""
    p = parse_ymd(s)
    if not p:
        return None
    _, mo, d = p
    for y in (today.year, today.year + 1):
        try:
            c = dt.date(y, mo, d)
        except ValueError:
            c = dt.date(y, mo, 28)
        if c >= today:
            return c


def build_events(conn, today, window):
    """Everything dated that the banker should see: key dates, term ends, birthdays,
    anniversaries, RFP deadlines, expected pricing dates."""
    out = []

    def add(d, kind, title, detail, link, remind=0):
        if d is None:
            return
        days = (d - today).days
        if days < -30 or days > max(window, remind):
            return
        out.append({"date": d.isoformat(), "days": days, "kind": kind, "title": title,
                    "detail": detail or "", "link": link, "reminder": bool(remind) and days <= remind})

    for k in conn.execute("SELECT k.*, i.name AS issuer_name FROM key_dates k "
                          "LEFT JOIN issuers i ON i.id=k.issuer_id WHERE k.done=0"):
        d = next_occurrence(k["date"], today) if k["recurs_annually"] else to_date(k["date"])
        link = {"entity": "issuers", "id": k["issuer_id"]} if k["issuer_id"] else None
        add(d, k["kind"] or "Date", k["title"], k["issuer_name"], link, k["remind_days_before"] or 0)

    for p in conn.execute("SELECT p.*, i.name AS issuer_name, d.name AS developer_name FROM people p "
                          "LEFT JOIN issuers i ON i.id=p.issuer_id LEFT JOIN developers d ON d.id=p.developer_id"):
        org = p["issuer_name"] or p["developer_name"] or ""
        link = {"entity": "people", "id": p["id"]}
        add(to_date(p["term_end"]), "Term Expiration", f"{p['name']}: term ends",
            f"{p['title'] or ''} {org}".strip(), link, 90)
        add(next_occurrence(p["birthday"], today), "Birthday", f"{p['name']}'s birthday", org, link)
        spouse = f" & {p['spouse']}" if p["spouse"] else ""
        add(next_occurrence(p["anniversary"], today), "Anniversary", f"{p['name']}{spouse}: anniversary", org, link)

    for d in conn.execute("SELECT d.*, i.name AS issuer_name FROM deals d LEFT JOIN issuers i ON i.id=d.issuer_id "
                          "WHERE d.stage NOT IN ('Closed','Lost','On Hold')"):
        link = {"entity": "deals", "id": d["id"]}
        add(to_date(d["rfp_deadline"]), "RFP Deadline", f"RFP due: {d['name']}", d["issuer_name"], link, 14)
        add(to_date(d["expected_date"]), "Expected Pricing", f"Expected pricing: {d['name']}", d["issuer_name"], link)

    out.sort(key=lambda e: (e["date"], e["title"]))
    return out


def overdue_followups(conn, today):
    s = get_settings(conn)
    cadence = {p: int(s.get(f"cadence_{p}", DEFAULT_SETTINGS[f"cadence_{p}"])) for p in "ABC"}
    out = []
    for p in list_rows(conn, "people"):
        if p["next_followup"]:  # a manual date overrides the cadence
            due, why = to_date(p["next_followup"]), "scheduled"
        elif p["last_contact"]:
            lc = to_date(p["last_contact"])
            due = lc + dt.timedelta(days=cadence.get(p["priority"] or "C", 180)) if lc else None
            why = f"{p['priority'] or 'C'}-list cadence"
        elif p["priority"] == "A":
            due, why = today, "never contacted"
        else:
            continue
        if due and due <= today:
            out.append({"id": p["id"], "name": p["name"], "title": p["title"],
                        "issuer_name": p["issuer_name"] or p["developer_name"], "priority": p["priority"],
                        "last_contact": p["last_contact"], "due": due.isoformat(),
                        "days_overdue": (today - due).days, "why": why})
    out.sort(key=lambda r: (r["priority"] or "C", -r["days_overdue"]))
    return out


def pipeline_summary(conn):
    res = {}
    for pl, stages in STAGES.items():
        rows = {r["stage"]: r for r in conn.execute(
            "SELECT stage, COUNT(*) n, COALESCE(SUM(par),0) par FROM deals WHERE pipeline=? GROUP BY stage", (pl,))}
        active = conn.execute(
            "SELECT COALESCE(SUM(par),0) p, COALESCE(SUM(par*COALESCE(probability,0)/100.0),0) w FROM deals "
            "WHERE pipeline=? AND stage NOT IN ('Closed','Lost','On Hold')", (pl,)).fetchone()
        res[pl] = {"stages": [{"stage": s, "count": rows[s]["n"] if s in rows else 0,
                               "par": rows[s]["par"] if s in rows else 0} for s in stages],
                   "active_par": active["p"], "weighted_par": active["w"]}
    return res


def dashboard(conn, today):
    s = get_settings(conn)
    window = int(s["dash_window"])
    return {"today": today.isoformat(), "window": window,
            "overdue": overdue_followups(conn, today),
            "events": build_events(conn, today, window),
            "pipeline": pipeline_summary(conn),
            "stats": {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("issuers", "people", "developers", "projects")}}


# ----------------------------------------------------------------------- digest
def build_digest(conn, today):
    s = get_settings(conn)
    window = int(s["digest_window"])
    overdue, events = overdue_followups(conn, today), build_events(conn, today, window)
    pipe = pipeline_summary(conn)
    e = html.escape
    th = "text-align:left;padding:4px 10px;border-bottom:1px solid #ddd;font-size:13px"
    parts = [f"<div style='font-family:Segoe UI,Arial,sans-serif;color:#1b2430;max-width:760px'>"
             f"<h2 style='margin-bottom:2px'>Weekly CRM digest</h2><div style='color:#667'>{today:%A, %B %d, %Y}</div>"]
    parts.append(f"<h3>Overdue follow-ups ({len(overdue)})</h3>")
    if overdue:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for r in overdue:
            parts.append(f"<tr><td style='{th}'><b>{e(r['name'])}</b></td><td style='{th}'>{e(r['issuer_name'] or '')}</td>"
                         f"<td style='{th}'>{e(r['priority'] or '')}</td>"
                         f"<td style='{th}'>{r['days_overdue']} days overdue</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>None. You're caught up.</p>")
    parts.append(f"<h3>Next {window} days</h3>")
    if events:
        parts.append("<table style='border-collapse:collapse;width:100%'>")
        for ev in events:
            when = "today" if ev["days"] == 0 else (f"in {ev['days']}d" if ev["days"] > 0 else f"{-ev['days']}d ago")
            parts.append(f"<tr><td style='{th}'>{e(ev['date'])} ({when})</td><td style='{th}'>{e(ev['kind'])}</td>"
                         f"<td style='{th}'>{e(ev['title'])}</td><td style='{th}'>{e(ev['detail'])}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p>Nothing scheduled.</p>")
    parts.append("<h3>Pipeline</h3><ul>")
    for pl, label in (("standard", "Issuer financings"), ("developer", "Developer deals")):
        n = sum(x["count"] for x in pipe[pl]["stages"] if x["stage"] not in INACTIVE_STAGES)
        parts.append(f"<li>{label}: {n} active, ${pipe[pl]['active_par'] / 1e6:,.1f}M par "
                     f"(${pipe[pl]['weighted_par'] / 1e6:,.1f}M weighted)</li>")
    parts.append("</ul></div>")
    text = [f"Weekly CRM digest, {today:%A, %B %d, %Y}", "", f"OVERDUE FOLLOW-UPS ({len(overdue)})"]
    text += [f"  - {r['name']} ({r['issuer_name'] or ''}) {r['priority']}: {r['days_overdue']}d overdue" for r in overdue]
    text += ["", f"NEXT {window} DAYS"]
    text += [f"  - {ev['date']} [{ev['kind']}] {ev['title']} {ev['detail']}" for ev in events]
    return "".join(parts), "\n".join(text)


# ----------------------------------------------------------------------- import
ALIASES = {
    "first": ["firstname", "first", "givenname"], "last": ["lastname", "last", "surname", "familyname"],
    "name": ["name", "fullname", "contact", "contactname"],
    "title": ["title", "jobtitle", "position", "role"],
    "issuer": ["issuer", "organization", "organisation", "company", "entity", "account", "agency", "jurisdiction"],
    "sector": ["sector", "issuertype", "entitytype", "type", "category"],
    "state": ["state", "st"],
    "email": ["email", "emailaddress", "email1", "workemail"],
    "phone": ["phone", "businessphone", "workphone", "mobile", "phonenumber", "telephone", "cell"],
    "priority": ["priority", "tier"],
    "birthday": ["birthday", "birthdate", "dob"], "anniversary": ["anniversary"],
    "spouse": ["spouse", "partner"], "kids": ["kids", "children"],
    "term_end": ["termend", "termexpires", "termexpiration"],
    "notes": ["notes", "note", "comments"],
}
NORM = lambda h: re.sub(r"[^a-z0-9]", "", (h or "").lower())


def guess_sector(*texts):
    t = " ".join(x for x in texts if x).lower()
    rules = [("charter", "Charter School"), ("private", "Private School"),
             ("isd", "K-12 School District"), ("school district", "K-12 School District"),
             ("unified", "K-12 School District"), ("k-12", "K-12 School District"), ("k12", "K-12 School District"),
             ("school", "K-12 School District"),
             ("college", "Higher Education"), ("universit", "Higher Education"), ("higher ed", "Higher Education"),
             ("utility", "Utility"), ("water", "Utility"), ("electric", "Utility"), ("sewer", "Utility"),
             ("power", "Utility"), ("county", "County"), ("city", "City"), ("town", "City"), ("village", "City"),
             ("district", "Special District"), ("mud", "Special District"), ("authority", "Special District")]
    for needle, sector in rules:
        if needle in t:
            return sector
    return "Other"


def parse_loose_date(s):
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,2}/\d{1,2}", s):  # month/day, year unknown
        s += "/1900"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def import_people(conn, text, dry=False):
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("The CSV has no header row.")
    colmap = {}
    for field, names in ALIASES.items():
        for h in reader.fieldnames:
            if NORM(h) in names and field not in colmap:
                colmap[field] = h
    if "name" not in colmap and not ("first" in colmap or "last" in colmap):
        raise ValueError("Couldn't find a name column (looked for Name, or First Name + Last Name).")
    issuer_cache = {r["name"].lower(): r["id"] for r in conn.execute("SELECT id,name FROM issuers")}
    res = {"mapping": colmap, "total": 0, "new_people": 0, "duplicates": 0, "new_issuers": 0,
           "skipped": 0, "sample": []}
    conn.execute("SAVEPOINT imp")
    for raw in reader:
        g = lambda f: (raw.get(colmap[f]) or "").strip() if f in colmap else ""
        name = g("name") or f"{g('first')} {g('last')}".strip()
        res["total"] += 1
        if not name:
            res["skipped"] += 1
            continue
        issuer_id, iname = None, g("issuer")
        if iname:
            issuer_id = issuer_cache.get(iname.lower())
            if not issuer_id:
                sector = guess_sector(g("sector"), iname)
                cur = conn.execute("INSERT INTO issuers(name,sector,state) VALUES(?,?,?)",
                                   (iname, sector, g("state") or None))
                issuer_id = issuer_cache[iname.lower()] = cur.lastrowid
                res["new_issuers"] += 1
        email = g("email").lower()
        dup = (email and conn.execute("SELECT 1 FROM people WHERE lower(email)=?", (email,)).fetchone()) or \
            conn.execute("SELECT 1 FROM people WHERE lower(name)=? AND COALESCE(issuer_id,0)=COALESCE(?,0)",
                         (name.lower(), issuer_id)).fetchone()
        if dup:
            res["duplicates"] += 1
            continue
        pri = g("priority").upper()[:1]
        conn.execute(
            "INSERT INTO people(name,title,issuer_id,email,phone,priority,birthday,anniversary,spouse,kids,term_end,notes)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, g("title") or None, issuer_id, email or None, g("phone") or None,
             pri if pri in ("A", "B", "C") else "C", parse_loose_date(g("birthday")),
             parse_loose_date(g("anniversary")), g("spouse") or None, g("kids") or None,
             parse_loose_date(g("term_end")), g("notes") or None))
        res["new_people"] += 1
        if len(res["sample"]) < 5:
            res["sample"].append({"name": name, "title": g("title"), "issuer": iname})
    if dry:
        conn.execute("ROLLBACK TO imp")
    conn.execute("RELEASE imp")
    conn.commit()
    return res


# ------------------------------------------------------------------------- demo
def seed_demo(conn):
    if conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0]:
        return False
    t = dt.date.today()
    D = lambda n: (t + dt.timedelta(days=n)).isoformat()
    ins = lambda table, **kw: conn.execute(
        f"INSERT INTO {table}({','.join(kw)}) VALUES({','.join('?' * len(kw))})", list(kw.values())).lastrowid
    X = lambda **kw: json.dumps(kw)
    city = ins("issuers", name="City of Riverbend", sector="City", state="TX", primary_banker="Hartwell Securities",
               our_coverage_banker="You", other_bankers="Larkin & Co.", fiscal_year_end="September",
               extra=X(population=148000))
    county = ins("issuers", name="Maple County", sector="County", state="TX", primary_banker="Larkin & Co.",
                 our_coverage_banker="You", extra=X(population=410000))
    isd = ins("issuers", name="Cedar Valley ISD", sector="K-12 School District", state="TX",
              primary_banker="Hartwell Securities", our_coverage_banker="You",
              extra=X(enrollment=17800, remaining_authorization=95000000))
    cc = ins("issuers", name="Westbrook Community College District", sector="Higher Education", state="TX",
             primary_banker="Larkin & Co.", extra=X(control="Public", enrollment=21000))
    util = ins("issuers", name="Lakeshore Water Authority", sector="Utility", state="TX",
               primary_banker="Hartwell Securities", extra=X(utility_type="Water / Sewer"))
    prep = ins("issuers", name="St. Anselm Preparatory School", sector="Private School", state="TX",
               extra=X(affiliation="Independent", enrollment=640))
    charter = ins("issuers", name="Prairie STEM Charter Academy", sector="Charter School", state="TX",
                  extra=X(authorizer="State Board", enrollment=1150))
    mud = ins("issuers", name="Harborview MUD No. 4", sector="Special District", state="TX",
              primary_banker="Larkin & Co.", our_coverage_banker="You")

    P = lambda **kw: ins("people", **kw)
    mayor = P(name="Dana Whitfield", title="Mayor", issuer_id=city, email="dwhitfield@example.gov", priority="B",
              term_start=D(-400), term_end=D(25), last_contact=D(-120))
    cm = P(name="Marcus Ellery", title="City Manager", issuer_id=city, email="mellery@example.gov", priority="A",
           last_contact=D(-45), birthday=f"1978-{(t + dt.timedelta(days=4)).month:02d}-{(t + dt.timedelta(days=4)).day:02d}",
           spouse="Priya", kids="Asha (12), Dev (9)", reports_to_id=mayor,
           personal_notes="Runs marathons. Alma mater: Texas A&M. Met at the TML conference.")
    P(name="Helen Okafor", title="Chief Financial Officer", issuer_id=city, email="hokafor@example.gov", priority="A",
      last_contact=D(-12), reports_to_id=cm, next_followup=D(-3), notes="Interested in refunding the 2016 GO.")
    P(name="Tom Brandt", title="City Clerk", issuer_id=city, priority="C", reports_to_id=cm)
    P(name="Judge Alan Reyes", title="County Judge", issuer_id=county, priority="B", term_end=D(200), last_contact=D(-100))
    P(name="Sue Lindqvist", title="County Auditor", issuer_id=county, priority="A", last_contact=D(-8),
      anniversary=f"2005-{(t + dt.timedelta(days=9)).month:02d}-{(t + dt.timedelta(days=9)).day:02d}", spouse="Karl")
    sup = P(name="Dr. Renee Park", title="Superintendent", issuer_id=isd, priority="A", last_contact=D(-60))
    P(name="Greg Hollis", title="Chief Financial Officer", issuer_id=isd, priority="A", last_contact=D(-20),
      reports_to_id=sup, next_followup=D(7))
    P(name="Nina Castellano", title="VP Finance", issuer_id=cc, priority="B", last_contact=D(-95))
    P(name="Omar Haddad", title="Finance Director", issuer_id=util, priority="B", last_contact=D(-30))
    P(name="Beth Archer", title="Head of School", issuer_id=prep, priority="C")
    P(name="Luis Moreno", title="Board Chair", issuer_id=charter, priority="B", term_end=D(60), last_contact=D(-70))
    P(name="Carla Dunn", title="District Administrator", issuer_id=mud, priority="B", last_contact=D(-15))

    dev = ins("developers", name="Northgate Land Partners", website="https://example.com")
    dev2 = ins("developers", name="Sundial Communities", website="https://example.com")
    P(name="Ray Kowalski", title="Managing Partner", developer_id=dev, priority="A", last_contact=D(-14),
      email="ray@example.com")
    P(name="Mia Tran", title="VP Land Development", developer_id=dev2, priority="B", last_contact=D(-110))
    proj = ins("projects", name="Harborview Phase 1", developer_id=dev, issuer_id=mud,
               structure="Assessment-backed (PID/MUD/CDD)", location="Harborview, TX", est_par=18500000)
    proj2 = ins("projects", name="Riverbend Marketplace", developer_id=dev, issuer_id=city,
                structure="Sales Tax Rebate Monetization", location="Riverbend, TX", est_par=32000000)
    ins("projects", name="Sundial Ranch", developer_id=dev2, structure="Assessment-backed (PID/MUD/CDD)",
        location="Maple County, TX", est_par=24000000)

    ins("deals", name="Riverbend GO Refunding", pipeline="standard", stage="Initial Conversation", issuer_id=city,
        purpose="Refunding", security_type="GO", par=42000000, expected_date=D(95), role="Senior Manager",
        probability=40, ma_name="Public Resources Advisory", bond_counsel="Mason & Pratt LLP", trustee="First Trust")
    ins("deals", name="Cedar Valley ISD 2027 Bond", pipeline="standard", stage="Proposal / RFP", issuer_id=isd,
        purpose="New Money", security_type="GO", par=95000000, expected_date=D(140), role="Senior Manager",
        probability=35, rfp_deadline=D(11), ma_name="Hilltop Advisors", bond_counsel="Mason & Pratt LLP",
        competing_banks="Hartwell, Larkin")
    ins("deals", name="Lakeshore Water Revenue Bonds", pipeline="standard", stage="Structuring", issuer_id=util,
        purpose="New Money", security_type="Revenue", par=60000000, expected_date=D(70), role="Senior Manager",
        probability=60, trustee="Regions Trust")
    ins("deals", name="Westbrook CCD Refunding", pipeline="standard", stage="Idea", issuer_id=cc,
        purpose="Refunding", security_type="GO", par=28000000, probability=15)
    ins("deals", name="Prairie STEM Series 2026", pipeline="standard", stage="Pricing", issuer_id=charter,
        purpose="New Money", security_type="Revenue", par=14500000, expected_date=D(16), role="Underwriter",
        probability=90)
    ins("deals", name="Harborview Phase 1 Assessment Bonds", pipeline="developer", stage="Validation", project_id=proj,
        issuer_id=mud, purpose="New Money", security_type="Assessment", par=18500000, expected_date=D(85),
        role="Underwriter", probability=55, bond_counsel="Mason & Pratt LLP")
    ins("deals", name="Riverbend Marketplace Rebate Monetization", pipeline="developer", stage="Internal Committee",
        project_id=proj2, issuer_id=city, purpose="New Money", security_type="Sales Tax Rebate", par=32000000,
        expected_date=D(120), role="Placement Agent", probability=30)

    K = lambda **kw: ins("key_dates", **kw)
    K(title="City of Riverbend: budget adoption", kind="Budget Adoption", date=D(33), issuer_id=city, remind_days_before=30)
    K(title="General election: council seats", kind="Election", date=D(36), issuer_id=city, remind_days_before=45)
    K(title="Cedar Valley ISD bond election", kind="Bond Election", date=D(52), issuer_id=isd, remind_days_before=60)
    K(title="Prairie STEM charter renewal", kind="Charter Renewal", date=D(210), issuer_id=charter, remind_days_before=120)
    K(title="Maple County fiscal year end", kind="Fiscal Year End", date=f"{t.year}-09-30", issuer_id=county,
      remind_days_before=45, recurs_annually=1)
    K(title="Lakeshore rate study due", kind="Rate Study", date=D(18), issuer_id=util, remind_days_before=21)

    for pid, off, typ, note in [(cm, -45, "Meeting", "Coffee at City Hall. Discussed 2016 GO call date and CIP timing."),
                                (cm, -120, "Call", "Intro call after conference."),
                                (mayor, -120, "Email", "Sent congratulations on re-election filing.")]:
        iss = conn.execute("SELECT issuer_id FROM people WHERE id=?", (pid,)).fetchone()[0]
        ins("interactions", person_id=pid, issuer_id=iss, date=D(off), type=typ, notes=note)
    conn.commit()
    return True


# ------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "PFCRM/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("PFCRM_VERBOSE"):
            super().log_message(fmt, *args)

    # -- helpers
    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def err(self, code, msg):
        self.send(code, {"error": msg})

    def trusted(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("localhost", "127.0.0.1"):
            return False  # blocks DNS-rebinding
        origin = self.headers.get("Origin")
        return not origin or urlparse(origin).netloc == self.headers.get("Host")

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8") if n else ""

    # -- dispatch
    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")
    def do_PUT(self): self.dispatch("PUT")
    def do_DELETE(self): self.dispatch("DELETE")

    def dispatch(self, method):
        if not self.trusted():
            return self.err(403, "forbidden")
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self.static(u.path) if method == "GET" else self.err(405, "method not allowed")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path[5:].split("/") if p]
        conn = connect()
        try:
            self.api(conn, method, parts, q)
        except LookupError:
            self.err(404, "not found")
        except (ValueError, sqlite3.IntegrityError) as e:
            self.err(400, str(e))
        except Exception as e:  # pragma: no cover
            self.err(500, f"{type(e).__name__}: {e}")
        finally:
            conn.close()

    def api(self, conn, method, parts, q):
        today = dt.date.today()
        head = parts[0] if parts else ""
        if method == "GET" and head == "meta":
            return self.send(200, {"stages": STAGES, "sectors": SECTORS, "settings": get_settings(conn)})
        if method == "GET" and head == "dashboard":
            return self.send(200, dashboard(conn, today))
        if method == "GET" and head == "events":
            return self.send(200, build_events(conn, today, int(q.get("window", 30))))
        if method == "GET" and head == "digest.html":
            return self.send(200, build_digest(conn, today)[0], "text/html; charset=utf-8")
        if method == "GET" and head == "backup":
            conn.commit()
            with open(DB_PATH, "rb") as f:
                return self.send(200, f.read(), "application/octet-stream",
                                 {"Content-Disposition": f"attachment; filename=crm-backup-{today}.db"})
        if head == "settings":
            if method == "PUT":
                for k, v in json.loads(self.body() or "{}").items():
                    if k in DEFAULT_SETTINGS:
                        if not str(v).isdigit() or int(v) < 1:
                            raise ValueError(f"{k} must be a positive whole number")
                        conn.execute("UPDATE settings SET value=? WHERE key=?", (str(v), k))
                conn.commit()
            return self.send(200, get_settings(conn))
        if method == "POST" and parts[:2] == ["import", "people"]:
            return self.send(200, import_people(conn, self.body(), dry=q.get("dry") == "1"))
        if head in QUERIES:
            rid = int(parts[1]) if len(parts) > 1 else None
            if method == "GET":
                rows = list_rows(conn, head, q, rid)
                if rid is not None:
                    if not rows:
                        raise LookupError
                    return self.send(200, rows[0])
                return self.send(200, rows)
            if method == "POST" and rid is None:
                new_id = create_row(conn, head, json.loads(self.body() or "{}"))
                return self.send(201, list_rows(conn, head, row_id=new_id)[0])
            if method == "PUT" and rid is not None:
                update_row(conn, head, rid, json.loads(self.body() or "{}"))
                return self.send(200, list_rows(conn, head, row_id=rid)[0])
            if method == "DELETE" and rid is not None:
                if not conn.execute(f"DELETE FROM {head} WHERE id=?", (rid,)).rowcount:
                    raise LookupError
                conn.commit()
                return self.send(200, {"ok": True})
        self.err(404, "not found")

    def static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            return self.err(404, "not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            self.send(200, f.read(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--demo", action="store_true", help="load fictional demo data if the database is empty")
    a = ap.parse_args()
    conn = connect()
    if a.demo and seed_demo(conn):
        print("Loaded demo data.")
    conn.close()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"Public Finance CRM running at http://localhost:{a.port}  (Ctrl+C to stop)\nDatabase: {DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    sys.exit(main())
