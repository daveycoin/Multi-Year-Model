import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402

TODAY = dt.date(2026, 10, 5)
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()


class CRMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = server.connect(os.path.join(self.tmp.name, "t.db"))
        self.issuer = server.create_row(self.conn, "issuers", {"name": "City of Test", "sector": "City"})

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def person(self, **kw):
        return server.create_row(self.conn, "people", {"name": "P", "issuer_id": self.issuer, **kw})

    def test_next_occurrence(self):
        self.assertEqual(server.next_occurrence("1980-10-05", TODAY), TODAY)
        self.assertEqual(server.next_occurrence("1980-10-04", TODAY), dt.date(2027, 10, 4))
        self.assertEqual(server.next_occurrence("2000-02-29", dt.date(2027, 1, 1)), dt.date(2027, 2, 28))
        self.assertIsNone(server.next_occurrence("garbage", TODAY))

    def test_cadence_overdue(self):
        self.person(name="A-old", priority="A", last_contact=D(-31))
        self.person(name="A-ok", priority="A", last_contact=D(-29))
        self.person(name="C-never", priority="C")
        self.person(name="A-never", priority="A")
        names = {r["name"] for r in server.overdue_followups(self.conn, TODAY)}
        self.assertEqual(names, {"A-old", "A-never"})

    def test_manual_followup_overrides_cadence(self):
        self.person(name="future", priority="A", last_contact=D(-200), next_followup=D(5))
        self.person(name="past", priority="C", last_contact=D(-1), next_followup=D(-2))
        names = {r["name"] for r in server.overdue_followups(self.conn, TODAY)}
        self.assertEqual(names, {"past"})

    def test_logging_interaction_updates_person(self):
        pid = self.person(priority="A", last_contact=D(-60), next_followup=D(-5))
        server.create_row(self.conn, "interactions", {"person_id": pid, "date": D(-1), "type": "Call"})
        p = server.list_rows(self.conn, "people", row_id=pid)[0]
        self.assertEqual(p["last_contact"], D(-1))
        self.assertIsNone(p["next_followup"])
        self.assertEqual(p["issuer_id"], self.issuer)
        self.assertEqual(server.list_rows(self.conn, "interactions")[0]["issuer_id"], self.issuer)
        server.create_row(self.conn, "interactions", {"person_id": pid, "date": D(0), "next_followup": D(30)})
        self.assertEqual(server.list_rows(self.conn, "people", row_id=pid)[0]["next_followup"], D(30))
        self.assertEqual(server.overdue_followups(self.conn, TODAY), [])

    def test_older_interaction_does_not_rewind_last_contact(self):
        pid = self.person(last_contact=D(-1))
        server.create_row(self.conn, "interactions", {"person_id": pid, "date": D(-40)})
        self.assertEqual(server.list_rows(self.conn, "people", row_id=pid)[0]["last_contact"], D(-1))

    def test_events(self):
        self.person(name="Mayor", term_end=D(60), birthday="1970-10-08", anniversary="1999-10-20", spouse="Sam")
        server.create_row(self.conn, "key_dates", {"title": "Election", "kind": "Election", "date": D(40),
                                                   "remind_days_before": 45, "issuer_id": self.issuer})
        server.create_row(self.conn, "key_dates", {"title": "FYE", "kind": "Fiscal Year End", "date": "2020-09-30",
                                                   "recurs_annually": 1, "remind_days_before": 0})
        server.create_row(self.conn, "key_dates", {"title": "Old", "date": D(-90)})
        server.create_row(self.conn, "key_dates", {"title": "Done", "date": D(3), "done": 1})
        evs = {e["title"]: e for e in server.build_events(self.conn, TODAY, 30)}
        self.assertIn("Mayor: term ends", evs)           # inside its 90-day reminder window
        self.assertTrue(evs["Mayor: term ends"]["reminder"])
        self.assertIn("Mayor's birthday", evs)
        self.assertIn("Mayor & Sam: anniversary", evs)      # 15 days out, inside the 30-day window
        self.assertEqual(evs["Election"]["days"], 40)       # outside window but inside its reminder lead time
        self.assertNotIn("FYE", evs)                        # next Sept 30 is ~360 days away
        self.assertNotIn("Old", evs)
        self.assertNotIn("Done", evs)

    def test_events_for_a_calendar_range(self):
        self.person(name="Pat", birthday="1980-09-10", term_end=D(-20))
        server.create_row(self.conn, "key_dates", {"title": "FYE", "date": "2020-09-30", "recurs_annually": 1})
        server.create_row(self.conn, "key_dates", {"title": "One-off", "date": D(40)})
        r = lambda a, b: {(e["title"], e["date"]) for e in server.build_events(self.conn, TODAY, 0, a, b)}
        sept = r(dt.date(2026, 9, 1), dt.date(2026, 9, 30))           # a month in the past
        self.assertEqual(sept, {("Pat's birthday", "2026-09-10"), ("FYE", "2026-09-30"), ("Pat: term ends", D(-20))})
        span = r(dt.date(2026, 9, 1), dt.date(2027, 10, 31))           # annual items repeat across years
        self.assertIn(("FYE", "2027-09-30"), span)
        self.assertIn(("Pat's birthday", "2027-09-10"), span)
        self.assertEqual(r(dt.date(2026, 11, 1), dt.date(2026, 11, 30)), {("One-off", D(40))})

    def test_rfp_deadline_event_only_for_active_deals(self):
        for stage in ("Proposal / RFP", "Lost"):
            server.create_row(self.conn, "deals", {"name": stage, "stage": stage, "issuer_id": self.issuer,
                                                   "rfp_deadline": D(5)})
        titles = [e["title"] for e in server.build_events(self.conn, TODAY, 30)]
        self.assertEqual(titles, ["RFP due: Proposal / RFP"])

    def test_deal_stage_validation_and_project_issuer_inheritance(self):
        with self.assertRaises(ValueError):
            server.create_row(self.conn, "deals", {"name": "x", "pipeline": "standard", "stage": "Validation"})
        dev = server.create_row(self.conn, "developers", {"name": "Dev Co"})
        proj = server.create_row(self.conn, "projects", {"name": "Proj", "developer_id": dev, "issuer_id": self.issuer})
        did = server.create_row(self.conn, "deals", {"name": "D", "pipeline": "developer", "project_id": proj,
                                                     "stage": "Validation"})
        d = server.list_rows(self.conn, "deals", row_id=did)[0]
        self.assertEqual(d["issuer_id"], self.issuer)
        self.assertEqual(server.list_rows(self.conn, "projects", {"issuer_id": self.issuer})[0]["name"], "Proj")

    def test_pipeline_summary_weighted(self):
        server.create_row(self.conn, "deals", {"name": "a", "stage": "Pricing", "par": 100, "probability": 50})
        server.create_row(self.conn, "deals", {"name": "b", "stage": "Closed", "par": 1000, "probability": 100})
        s = server.pipeline_summary(self.conn)["standard"]
        self.assertEqual((s["active_par"], s["weighted_par"]), (100, 50))

    def test_import_csv(self):
        csv_text = ("First Name,Last Name,Job Title,Company,Email,Birthday\n"
                    "Ann,Lee,CFO,City of Alpha,ann@x.gov,3/15\n"
                    "Bob,Ray,Superintendent,Beta ISD,bob@x.edu,\n"
                    "Ann,Lee,CFO,City of Alpha,ann@x.gov,\n"
                    ",,,,,\n")
        dry = server.import_people(self.conn, csv_text, dry=True)
        self.assertEqual((dry["new_people"], dry["new_issuers"], dry["duplicates"], dry["skipped"]), (2, 2, 1, 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM people").fetchone()[0], 0)  # dry run left nothing
        server.import_people(self.conn, csv_text)
        sectors = {r["name"]: r["sector"] for r in self.conn.execute("SELECT name,sector FROM issuers")}
        self.assertEqual(sectors["City of Alpha"], "City")
        self.assertEqual(sectors["Beta ISD"], "K-12 School District")
        self.assertEqual(self.conn.execute("SELECT birthday FROM people WHERE email='ann@x.gov'").fetchone()[0],
                         "1900-03-15")
        again = server.import_people(self.conn, csv_text)
        self.assertEqual(again["new_people"], 0)

    def test_import_requires_name_column(self):
        with self.assertRaises(ValueError):
            server.import_people(self.conn, "Company,Email\nX,y@z.com\n")

    def test_person_links_groups_and_primary_issuer(self):
        other = server.create_row(self.conn, "issuers", {"name": "Maple County", "sector": "County"})
        pid = server.create_row(self.conn, "people", {
            "name": "Counsel", "links": [{"issuer_id": self.issuer, "groups": ["Related", "Bogus"]},
                                         {"issuer_id": other, "groups": ["Related", "Staff"]}]})
        p = server.list_rows(self.conn, "people", row_id=pid)[0]
        self.assertEqual(p["issuer_id"], self.issuer)                      # first link is the primary issuer
        self.assertEqual([(l["issuer_id"], l["groups"]) for l in p["links"]],
                         [(self.issuer, ["Related"]), (other, ["Staff", "Related"])])  # invalid group dropped, canonical order
        at_county = server.list_rows(self.conn, "people", {"linked_issuer": other})
        self.assertEqual([(r["name"], r["groups"]) for r in at_county], [("Counsel", ["Staff", "Related"])])
        # replacing the links updates primary; removing every link clears it
        server.update_row(self.conn, "people", pid, {"links": [{"issuer_id": other, "groups": ["Elected"]}]})
        p = server.list_rows(self.conn, "people", row_id=pid)[0]
        self.assertEqual((p["issuer_id"], len(p["links"])), (other, 1))
        server.update_row(self.conn, "people", pid, {"links": []})
        self.assertIsNone(server.list_rows(self.conn, "people", row_id=pid)[0]["issuer_id"])

    def test_plain_issuer_id_gets_a_guessed_group_link(self):
        mayor = self.person(name="M", title="Mayor")
        clerk = self.person(name="C", title="City Clerk")
        groups = {r["name"]: r["links"][0]["groups"] for r in server.list_rows(self.conn, "people")
                  if r["id"] in (mayor, clerk)}
        self.assertEqual(groups, {"M": ["Elected"], "C": ["Staff"]})

    def test_deleting_issuer_moves_primary_to_remaining_link(self):
        other = server.create_row(self.conn, "issuers", {"name": "Second", "sector": "County"})
        pid = server.create_row(self.conn, "people", {"name": "Two", "links": [
            {"issuer_id": self.issuer, "groups": ["Staff"]}, {"issuer_id": other, "groups": ["Related"]}]})
        self.conn.execute("DELETE FROM issuers WHERE id=?", (self.issuer,))
        server.repair_primary(self.conn)
        p = server.list_rows(self.conn, "people", row_id=pid)[0]
        self.assertEqual((p["issuer_id"], [l["issuer_id"] for l in p["links"]]), (other, [other]))

    def test_old_database_is_migrated(self):
        self.conn.execute("DELETE FROM person_issuers")        # simulate a pre-groups database
        pid = self.conn.execute("INSERT INTO people(name,title,issuer_id) VALUES('Old','Council Member',?)",
                                (self.issuer,)).lastrowid
        server.backfill_links(self.conn)
        self.assertEqual(server.list_rows(self.conn, "people", row_id=pid)[0]["links"][0]["groups"], ["Elected"])

    def test_handle_api_round_trip(self):
        old = server.DB_PATH
        server.DB_PATH = os.path.join(self.tmp.name, "api.db")
        try:
            code, issuer, _, _ = server.handle_api("POST", "/api/issuers", '{"name": "API City", "sector": "City"}')
            self.assertEqual(code, 201)
            code, rows, ctype, _ = server.handle_api("GET", "/api/issuers?sector=City", today=TODAY)
            self.assertEqual((code, ctype, [r["name"] for r in rows]), (200, "application/json", ["API City"]))
            self.assertEqual(server.handle_api("GET", "/api/issuers/999")[0], 404)
            self.assertEqual(server.handle_api("POST", "/api/issuers", "{}")[0], 400)   # nothing to save
            code, err, _, _ = server.handle_api("POST", "/api/issuers", '{"state": "TX"}')
            self.assertEqual((code, err["error"]), (400, "Missing required field: name"))
            self.assertEqual(server.handle_api("POST", "/api/issuers", "not json")[0], 400)
            code, html_body, ctype, _ = server.handle_api("GET", "/api/digest.html", today=TODAY)
            self.assertTrue(ctype.startswith("text/html") and "Weekly CRM digest" in html_body)
            code, blob, _, hdrs = server.handle_api("GET", "/api/backup", today=TODAY)
            self.assertTrue(blob.startswith(b"SQLite format 3") and "crm-backup-2026-10-05" in hdrs["Content-Disposition"])
        finally:
            server.DB_PATH = old

    def test_tasks_lifecycle_events_and_digest(self):
        pid = self.person(name="Contact")
        tid = server.create_row(self.conn, "tasks", {"title": "Send deck", "due_date": D(2), "person_id": pid})
        task = server.list_rows(self.conn, "tasks", row_id=tid)[0]
        self.assertEqual((task["issuer_id"], task["done"]), (self.issuer, 0))             # issuer inferred from the person
        server.create_row(self.conn, "tasks", {"title": "Late one", "due_date": D(-3)})
        server.create_row(self.conn, "tasks", {"title": "Far off", "due_date": D(40)})
        due = server.tasks_due(self.conn, TODAY)
        self.assertEqual([t["title"] for t in due], ["Late one", "Send deck"])           # overdue first; far-off task excluded
        self.assertIn("Send deck", {e["title"] for e in server.build_events(self.conn, TODAY, 30)})
        self.assertIn("Send deck", server.build_digest(self.conn, TODAY)[1])
        server.CURRENT_DATE = TODAY
        try:
            server.update_row(self.conn, "tasks", tid, {"done": 1})
        finally:
            server.CURRENT_DATE = None
        task = server.list_rows(self.conn, "tasks", row_id=tid)[0]
        self.assertEqual((task["done"], task["done_at"]), (1, TODAY.isoformat()))
        self.assertNotIn("Send deck", [t["title"] for t in server.tasks_due(self.conn, TODAY)])
        self.assertEqual(len(server.list_rows(self.conn, "tasks", {"done": 0})), 2)
        server.update_row(self.conn, "tasks", tid, {"done": 0})
        self.assertIsNone(server.list_rows(self.conn, "tasks", row_id=tid)[0]["done_at"])

    def test_timeline_records_stage_moves_tasks_and_date_changes(self):
        pid = self.person(name="Pat")
        did = server.create_row(self.conn, "deals", {"name": "Deal A", "issuer_id": self.issuer})
        server.update_row(self.conn, "deals", did, {"stage": "Structuring"})
        server.update_row(self.conn, "deals", did, {"par": 5})                           # not a stage change: no entry
        kid = server.create_row(self.conn, "key_dates", {"title": "Budget", "date": D(10), "issuer_id": self.issuer})
        server.update_row(self.conn, "key_dates", kid, {"date": D(20)})
        tid = server.create_row(self.conn, "tasks", {"title": "Follow up", "person_id": pid})
        server.update_row(self.conn, "tasks", tid, {"done": 1})
        server.create_row(self.conn, "interactions", {"person_id": pid, "date": D(-1), "type": "Call", "notes": "Chatted"})
        texts = [i["text"] for i in server.timeline(self.conn, issuer_id=self.issuer)]
        for expected in ("Financing added: Deal A (Idea)", "Deal A: stage Idea \u2192 Structuring",
                         f"Date moved: Budget {D(10)} \u2192 {D(20)}", "Task completed: Follow up", "Chatted"):
            self.assertIn(expected, texts)
        self.assertEqual(sum("Deal A: stage" in t for t in texts), 1)
        mine = server.timeline(self.conn, person_id=pid)
        self.assertEqual({i["kind"] for i in mine}, {"Call", "Task", "Person"})
        self.assertEqual(len(server.timeline(self.conn, limit=2)), 2)

    def test_closed_date_set_and_cleared_with_stage(self):
        did = server.create_row(self.conn, "deals", {"name": "D"})
        server.CURRENT_DATE = TODAY
        try:
            server.update_row(self.conn, "deals", did, {"stage": "Closed"})
            self.assertEqual(server.list_rows(self.conn, "deals", row_id=did)[0]["closed_date"], TODAY.isoformat())
            server.update_row(self.conn, "deals", did, {"stage": "Pricing"})
        finally:
            server.CURRENT_DATE = None
        self.assertIsNone(server.list_rows(self.conn, "deals", row_id=did)[0]["closed_date"])

    def test_search_across_entities_with_ranking_and_escaping(self):
        pid = self.person(name="Rebecca Stone", title="CFO", email="rs@x.gov", notes="loves sailing")
        server.create_row(self.conn, "issuers", {"name": "Stone County", "sector": "County"})
        server.create_row(self.conn, "deals", {"name": "Refunding", "ma_name": "Stone Advisors", "issuer_id": self.issuer})
        server.create_row(self.conn, "interactions", {"person_id": pid, "date": D(-1), "notes": "Discussed 100% funding_gap"})
        res = {g["entity"]: [r["title"] for r in g["results"]] for g in server.search(self.conn, "stone")["groups"]}
        self.assertEqual(res["issuers"], ["Stone County"])
        self.assertEqual(res["people"], ["Rebecca Stone"])
        self.assertEqual(res["deals"], ["Refunding"])                                    # matched through the MA name
        self.assertEqual([r["title"] for g in server.search(self.conn, "sailing")["groups"] for r in g["results"]],
                         ["Rebecca Stone"])                                               # matched through personal notes
        self.assertEqual(server.search(self.conn, "rebecca cfo")["total"], 1)             # all terms must match
        self.assertEqual(server.search(self.conn, "100% funding_gap")["groups"][0]["entity"], "interactions")
        self.assertEqual(server.search(self.conn, "%")["total"], 1)                       # a literal %, not a wildcard
        self.assertEqual(server.search(self.conn, "   ")["total"], 0)

    def test_reports_and_custom_report(self):
        iss2 = server.create_row(self.conn, "issuers", {"name": "Other ISD", "sector": "K-12 School District"})
        mk = lambda **kw: server.create_row(self.conn, "deals", kw)
        mk(name="a", issuer_id=self.issuer, stage="Pricing", par=100, probability=50, expected_date="2026-11-10")
        mk(name="b", issuer_id=iss2, stage="Idea", par=300, probability=10, expected_date="2027-02-01")
        mk(name="c", issuer_id=iss2, stage="Closed", par=70, closed_date="2026-03-01")
        mk(name="d", issuer_id=iss2, stage="Lost", par=30, closed_date="2026-05-01")
        mk(name="e", issuer_id=iss2, stage="Closed", par=10, closed_date="2025-05-01")
        r = server.reports(self.conn, TODAY)
        self.assertEqual((r["kpis"]["active_par"], r["kpis"]["weighted_par"]), (400, 80))
        self.assertEqual({q["label"]: q["par"] for q in r["by_quarter"]}, {"2026 Q4": 100, "2027 Q1": 300})
        self.assertEqual({s["label"]: s["par"] for s in r["by_sector"]}, {"K-12 School District": 300, "City": 100})
        self.assertEqual([(y["label"], y["closed_par"], y["lost_par"]) for y in r["outcomes"]], [("2025", 10, 0), ("2026", 70, 30)])
        self.assertEqual((r["kpis"]["win_rate"], r["kpis"]["closed_ytd_par"]), (67, 70))
        self.assertEqual(len(r["activity"]), 12)
        rep = server.custom_report(self.conn, {"entity": "deals", "group": "stage", "measure": "par", "active": "0"})
        self.assertEqual([(x["label"], x["value"]) for x in rep["rows"]],
                         [("Idea", 300), ("Pricing", 100), ("Closed", 80), ("Lost", 30)])   # stage order, not alphabetical
        rep = server.custom_report(self.conn, {"entity": "deals", "group": "sector", "measure": "weighted"})
        self.assertEqual((rep["rows"][0]["label"], rep["total"]), ("City", 80))             # active only by default
        self.assertEqual(server.custom_report(self.conn, {"entity": "issuers", "group": "sector"})["total"], 2)
        for bad in ({"entity": "deals", "group": "nope"}, {"entity": "people", "group": "group", "measure": "par"}):
            with self.assertRaises(ValueError):
                server.custom_report(self.conn, bad)

    def test_stale_relationships_report(self):
        iss2 = server.create_row(self.conn, "issuers", {"name": "Fresh", "sector": "City"})
        self.person(name="Old", last_contact=D(-100))
        server.create_row(self.conn, "people", {"name": "New", "last_contact": D(-5), "links": [{"issuer_id": iss2}]})
        server.create_row(self.conn, "deals", {"name": "x", "issuer_id": self.issuer})
        stale = server.reports(self.conn, TODAY)["stale"]
        self.assertEqual([(s["name"], s["days"], s["n_active"]) for s in stale], [("City of Test", 100, 1)])

    def test_issuer_state_stays_plain_text(self):
        iid = server.create_row(self.conn, "issuers", {"name": "Texas City", "sector": "City", "state": "TX"})
        self.assertEqual(server.list_rows(self.conn, "issuers", row_id=iid)[0]["state"], "TX")
        self.assertEqual([r["state"] for r in server.list_rows(self.conn, "issuers", {"sector": "City"}) if r["id"] == iid], ["TX"])
        self.assertEqual(server.list_rows(self.conn, "issuers", row_id=self.issuer)[0]["state"], None)   # unset stays unset

    def test_saved_views_round_trip_through_api(self):
        old = server.DB_PATH
        server.DB_PATH = os.path.join(self.tmp.name, "views.db")
        try:
            code, row, _, _ = server.handle_api("POST", "/api/saved_views",
                                                '{"page": "people", "name": "Elected", "state": {"group": "Elected", "q": ""}}')
            self.assertEqual((code, row["state"]), (201, {"group": "Elected", "q": ""}))
            code, rows, _, _ = server.handle_api("GET", "/api/saved_views?page=people")
            self.assertEqual([r["name"] for r in rows], ["Elected"])
            self.assertEqual(server.handle_api("GET", "/api/saved_views?page=issuers")[1], [])
            for path in ("/api/search?q=x", "/api/reports", "/api/timeline", "/api/report?entity=deals&group=stage"):
                self.assertEqual(server.handle_api("GET", path, today=TODAY)[0], 200, path)
            self.assertEqual(server.handle_api("GET", "/api/report?entity=deals&group=bogus")[0], 400)
        finally:
            server.DB_PATH = old

    def test_old_database_gains_closed_date_column(self):
        self.conn.execute("ALTER TABLE deals DROP COLUMN closed_date")
        self.conn.commit()
        self.conn.close()
        self.conn = server.connect(os.path.join(self.tmp.name, "t.db"))
        self.assertIn("closed_date", server.table_columns(self.conn, "deals"))

    def test_demo_seed_and_digest(self):
        other = server.connect(os.path.join(self.tmp.name, "demo.db"))
        self.assertTrue(server.seed_demo(other))
        self.assertFalse(server.seed_demo(other))
        d = server.dashboard(other, dt.date.today())
        self.assertTrue(d["overdue"] and d["events"])
        html_body, text = server.build_digest(other, dt.date.today())
        self.assertIn("Overdue follow-ups", html_body)
        self.assertIn("OVERDUE", text)
        other.close()


if __name__ == "__main__":
    unittest.main()
