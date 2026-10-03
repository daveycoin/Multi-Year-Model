# Public Finance CRM (proof of concept)

A single-user, local CRM built around how a public finance banker works: **issuer → people**, and for
developer deals **developer → projects → issuer**. Standard-library Python + SQLite + a small
browser UI. Nothing to install, and nothing leaves your machine (the server binds to `127.0.0.1`).

## Run it

```bash
cd pf-crm
python3 server.py --demo      # --demo loads fictional sample data into an empty database
# open http://localhost:8765
```

Drop `--demo` to start empty. Your data is one file, `data/crm.db` (download a backup from Settings).
Run the tests with `python3 -m unittest discover -s tests`.

## What's in it

| Area | Notes |
|---|---|
| **Issuers** | Cities, counties, K-12, higher ed, utilities, private schools, charter schools, special districts. Shared fields plus a few sector-specific ones. Tracks the **primary banker**, our coverage banker, and other banks covering them. |
| **People** | Linked to one or more issuers (or a developer), and tagged **Elected / Staff / Related** at each issuer (one or several groups per link, so someone can be Staff at one issuer and Related at another). An issuer page shows its people in those three groups. Reports-to, term start/end, priority A/B/C, last contact, next follow-up, birthday, anniversary, spouse, kids, personal notes. |
| **Developers → Projects** | Projects link to the issuer behind them (district, city, county), so an issuer page shows its developer projects. |
| **Pipeline** | Two list views (switch with the tabs; filter by stage, sort by any column, change stage inline). Issuer financings: Idea → Initial Conversation → Structuring → Proposal / RFP → Selected → Pricing → Closed (+ Lost, On Hold). Developer deals: Developer Intro → Project Scoped → Entitlements / District Formation → Structuring → Validation → Internal Committee → Approvals → Pricing → Closed (+ Lost, On Hold). Each deal records purpose, security, par, role, probability, **MA, bond counsel, trustee**, competing banks, and **RFP deadline**. |
| **Dates & reminders** | A **List / Calendar** toggle on both the Dashboard and the Dates page (each remembers your choice). The calendar is a month grid: color-coded by type, click a day for its details, hover a day and click **+** to add a date there, and step through any month (yearly items like birthdays and fiscal year end show in every year). Elections, bond elections, budget adoption, fiscal year end, charter renewal, rate studies, etc. (optionally yearly), each with a "start reminding N days before" lead time. Term ends, birthdays, anniversaries, RFP deadlines and expected pricing dates are pulled from your records automatically. |
| **Dashboard** | Overdue follow-ups first, then upcoming dates and reminders, then pipeline totals (par and probability-weighted par). |
| **Follow-up logic** | A contact is overdue when `last contact + cadence` (A 30 / B 90 / C 180 days, editable in Settings) has passed. A manual next-follow-up date overrides the cadence. Logging a contact updates last contact and clears a follow-up it satisfies. |
| **CSV import** | Outlook or Excel exports. Preview first; issuers are created and sector-guessed from the organization name; duplicates are skipped. |
| **Weekly email digest** | `python3 digest.py`. See below. |

## Weekly email digest

`digest.py` builds the overdue list, the next 14 days, and pipeline totals. With no SMTP settings it just
writes `data/digest.html`. To email it, set `PFCRM_SMTP_HOST`, `PFCRM_SMTP_PORT`, `PFCRM_SMTP_USER`,
`PFCRM_SMTP_PASS`, `PFCRM_MAIL_FROM` and `PFCRM_MAIL_TO`, then schedule it (cron, or Windows Task
Scheduler) for Monday morning. Check with your firm's IT before sending client names through an SMTP relay.

## Deliberately not in the proof of concept

Multi-user logins and permissions, Outlook sync, outstanding-debt tracking (bond series, call dates,
refunding savings), and compliance logs (G-37 contributions, etc.). The schema is plain tables, so
adding a `bonds` table linked to `issuers` is the natural next step.
