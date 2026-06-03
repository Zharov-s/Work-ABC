#!/usr/bin/env python3
"""
enrich_okved.py — Обогащение базы кодами ОКВЭД через DaData API.

Для каждого контакта с ИНН, но без ОКВЭД:
  1. Запрашивает данные компании через DaData
  2. Извлекает основной ОКВЭД
  3. Обновляет contacts.db

Требуется бесплатный токен DaData:
  - Регистрация: https://dadata.ru (2 минуты, карта не нужна)
  - Бесплатный лимит: 10 000 запросов/месяц
  - Токен: https://dadata.ru/profile/#info → «API-ключ (token)»

Использование:
  python3 enrich_okved.py --token YOUR_DADATA_TOKEN
  python3 enrich_okved.py --token YOUR_DADATA_TOKEN --limit 500   # первые 500
  python3 enrich_okved.py --token YOUR_DADATA_TOKEN --dry-run     # без записи в БД
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import requests

DB_PATH   = Path(__file__).parent / "webapp/data/contacts.db"
DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
DELAY      = 0.12    # ~8 req/sec — well under free-tier limit of 20/sec
COMMIT_EVERY = 100


def get_okved(inn: str, token: str, session: requests.Session) -> str | None:
    """Return main OKVED code for a company INN via DaData, or None on failure."""
    try:
        r = session.post(
            DADATA_URL,
            json={"query": inn.strip(), "count": 1},
            headers={
                "Authorization": f"Token {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        r.raise_for_status()
        suggestions = r.json().get("suggestions", [])
        if not suggestions:
            return None
        return suggestions[0].get("data", {}).get("okved") or None
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich contacts with OKVED via DaData")
    parser.add_argument("--token",   required=True,         help="DaData API token")
    parser.add_argument("--limit",   type=int, default=0,   help="Max contacts to process (0=all)")
    parser.add_argument("--dry-run", action="store_true",   help="Show results without writing to DB")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT id, company_name, inn FROM contacts
        WHERE (okved IS NULL OR okved = '')
          AND inn IS NOT NULL AND inn != ''
        ORDER BY id
    """
    if args.limit:
        sql += f" LIMIT {args.limit}"

    rows  = conn.execute(sql).fetchall()
    total = len(rows)

    if total == 0:
        print("Все контакты уже имеют ОКВЭД — ничего не делаем.")
        conn.close()
        return

    print(f"Контактов к обогащению: {total}")
    print(f"Примерное время:        ~{total * DELAY / 60:.0f} мин")
    if args.dry_run:
        print("DRY RUN — запись в БД отключена")
    print()

    session   = requests.Session()
    updated   = 0
    not_found = 0

    for i, row in enumerate(rows, 1):
        okved = get_okved(row["inn"], args.token, session)

        if okved:
            updated += 1
            if not args.dry_run:
                conn.execute("UPDATE contacts SET okved=? WHERE id=?", (okved, row["id"]))
                if updated % COMMIT_EVERY == 0:
                    conn.commit()
            if i <= 15 or updated % 200 == 0:
                print(f"  [{i:5}/{total}] {row['company_name'][:48]:48s} → {okved}")
        else:
            not_found += 1

        if i % 100 == 0:
            pct = i * 100 // total
            print(f"  [{pct:3}%] {i}/{total}  обновлено={updated}  не найдено={not_found}")

        time.sleep(DELAY)

    if not args.dry_run:
        conn.commit()
    conn.close()

    print()
    print(f"{'[DRY RUN] ' if args.dry_run else ''}Готово:")
    print(f"  Обновлено:   {updated}")
    print(f"  Не найдено:  {not_found}")
    print(f"  Всего:       {total}")


if __name__ == "__main__":
    main()
