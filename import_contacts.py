"""
Импортирует контакты из Research/output/found_contacts_memory.jsonl в SQLite.
Запускается один раз при первом старте или вручную.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from database import init_db, get_db
from datetime import datetime

JSONL_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'Research', 'output', 'found_contacts_memory.jsonl'
)

def run():
    init_db()
    if not os.path.exists(JSONL_PATH):
        print(f'Файл не найден: {JSONL_PATH}')
        return

    conn  = get_db()
    added = 0
    skipped = 0

    with open(JSONL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            email = (rec.get('email') or '').strip().lower()
            if not email or '@' not in email:
                skipped += 1
                continue

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO contacts
                       (company_name, website, person_name, title, email, phone,
                        source_url, segment, region, date_found, status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        rec.get('company_name') or rec.get('Наименование'),
                        rec.get('website') or rec.get('Сайт'),
                        rec.get('person_name') or rec.get('ФИО'),
                        rec.get('title') or rec.get('Должность'),
                        email,
                        rec.get('phone') or rec.get('Мобильный телефон или городской с добавочным'),
                        rec.get('source_url'),
                        rec.get('segment', 'Электроника и приборостроение'),
                        rec.get('region', 'Москва'),
                        rec.get('date_found', datetime.now().strftime('%Y-%m-%d')),
                        'new',
                    )
                )
                added += 1
            except Exception as e:
                print(f'Ошибка: {e} — {email}')

    conn.commit()
    conn.close()
    print(f'Импорт завершён. Добавлено: {added}, пропущено: {skipped}')

if __name__ == '__main__':
    run()
