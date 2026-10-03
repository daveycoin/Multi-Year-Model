#!/usr/bin/env python3
"""Build the weekly digest email. Run it from Task Scheduler / cron every Monday morning.

Without SMTP settings it writes data/digest.html and prints the path (nothing is sent).
To send, set: PFCRM_SMTP_HOST, PFCRM_SMTP_PORT (587), PFCRM_SMTP_USER, PFCRM_SMTP_PASS,
PFCRM_MAIL_FROM, PFCRM_MAIL_TO. Use only an SMTP account your firm allows.
"""
import datetime as dt
import os
import smtplib
import sys
from email.message import EmailMessage

import server


def main():
    conn = server.connect()
    html_body, text_body = server.build_digest(conn, dt.date.today())
    host, to = os.environ.get("PFCRM_SMTP_HOST"), os.environ.get("PFCRM_MAIL_TO")
    if not (host and to):
        out = os.path.join(os.path.dirname(server.DB_PATH), "digest.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"SMTP not configured; wrote digest to {out}")
        return 0
    msg = EmailMessage()
    msg["Subject"] = f"CRM digest, {dt.date.today():%b %d}"
    msg["From"] = os.environ.get("PFCRM_MAIL_FROM", os.environ.get("PFCRM_SMTP_USER", to))
    msg["To"] = to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(host, int(os.environ.get("PFCRM_SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.environ.get("PFCRM_SMTP_USER"):
            s.login(os.environ["PFCRM_SMTP_USER"], os.environ.get("PFCRM_SMTP_PASS", ""))
        s.send_message(msg)
    print(f"Digest sent to {to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
