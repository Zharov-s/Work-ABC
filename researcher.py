import os
import json
import time
import threading
from datetime import datetime
from database import get_db

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', '')

# Хранилище запусков в памяти (run_id -> dict)
_runs: dict = {}
_lock = threading.Lock()


SEGMENT_LABELS = {
    'electronics':    'Электроника и приборостроение',
    'medtech':        'Медтех и фармацевтика',
    'robotics':       'Робототехника и автоматизация',
    'it_hardware':    'IT-производство и hardware',
    'laser_optics':   'Лазерные и оптические технологии',
    'light_industrial':'Прочее light industrial',
}

SEGMENT_QUERIES = {
    'electronics': [
        'производство электроники Москва компания контакты директор',
        'приборостроение Москва производитель сайт',
        'электронная промышленность компания Москва разработка',
    ],
    'medtech': [
        'медицинское оборудование производство Москва компания',
        'медтех стартап производитель Москва контакты',
        'медицинские приборы диагностика производство Москва',
    ],
    'robotics': [
        'робототехника автоматизация производство Москва компания',
        'промышленные роботы беспилотники производитель Москва',
        'мехатроника автоматизация Москва сайт контакты',
    ],
    'it_hardware': [
        'производство серверов hardware Москва компания',
        'телекоммуникационное оборудование производитель Москва',
        'отечественное ИТ оборудование производство Москва',
    ],
    'laser_optics': [
        'лазерные системы производство Москва компания',
        'оптические приборы производитель Москва',
        'лазерные технологии разработка производство Москва',
    ],
    'light_industrial': [
        'легкое производство light industrial Москва компания',
        'промышленный технопарк резиденты производство Москва',
        'производственная компания Москва класс А технопарк',
    ],
}

REGION_SUFFIX = {
    'moscow':    'Москва',
    'mo':        'Московская область',
    'russia':    'Россия',
}


def _log(run_id: int, msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    entry = f'[{ts}] {msg}'
    with _lock:
        if run_id in _runs:
            _runs[run_id]['log'].append(entry)
    # Persist to DB
    try:
        conn = get_db()
        conn.execute(
            "UPDATE research_runs SET log_text = log_text || ? WHERE id=?",
            (entry + '\n', run_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_run_status(run_id: int):
    with _lock:
        return _runs.get(run_id)


def _extract_companies(client, results_text: str, segment_label: str) -> list:
    try:
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Ты помогаешь находить компании для аренды в промышленном технопарке класса A+ в Москве (Митино). '
                        'Объект подходит для: производства, R&D, лабораторий, шоурума, light industrial. '
                        'НЕ подходит: склады, ритейл, офисы без производства, тяжёлая промышленность. '
                        'Из результатов поиска извлеки список реальных российских компаний. '
                        'Верни JSON: {"companies": [{"name": "...", "website": "...", "description": "..."}]}'
                    )
                },
                {
                    'role': 'user',
                    'content': f'Сегмент: {segment_label}\n\nРезультаты поиска:\n{results_text}'
                }
            ],
            response_format={'type': 'json_object'},
            max_tokens=1500,
        )
        data = json.loads(resp.choices[0].message.content)
        return data.get('companies', [])
    except Exception as e:
        return []


def _extract_lpr(client, company: dict, results_text: str) -> dict | None:
    try:
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Ты ищешь контакты ЛПР (лица, принимающего решения) в компании. '
                        'Приоритет ролей: 1. Административный директор, 2. Исполнительный директор, '
                        '3. Заместитель генерального директора, 4. HR-директор, 5. Технический директор, '
                        '6. Финансовый директор, 7. Генеральный директор / владелец. '
                        'ВАЖНО: извлекай ТОЛЬКО реальные данные из текста. Не придумывай. '
                        'Верни JSON: {"person_name": "ФИО или null", "title": "Должность или null", '
                        '"email": "email или null", "phone": "телефон или null", "source_url": "URL"}'
                    )
                },
                {
                    'role': 'user',
                    'content': (
                        f'Компания: {company.get("name")}\n'
                        f'Сайт: {company.get("website")}\n\n'
                        f'Найденная информация:\n{results_text}'
                    )
                }
            ],
            response_format={'type': 'json_object'},
            max_tokens=400,
        )
        data = json.loads(resp.choices[0].message.content)
        if data.get('email'):
            data['company_name'] = company.get('name', '')
            data['website'] = company.get('website', '')
            return data
        return None
    except Exception:
        return None


def _results_to_text(results: dict, max_chars_per_result: int = 600) -> str:
    parts = []
    for r in results.get('results', []):
        content = r.get('content', '') or r.get('raw_content', '') or ''
        parts.append(
            f"URL: {r.get('url', '')}\n"
            f"Заголовок: {r.get('title', '')}\n"
            f"Контент: {content[:max_chars_per_result]}"
        )
    return '\n\n---\n\n'.join(parts)


def _research_worker(run_id: int, config: dict):
    from openai import OpenAI
    from tavily import TavilyClient

    openai_key = os.getenv('OPENAI_API_KEY', OPENAI_API_KEY)
    tavily_key = os.getenv('TAVILY_API_KEY', TAVILY_API_KEY)

    client  = OpenAI(api_key=openai_key)
    tavily  = TavilyClient(api_key=tavily_key)

    segment      = config.get('segment', 'electronics')
    region_key   = config.get('region', 'moscow')
    target_count = int(config.get('count', 10))
    keywords     = config.get('keywords', '').strip()

    segment_label = SEGMENT_LABELS.get(segment, segment)
    region_label  = REGION_SUFFIX.get(region_key, 'Москва')

    _log(run_id, f'🚀 Старт поиска: {segment_label}, {region_label}, цель={target_count}')
    if keywords:
        _log(run_id, f'🔑 Доп. слова: {keywords}')

    queries = SEGMENT_QUERIES.get(segment, SEGMENT_QUERIES['electronics'])
    # Добавить регион и ключевые слова к запросам
    queries = [f'{q} {region_label} {keywords}'.strip() for q in queries]

    found_contacts = []
    searched_names: set = set()

    conn_main = get_db()
    # Загрузить уже существующие email из БД для дедупликации
    existing_emails = {
        r['email'] for r in conn_main.execute('SELECT email FROM contacts').fetchall()
    }
    conn_main.close()

    for query in queries:
        if len(found_contacts) >= target_count:
            break

        _log(run_id, f'🔍 Поиск: {query}')
        try:
            search_res = tavily.search(query, max_results=8)
        except Exception as e:
            _log(run_id, f'❌ Ошибка поиска: {e}')
            continue

        results_text = _results_to_text(search_res)
        companies    = _extract_companies(client, results_text, segment_label)
        _log(run_id, f'   Найдено компаний в выдаче: {len(companies)}')

        for company in companies:
            if len(found_contacts) >= target_count:
                break

            name = (company.get('name') or '').strip()
            if not name or name in searched_names:
                continue
            searched_names.add(name)

            _log(run_id, f'🏢 Проверяем: {name}')

            contact_query = f'{name} контакты директор email телефон'
            try:
                contact_res = tavily.search(contact_query, max_results=5)
            except Exception as e:
                _log(run_id, f'   ⚠️ Ошибка поиска контактов: {e}')
                continue

            contact_text = _results_to_text(contact_res, 800)
            lpr          = _extract_lpr(client, company, contact_text)

            if lpr and lpr.get('email') and lpr['email'] not in existing_emails:
                existing_emails.add(lpr['email'])
                lpr['segment'] = segment_label
                lpr['region']  = region_label
                found_contacts.append(lpr)
                _log(run_id, f'   ✅ {lpr.get("person_name","??")} — {lpr["email"]}')
            elif lpr and lpr.get('email') in existing_emails:
                _log(run_id, f'   ⏭  {lpr["email"]} уже в базе, пропускаем')
            else:
                _log(run_id, f'   ⚠️  email не найден')

            time.sleep(0.3)

    # Сохранить в БД
    conn = get_db()
    saved = 0
    today = datetime.now().strftime('%Y-%m-%d')
    for c in found_contacts:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO contacts
                   (company_name, website, person_name, title, email, phone,
                    source_url, segment, region, date_found, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,'new')""",
                (c.get('company_name'), c.get('website'), c.get('person_name'),
                 c.get('title'), c.get('email'), c.get('phone'),
                 c.get('source_url'), c.get('segment'), c.get('region'), today)
            )
            saved += 1
        except Exception as e:
            _log(run_id, f'   ⚠️ Ошибка записи: {e}')

    conn.execute(
        "UPDATE research_runs SET status='done', completed_at=datetime('now'), found_count=? WHERE id=?",
        (saved, run_id)
    )
    conn.commit()
    conn.close()

    _log(run_id, f'✅ Готово! Сохранено {saved} новых контактов из {target_count} запрошенных')

    with _lock:
        if run_id in _runs:
            _runs[run_id]['status'] = 'done'
            _runs[run_id]['found_count'] = saved


def start_research(config: dict) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO research_runs(config_json, status) VALUES(?,?)",
        (json.dumps(config, ensure_ascii=False), 'running')
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()

    with _lock:
        _runs[run_id] = {'status': 'running', 'log': [], 'found_count': 0}

    t = threading.Thread(target=_research_worker, args=(run_id, config), daemon=True)
    t.start()
    return run_id
