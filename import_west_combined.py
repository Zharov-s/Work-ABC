"""Import contacts from Research/output/combined_west.md into contacts.db.

Strategy:
- One DB row per unique email address.
- Companies without email get one row with NULL email (phone-only record).
- Row 48 (Сбербанк терминал) is skipped — not a company.
- Segment = value from "Объект" column (West Plaza / Sezar Industrial).
- Deduplicates against existing DB rows by email before inserting.
"""

import re
import sqlite3
from datetime import date

MD_FILE = "Research/output/combined_west.md"
DB_FILE = "webapp/data/contacts.db"
DATE_FOUND = str(date.today())
SKIP_ROWS = {48}  # Сбербанк терминал — не офис компании


def parse_md_table(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells or cells[0] in ("№", "---:", ""):
                continue
            try:
                num = int(cells[0])
            except ValueError:
                continue
            if num in SKIP_ROWS:
                continue
            rows.append({
                "num":         num,
                "source":      cells[1].strip(),
                "company":     cells[2].strip(),
                "website_raw": cells[4].strip(),
                "email_raw":   cells[5].strip(),
                "phone_raw":   cells[6].strip(),
                "inn_raw":     cells[7].strip(),
                "comment":     cells[9].strip() if len(cells) > 9 else "",
            })
    return rows


def first_url(raw: str) -> str | None:
    if raw in ("—", ""):
        return None
    return raw.split(";")[0].strip()


def first_phone(raw: str) -> str | None:
    if raw in ("—", ""):
        return None
    p = raw.split(";")[0].strip()
    return re.split(r",\s*доб\.", p)[0].strip()


def split_emails(raw: str) -> list[str]:
    if raw in ("—", ""):
        return []
    return [e.strip().lower() for e in raw.split(";") if e.strip()]


def main():
    rows = parse_md_table(MD_FILE)
    conn = sqlite3.connect(DB_FILE)

    existing: set[str] = {
        r[0].lower()
        for r in conn.execute(
            "SELECT email FROM contacts WHERE email IS NOT NULL AND email != ''"
        ).fetchall()
    }

    inserted_with_email = 0
    inserted_no_email   = 0
    skipped_dup         = 0

    for row in rows:
        company = row["company"]
        segment = row["source"]
        website = first_url(row["website_raw"])
        phone   = first_phone(row["phone_raw"])
        inn     = row["inn_raw"] if row["inn_raw"] not in ("—", "") else None
        comment = row["comment"] if row["comment"] not in ("—", "") else None
        emails  = split_emails(row["email_raw"])

        if emails:
            for email in emails:
                if email in existing:
                    skipped_dup += 1
                    continue
                conn.execute(
                    """INSERT INTO contacts
                       (company_name, website, email, phone, inn,
                        segment, region, date_found, status, notes)
                       VALUES (?, ?, ?, ?, ?, ?, 'Москва', ?, 'new', ?)""",
                    (company, website, email, phone, inn,
                     segment, DATE_FOUND, comment),
                )
                existing.add(email)
                inserted_with_email += 1
        else:
            # No email — still useful as a lead with phone/website
            conn.execute(
                """INSERT INTO contacts
                   (company_name, website, phone, inn,
                    segment, region, date_found, status, notes)
                   VALUES (?, ?, ?, ?, ?, 'Москва', ?, 'new', ?)""",
                (company, website, phone, inn,
                 segment, DATE_FOUND, comment),
            )
            inserted_no_email += 1

    conn.commit()
    conn.close()

    print(f"Inserted with email:    {inserted_with_email}")
    print(f"Inserted without email: {inserted_no_email}")
    print(f"Skipped (duplicate):    {skipped_dup}")
    print(f"Total new rows:         {inserted_with_email + inserted_no_email}")


if __name__ == "__main__":
    main()
