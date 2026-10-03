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
