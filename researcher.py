import os
import re
import json
import time
import threading
from datetime import datetime
from database import get_db

TAVILY_API_KEY  = os.getenv('TAVILY_API_KEY', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'qwen3:4b')

_runs: dict = {}
_lock = threading.Lock()


# ── Константы ──────────────────────────────────────────────────────────────

SEGMENT_LABELS = {
    'electronics':     'Электроника и приборостроение',
    'medtech':         'Медтех и фармацевтика',
    'robotics':        'Робототехника и автоматизация',
    'it_hardware':     'IT-производство и hardware',
    'laser_optics':    'Лазерные и оптические технологии',
    'light_industrial':'Прочее light industrial',
}

REGION_SUFFIX = {
    'moscow':  'Москва',
    'mo':      'Московская область',
    'russia':  'Россия',
}

SCALE_SUFFIX = {
    'any':    '',
    'small':  'малый бизнес',
    'medium': 'средний бизнес',
    'large':  'крупный бизнес',
}

# ── Поисковые запросы ───────────────────────────────────────────────────────

# Основные запросы через Tavily (широкий поиск)
SEGMENT_QUERIES = {
    'electronics': [
        'производство электроники приборостроение компания Москва руководитель',
        'электронные компоненты датчики контроллеры производитель Москва офис',
        'разработка производство электроника Москва контакты директор',
    ],
    'medtech': [
        'медицинское оборудование производство компания Москва контакты',
        'медтех диагностика лабораторное оборудование производитель Москва',
        'фармацевтика биотехнологии пилотное производство Москва компания',
    ],
    'robotics': [
        'робототехника промышленная автоматизация производство Москва компания',
        'беспилотные системы дроны производитель Москва офис',
        'мехатроника приводы сервосистемы разработка Москва',
    ],
    'it_hardware': [
        'производство серверов телекоммуникационное оборудование Москва',
        'отечественное ИТ hardware производство офис Москва',
        'вычислительная техника сетевое оборудование производитель Москва',
    ],
    'laser_optics': [
        'лазерные системы оптические приборы производство Москва',
        'фотоника волоконная оптика производитель Москва',
        'лазерные технологии производство научное оборудование Москва',
    ],
    'light_industrial': [
        'лёгкое производство R&D шоурум технопарк Москва компания',
        'производственная компания класс А технопарк Москва',
        'сборочное производство инжиниринг сервисный центр Москва',
    ],
}

# Дополнительные каналы: технопарки, выставки, импортозамещение
EXTRA_DISCOVERY_QUERIES = {
    'electronics': [
        'резиденты ОЭЗ технопарк Москва производство электроника 2024 2025',
        'ExpoElectronica 2025 экспоненты участники производитель Москва',
        'импортозамещение электроника производство Москва компания контракт',
        'кластер электроники Зеленоград ОЭЗ резиденты компании',
    ],
    'medtech': [
        'резиденты технопарка Москва медицинское оборудование производство',
        'Pharmtech 2024 2025 экспоненты Москва производитель медтех',
        'импортозамещение медицинские изделия производство Москва компания',
        'московский медицинский кластер резидент производитель',
    ],
    'robotics': [
        'технопарк Москва робототехника автоматизация резидент компания',
        'ИННОПРОМ 2024 2025 промышленная автоматизация Москва экспонент',
        'импортозамещение промышленные роботы производство Москва',
        'ОЭЗ Москва мехатроника приводы производство резидент',
    ],
    'it_hardware': [
        'резиденты технопарка Москва производство ИТ оборудование серверы',
        'российские производители серверов коммутаторов Москва 2024 2025',
        'импортозамещение ИТ инфраструктура серверы производство Москва компания',
        'Rusnanotech ОЭЗ Москва ИТ оборудование резидент',
    ],
    'laser_optics': [
        'технопарк Москва лазерные оптические системы производство резидент',
        'Фотоника 2024 2025 Москва участники производитель лазеры',
        'импортозамещение лазеры оптика производство Москва компания',
    ],
    'light_industrial': [
        'резиденты промышленного технопарка Москва лёгкое производство R&D',
        'технопарк Москва производство шоурум офис аренда класс А',
        'московские производственные компании технопарк сборка инжиниринг',
        'резиденты технополис Москва производство 2024',
    ],
}

# Заблокированные общие email-адреса
BLOCKED_EMAIL_PREFIXES = {
    'info', 'sales', 'office', 'support', 'mail', 'contact', 'zakaz',
    'hello', 'admin', 'reception', 'corp', 'marketing', 'pr', 'press',
    'media', 'hr', 'career', 'communications', 'comms', 'post', 'inbox',
    'noreply', 'no-reply', 'feedback', 'help', 'service', 'request',
    'quality', 'tender', 'zakupki', 'buh', 'director', 'general',
}

# Юридические форм-факторы для нормализации
_LEGAL_PREFIX = re.compile(
    r'\b(ООО|АО|ПАО|ЗАО|НКО|ГУП|МУП|ИП|ФГУП|НПП|НПО|ОАО|СРО|ЗАО|ФКУ|ФГБУ|ФГБОУ)\s*["""«»]?',
    re.IGNORECASE,
)

# Regex для извлечения ФИО директора из сниппетов rusprofile/zachestnyibiznes
_DIRECTOR_PATTERNS = [
    # "Генеральный директор ... - Фамилия Имя Отчество"
    re.compile(r'(?:Генеральный директор|ГД).{0,60}[-—]\s*([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)', re.IGNORECASE),
    # "Директор - Фамилия Имя Отчество"
    re.compile(r'(?:Директор|Руководитель)\s*[-—:]\s*([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)'),
    # "Директор - Фамилия И.О."
    re.compile(r'(?:Директор|Руководитель)\s*[-—:]\s*([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)'),
    # "Генеральный директор: Фамилия ..."
    re.compile(r'(?:Генеральный директор|директор)[^.]{0,30}[:]\s*([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)', re.IGNORECASE),
    # "ГД Фамилия Имя Отчество"
    re.compile(r'\bГД\s+([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)'),
]

# Regex для извлечения email из текста
_EMAIL_RE = re.compile(r'[\w.+\-]+@[\w\-]+\.[a-zA-Z]{2,}')


# ── Вспомогательные функции ────────────────────────────────────────────────

def normalize_company_name(name: str) -> str:
    if not name:
        return ''
    s = _LEGAL_PREFIX.sub('', name)
    s = re.sub(r'["«»""„\'\`]', '', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def is_generic_email(email: str) -> bool:
    if not email or '@' not in email:
        return True
    local = email.split('@')[0].lower()
    return local in BLOCKED_EMAIL_PREFIXES


def extract_director_name(text: str) -> str | None:
    """Извлекает ФИО директора из текста сниппета rusprofile/zachestnyibiznes."""
    for pat in _DIRECTOR_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip()
            # Базовая валидация: минимум 2 слова, кириллица
            if len(name.split()) >= 2 and re.search(r'[а-яё]', name, re.IGNORECASE):
                return name
    return None


def extract_emails_from_text(text: str) -> list[str]:
    """Извлекает все email-адреса из текста, фильтруя общие."""
    found = _EMAIL_RE.findall(text)
    return [e.lower() for e in found if not is_generic_email(e)]


def get_run_status(run_id: int):
    with _lock:
        return _runs.get(run_id)


def _log(run_id: int, msg: str):
    ts    = datetime.now().strftime('%H:%M:%S')
    entry = f'[{ts}] {msg}'
    with _lock:
        if run_id in _runs:
            _runs[run_id]['log'].append(entry)
    try:
        conn = get_db()
        conn.execute('UPDATE research_runs SET log_text = log_text || ? WHERE id=?',
                     (entry + '\n', run_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _set_run_status(run_id: int, status: str, found_count: int = 0):
    with _lock:
        if run_id in _runs:
            _runs[run_id]['status']      = status
            _runs[run_id]['found_count'] = found_count
    try:
        conn = get_db()
        conn.execute(
            "UPDATE research_runs SET status=?, completed_at=datetime('now'), found_count=? WHERE id=?",
            (status, found_count, run_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Ollama ─────────────────────────────────────────────────────────────────

def _ollama_chat(client, messages: list, expect_json: bool = True) -> str:
    kwargs = dict(model=OLLAMA_MODEL, messages=messages, temperature=0.1, max_tokens=800)
    if expect_json:
        kwargs['response_format'] = {'type': 'json_object'}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ''


def _strip_think(raw: str) -> str:
    if '<think>' in raw and '</think>' in raw:
        return raw[raw.rfind('</think>') + 8:].strip()
    return raw


def _check_ollama(client) -> bool:
    try:
        models = client.models.list()
        return any(OLLAMA_MODEL in m.id for m in models.data)
    except Exception:
        return False


# ── AI-экстракторы ─────────────────────────────────────────────────────────

def _extract_companies(client, results_text: str, segment_label: str) -> list:
    prompt = (
        'Ты помогаешь находить компании для аренды в промышленном технопарке класса A+ в Москве (Митино). '
        'Объект: производство, R&D, лаборатории, шоурум, light industrial. '
        'НЕ подходят: склады, ритейл, чистые офисы без производства, тяжёлая промышленность. '
        'Из результатов поиска извлеки список реальных российских компаний. '
        'Верни ТОЛЬКО JSON: {"companies": [{"name": "название", "website": "сайт или null", "description": "описание"}]}'
    )
    try:
        raw  = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': f'Сегмент: {segment_label}\n\n{results_text}'},
        ])
        return json.loads(_strip_think(raw)).get('companies', [])
    except Exception:
        return []


def _extract_lpr_from_combined(client, company: dict, combined_text: str,
                                known_director: str | None = None) -> dict | None:
    director_hint = (
        f'Известно что директор компании: {known_director}. '
        'Найди его прямой рабочий email или телефон. '
        if known_director else ''
    )
    prompt = (
        'Ты ищешь контакты ЛПР (лица, принимающего решения) в российской компании. '
        'Приоритет ролей: Административный директор > Исполнительный директор > '
        'Заместитель генерального директора > HR-директор > Технический директор > '
        'Финансовый директор > Генеральный директор. '
        f'{director_hint}'
        'Email должен быть ЛИЧНЫМ (имя.фамилия@, i.ivanov@ и т.п.) — '
        'НЕ общим (info@, sales@, office@, support@ и т.п.). '
        'Извлекай ТОЛЬКО то, что есть в тексте. Не придумывай. '
        'Верни ТОЛЬКО JSON: {"person_name": "ФИО или null", "title": "должность или null", '
        '"email": "личный email или null", "phone": "телефон или null", "source_url": "URL или null"}'
    )
    try:
        raw  = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': (
                f'Компания: {company.get("name")}\n'
                f'Сайт: {company.get("website") or "неизвестен"}\n\n'
                f'Собранная информация:\n{combined_text}'
            )},
        ])
        data = json.loads(_strip_think(raw))
        email = (data.get('email') or '').lower().strip()
        if email and is_generic_email(email):
            data['email'] = None
        # Если директор известен но ИИ не нашёл имя — подставляем
        if known_director and not data.get('person_name'):
            data['person_name'] = known_director
            data['title']       = data.get('title') or 'Генеральный директор'
        if data.get('person_name') or data.get('email') or data.get('phone'):
            data['company_name'] = company.get('name', '')
            data['website']      = company.get('website', '')
            return data
        return None
    except Exception:
        return None


def _results_to_text(results: dict, max_chars: int = 500) -> str:
    parts = []
    for r in results.get('results', []):
        content = (r.get('content') or r.get('raw_content') or '')[:max_chars]
        parts.append(f"URL: {r.get('url', '')}\nЗаголовок: {r.get('title', '')}\nКонтент: {content}")
    return '\n\n---\n\n'.join(parts)


# ── Многопроходный поиск ЛПР ──────────────────────────────────────────────

def _multi_pass_lpr_search(tavily, company: dict, log_fn) -> tuple[str | None, str]:
    """
    Трёхпроходный поиск контактов ЛПР:
    1. Rusprofile/Zachestnyibiznes → директор (regex из сниппета)
    2. Email по имени директора + компания
    3. Контакты с официального сайта

    Возвращает (director_name, combined_text).
    """
    name    = company.get('name', '')
    website = company.get('website') or ''
    domain  = ''
    if website:
        domain = website.replace('https://', '').replace('http://', '').split('/')[0]

    combined_parts = []
    director_name  = None

    # Проход 1: директор из российских реестров
    q1 = f'"{name}" генеральный директор'
    try:
        r1 = tavily.search(q1, max_results=4)
        text1 = _results_to_text(r1, 600)
        combined_parts.append(text1)
        # Пробуем regex-извлечение директора из каждого сниппета
        for item in r1.get('results', []):
            snippet = (item.get('content') or '')
            found   = extract_director_name(snippet)
            if found:
                director_name = found
                log_fn(f'   📋 Директор из реестра: {director_name}')
                break
    except Exception:
        pass
    time.sleep(0.2)

    # Проход 2: если нашли директора — ищем его личный email
    if director_name:
        q2 = f'"{director_name}" "{name}" email'
        try:
            r2 = tavily.search(q2, max_results=3)
            text2 = _results_to_text(r2, 500)
            combined_parts.append(text2)
            # Быстрая проверка: есть ли личные email прямо в сниппетах
            for item in r2.get('results', []):
                emails = extract_emails_from_text(item.get('content', ''))
                if emails:
                    log_fn(f'   📧 Личный email в выдаче: {emails[0]}')
                    break
        except Exception:
            pass
        time.sleep(0.2)

    # Проход 3: контакты с сайта компании (или общий поиск)
    if domain:
        q3 = f'site:{domain} контакты директор email'
    else:
        q3 = f'"{name}" контакты email телефон официальный сайт'
    try:
        r3 = tavily.search(q3, max_results=3)
        combined_parts.append(_results_to_text(r3, 500))
    except Exception:
        pass

    return director_name, '\n\n===\n\n'.join(combined_parts)


# ── Основной worker ────────────────────────────────────────────────────────

def _research_worker(run_id: int, config: dict):
    from openai import OpenAI
    from tavily import TavilyClient

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key='ollama')
    tavily = TavilyClient(api_key=TAVILY_API_KEY)

    # Параметры
    raw_segs = config.get('segments', config.get('segment', 'electronics'))
    if isinstance(raw_segs, str):
        raw_segs = [raw_segs]
    segments_list = [s for s in raw_segs if s in SEGMENT_LABELS] or ['electronics']

    region_key    = config.get('region', 'moscow')
    target_count  = int(config.get('count', 10))
    keywords      = config.get('keywords', '').strip()
    company_scale = config.get('company_scale', 'any')
    require_email = bool(config.get('require_email'))
    require_phone = bool(config.get('require_phone'))

    region_label = REGION_SUFFIX.get(region_key, 'Москва')
    scale_suffix = SCALE_SUFFIX.get(company_scale, '')

    seg_labels = [SEGMENT_LABELS.get(s, s) for s in segments_list]
    _log(run_id, f'🚀 Старт: {", ".join(seg_labels)} | {region_label} | цель={target_count}')
    _log(run_id, f'🤖 Модель: {OLLAMA_MODEL} (Ollama)')

    if not _check_ollama(client):
        _log(run_id, f'❌ Ollama недоступна. Запустите: ollama serve')
        _set_run_status(run_id, 'failed')
        return

    # Память базы — что уже знаем
    conn_main = get_db()
    existing_emails = {
        r['email'].lower()
        for r in conn_main.execute('SELECT email FROM contacts WHERE email IS NOT NULL').fetchall()
    }
    existing_companies = {
        normalize_company_name(r['company_name'])
        for r in conn_main.execute('SELECT company_name FROM contacts WHERE company_name IS NOT NULL').fetchall()
        if r['company_name']
    }
    conn_main.close()
    _log(run_id, f'📋 В базе: {len(existing_companies)} компаний, {len(existing_emails)} email — дубли пропустим')

    if keywords:
        _log(run_id, f'🔑 Доп. слова: {keywords}')

    # Строим список запросов: основные + дополнительные каналы
    all_queries = []
    for seg in segments_list:
        for q in SEGMENT_QUERIES.get(seg, []):
            full_q = ' '.join(filter(None, [q, region_label, scale_suffix, keywords]))
            all_queries.append((full_q, SEGMENT_LABELS.get(seg, seg), 'tavily'))
        # Дополнительные каналы: технопарки, выставки, импортозамещение
        for q in EXTRA_DISCOVERY_QUERIES.get(seg, []):
            full_q = ' '.join(filter(None, [q, keywords]))
            all_queries.append((full_q, SEGMENT_LABELS.get(seg, seg), 'extra'))

    found_contacts = []
    searched_names = set()

    for query, segment_label, source_tag in all_queries:
        if len(found_contacts) >= target_count:
            break

        icon = '🔍' if source_tag == 'tavily' else '🏭'
        _log(run_id, f'{icon} [{segment_label}] {query}')

        try:
            search_res = tavily.search(query, max_results=7)
        except Exception as e:
            _log(run_id, f'❌ Tavily: {e}')
            continue

        companies = _extract_companies(client, _results_to_text(search_res), segment_label)
        _log(run_id, f'   Компаний в выдаче: {len(companies)}')

        for company in companies:
            if len(found_contacts) >= target_count:
                break

            name = (company.get('name') or '').strip()
            norm = normalize_company_name(name)
            if not name or not norm:
                continue
            if norm in existing_companies:
                _log(run_id, f'   ⏭  {name} — уже в базе')
                continue
            if norm in searched_names:
                continue
            searched_names.add(norm)

            _log(run_id, f'🏢 Новая: {name}')

            # Многопроходный поиск ЛПР
            director_name, combined_text = _multi_pass_lpr_search(
                tavily, company, lambda m: _log(run_id, m)
            )

            if not combined_text.strip():
                _log(run_id, '   ⚠️  Ничего не найдено по контактам')
                continue

            lpr = _extract_lpr_from_combined(client, company, combined_text, director_name)

            if not lpr:
                _log(run_id, '   ⚠️  ЛПР не определён')
                continue

            email = (lpr.get('email') or '').lower().strip()
            phone = (lpr.get('phone') or '').strip()

            if email and is_generic_email(email):
                _log(run_id, f'   ⛔  {email} — общий адрес, пропускаем')
                lpr['email'] = None
                email = ''

            if email and email in existing_emails:
                _log(run_id, f'   ⏭  {email} — уже в базе')
                continue

            if require_email and not email:
                _log(run_id, '   ⏭  нет личного email (фильтр)')
                continue
            if require_phone and not phone:
                _log(run_id, '   ⏭  нет телефона (фильтр)')
                continue

            if email:
                existing_emails.add(email)
            existing_companies.add(norm)

            lpr['segment'] = segment_label
            lpr['region']  = region_label
            lpr['email']   = email or None
            found_contacts.append(lpr)

            person = lpr.get('person_name') or director_name or '???'
            detail = ' | '.join(filter(None, [email, phone]))
            _log(run_id, f'   ✅ {person} — {detail or "имя найдено, email в поиске"}')

            time.sleep(0.3)

    # Сохранить в базу
    conn  = get_db()
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
            _log(run_id, f'⚠️ Ошибка записи: {e}')

    conn.execute(
        "UPDATE research_runs SET status='done', completed_at=datetime('now'), found_count=? WHERE id=?",
        (saved, run_id),
    )
    conn.commit()
    conn.close()

    _log(run_id, '')
    _log(run_id, f'✅ Готово. Сохранено в базу: {saved} новых контактов')
    _log(run_id, f'   Запрошено: {target_count} | Проверено компаний: {len(searched_names)}')
    _log(run_id, f'   Запросов выполнено: {len(all_queries)} ({len(SEGMENT_QUERIES.get(segments_list[0],[]))*len(segments_list)} основных + {len(EXTRA_DISCOVERY_QUERIES.get(segments_list[0],[]))*len(segments_list)} дополнительных)')

    _set_run_status(run_id, 'done', found_count=saved)


def start_research(config: dict) -> int:
    conn = get_db()
    cur  = conn.execute(
        'INSERT INTO research_runs(config_json, status) VALUES(?,?)',
        (json.dumps(config, ensure_ascii=False), 'running'),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()

    with _lock:
        _runs[run_id] = {'status': 'running', 'log': [], 'found_count': 0}

    t = threading.Thread(target=_research_worker, args=(run_id, config), daemon=True)
    t.start()
    return run_id
