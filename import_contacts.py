"""
Импортирует контакты из Research/output/found_contacts_memory.jsonl в SQLite.
Автоматически определяет сегмент по названию компании и сайту.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from database import init_db, get_db
from datetime import datetime

JSONL_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'Research', 'output', 'found_contacts_memory.jsonl'
)

# Ключевые слова для определения сегмента
SEGMENT_KEYWORDS = {
    'medtech': [
        'мед', 'pharma', 'фарм', 'bio', 'диагност', 'клиник', 'health',
        'лекарств', 'препарат', 'хирург', 'dental', 'стомат', 'нии пробиотик',
        'медика', 'медплант', 'медресурс',
    ],
    'robotics': [
        'робот', 'robot', 'автомат', 'беспилот', 'дрон', 'mechatronic',
        'мехатрон', 'привод', 'актуатор', 'серво',
    ],
    'it_hardware': [
        'сервер', 'server', 'yadro', 'ядро', 'аквариус', 'aquarius',
        'телеком', 'telecom', 'сеть', 'network', 'switch', 'router',
        'коммутат', 'вычислит', 'процессор', 'kraft', 'крафтвэй',
    ],
    'laser_optics': [
        'лазер', 'laser', 'оптик', 'optic', 'фотон', 'photon',
        'световод', 'волокон', 'spectro', 'спектр',
    ],
    'electronics': [
        'электрон', 'electro', 'приборо', 'instrument', 'датчик', 'sensor',
        'контроллер', 'controller', 'plc', 'scada', 'автоматиз',
        'микроэлектр', 'микросхем', 'чип', 'chip', 'резонит', 'rezonit',
        'миландр', 'milandr', 'eltex', 'элтекс', 'bolid', 'болид',
    ],
}


def detect_segment(company_name: str, website: str = '', title: str = '') -> str:
    """Определяет сегмент компании по ключевым словам в названии и сайте."""
    text = ' '.join([
        (company_name or '').lower(),
        (website or '').lower(),
        (title or '').lower(),
    ])
    for seg, keywords in SEGMENT_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return {
                'medtech':      'Медтех и фармацевтика',
                'robotics':     'Робототехника и автоматизация',
                'it_hardware':  'IT-производство и hardware',
                'laser_optics': 'Лазерные и оптические технологии',
                'electronics':  'Электроника и приборостроение',
            }[seg]
    return 'Электроника и приборостроение'  # дефолт для существующей базы


def run():
    init_db()
    if not os.path.exists(JSONL_PATH):
        print(f'Файл не найден: {JSONL_PATH}')
        return

    conn  = get_db()
    added = 0
    skipped_dup = 0
    skipped_bad = 0

    # Загружаем существующие email для дедупликации
    existing = {
        r['email'].lower()
        for r in conn.execute('SELECT email FROM contacts WHERE email IS NOT NULL').fetchall()
    }

    with open(JSONL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            email = (rec.get('email') or rec.get('Емайл') or '').strip().lower()
            if not email or '@' not in email:
                skipped_bad += 1
                continue

            if email in existing:
                skipped_dup += 1
                continue

            company = rec.get('company_name') or rec.get('Наименование') or ''
            website = rec.get('website') or rec.get('Сайт') or ''
            person  = rec.get('person_name') or rec.get('ФИО') or ''
            title   = rec.get('title') or rec.get('Должность') or ''
            phone   = rec.get('phone') or rec.get('Мобильный телефон или городской с добавочным') or ''
            segment = detect_segment(company, website, title)

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO contacts
                       (company_name, website, person_name, title, email, phone,
                        source_url, segment, region, date_found, status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        company, website, person, title, email, phone,
                        rec.get('source_url'),
                        segment,
                        'Москва',
                        rec.get('date_found', datetime.now().strftime('%Y-%m-%d')),
                        'new',
                    )
                )
                existing.add(email)
                added += 1
            except Exception as e:
                print(f'Ошибка: {e} — {email}')

    conn.commit()
    conn.close()
    print(f'Импорт завершён.')
    print(f'  Добавлено:        {added}')
    print(f'  Дублей (пропущ.): {skipped_dup}')
    print(f'  Без email:        {skipped_bad}')


if __name__ == '__main__':
    run()
