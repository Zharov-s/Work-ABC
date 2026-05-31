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

SEGMENT_QUERIES = {
    'electronics': [
        'производство электроники приборостроение Москва компания контакты руководитель',
        'электронные компоненты приборы производитель Москва офис',
        'разработка производство электроника Москва технопарк',
    ],
    'medtech': [
        'медицинское оборудование производство Москва компания контакты',
        'медтех диагностика лабораторное оборудование производитель Москва',
        'фармацевтика биотехнологии производство Москва компания',
    ],
    'robotics': [
        'робототехника автоматизация производство Москва компания контакты',
        'промышленные роботы беспилотники производитель Москва',
        'системы автоматизации мехатроника разработка Москва',
    ],
    'it_hardware': [
        'производство серверов телекоммуникационное оборудование Москва компания',
        'отечественное ИТ hardware производство Москва офис',
        'вычислительная техника сетевое оборудование производитель Москва',
    ],
    'laser_optics': [
        'лазерные системы оптические приборы производство Москва компания',
        'фотоника оптика лазер разработка производитель Москва',
        'лазерные технологии производство научное оборудование Москва',
    ],
    'light_industrial': [
        'производство light industrial технопарк Москва компания контакты',
        'лёгкое производство R&D шоурум аренда Москва',
        'производственная компания Москва класс А технопарк офис',
    ],
}

REGION_SUFFIX = {
    'moscow':  'Москва',
    'mo':      'Московская область',
    'russia':  'Россия',
}

INDUSTRIES_LIST = [
    {'code': 'manufacturing', 'label': 'Производство'},
    {'code': 'it',            'label': 'ИТ и связь'},
    {'code': 'healthcare',    'label': 'Здравоохранение'},
    {'code': 'construction',  'label': 'Строительство'},
    {'code': 'transport',     'label': 'Транспорт'},
    {'code': 'media',         'label': 'Медиа'},
    {'code': 'finance',       'label': 'Финансы'},
    {'code': 'education',     'label': 'Образование'},
    {'code': 'culture',       'label': 'Культура'},
    {'code': 'gov',           'label': 'Госуправление'},
    {'code': 'unions',        'label': 'Объединения'},
    {'code': 'trade',         'label': 'Торговля'},
    {'code': 'services',      'label': 'Услуги'},
]

SCALE_SUFFIX = {
    'any':    '',
    'small':  'малый бизнес',
    'medium': 'средний бизнес',
    'large':  'крупный бизнес',
}

# Email-адреса общего назначения — не ЛПР, не сохранять
BLOCKED_EMAIL_PREFIXES = {
    'info', 'sales', 'office', 'support', 'mail', 'contact', 'zakaz',
    'hello', 'admin', 'reception', 'corp', 'marketing', 'pr', 'press',
    'media', 'hr', 'career', 'communications', 'comms', 'post', 'inbox',
    'noreply', 'no-reply', 'feedback', 'help', 'service', 'request',
}

# Юридические префиксы для нормализации имён компаний
_LEGAL_PREFIX = re.compile(
    r'\b(ООО|АО|ПАО|ЗАО|НКО|ГУП|МУП|ИП|ФГУП|НПП|НПО|ОАО|СРО)\s*["""«»]?',
    re.IGNORECASE,
)


# ── Вспомогательные функции ────────────────────────────────────────────────

def normalize_company_name(name: str) -> str:
    """Приводит название компании к нижнему регистру без юр. форм и кавычек."""
    if not name:
        return ''
    s = _LEGAL_PREFIX.sub('', name)
    s = re.sub(r'["«»“”„‘’\'`]', '', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def is_generic_email(email: str) -> bool:
    """True если адрес является общим ящиком, а не личным ЛПР."""
    if not email or '@' not in email:
        return True
    local = email.split('@')[0].lower()
    return local in BLOCKED_EMAIL_PREFIXES


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
        conn.execute(
            'UPDATE research_runs SET log_text = log_text || ? WHERE id=?',
            (entry + '\n', run_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Ollama helpers ─────────────────────────────────────────────────────────

def _ollama_chat(client, messages: list, expect_json: bool = True) -> str:
    kwargs = dict(
        model=OLLAMA_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=1000,
    )
    if expect_json:
        kwargs['response_format'] = {'type': 'json_object'}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ''


def _strip_think(raw: str) -> str:
    """Убирает <think>...</think> блок из ответа Qwen3."""
    if '<think>' in raw and '</think>' in raw:
        raw = raw[raw.rfind('</think>') + 8:].strip()
    return raw


def _check_ollama(client) -> bool:
    try:
        models = client.models.list()
        available = [m.id for m in models.data]
        return any(OLLAMA_MODEL in m for m in available)
    except Exception:
        return False


def _extract_companies(client, results_text: str, segment_label: str,
                       exclude_hint: str = '') -> list:
    exclude_clause = f'Исключай компании из сфер: {exclude_hint}. ' if exclude_hint else ''
    prompt = (
        'Ты помогаешь находить компании для аренды в промышленном технопарке класса A+ в Москве (Митино). '
        'Объект подходит для: производства, R&D, лабораторий, шоурума, light industrial. '
        'НЕ подходит: склады, ритейл, чистые офисы без производства, тяжёлая промышленность. '
        f'{exclude_clause}'
        'Из результатов поиска извлеки список реальных российских компаний. '
        'Верни ТОЛЬКО валидный JSON: '
        '{"companies": [{"name": "полное название компании", "website": "сайт или null", "description": "краткое описание"}]}'
    )
    try:
        raw  = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': f'Сегмент: {segment_label}\n\nРезультаты поиска:\n{results_text}'},
        ])
        data = json.loads(_strip_think(raw))
        return data.get('companies', [])
    except Exception:
        return []


def _extract_lpr(client, company: dict, results_text: str) -> dict | None:
    prompt = (
        'Ты ищешь контакты ЛПР (лица, принимающего решения) в компании. '
        'Приоритет ролей: Административный директор > Исполнительный директор > '
        'Заместитель генерального директора > HR-директор > Технический директор > '
        'Финансовый директор > Генеральный директор. '
        'ВАЖНО: извлекай ТОЛЬКО реальные данные из текста. Не придумывай. '
        'Email должен быть ЛИЧНЫМ (имя.фамилия@..., i.ivanov@...) — '
        'НЕ общим (info@, sales@, office@, support@ и т.п.). '
        'Верни ТОЛЬКО валидный JSON: '
        '{"person_name": "ФИО или null", "title": "Должность или null", '
        '"email": "личный email или null", "phone": "телефон или null", '
        '"source_url": "URL источника или null"}'
    )
    try:
        raw  = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': (
                f'Компания: {company.get("name")}\n'
                f'Сайт: {company.get("website")}\n\n'
                f'Найденная информация:\n{results_text}'
            )},
        ])
        data = json.loads(_strip_think(raw))
        if data.get('email') and not is_generic_email(data['email']):
            data['company_name'] = company.get('name', '')
            data['website']      = company.get('website', '')
            return data
        return None
    except Exception:
        return None


def _results_to_text(results: dict, max_chars: int = 600) -> str:
    parts = []
    for r in results.get('results', []):
        content = (r.get('content') or r.get('raw_content') or '')[:max_chars]
        parts.append(
            f"URL: {r.get('url', '')}\n"
            f"Заголовок: {r.get('title', '')}\n"
            f"Контент: {content}"
        )
    return '\n\n---\n\n'.join(parts)


# ── Основной worker ────────────────────────────────────────────────────────

def _research_worker(run_id: int, config: dict):
    from openai import OpenAI
    from tavily import TavilyClient

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key='ollama')
    tavily = TavilyClient(api_key=TAVILY_API_KEY)

    # Параметры из конфига
    raw_segments = config.get('segments', config.get('segment', 'electronics'))
    if isinstance(raw_segments, str):
        raw_segments = [raw_segments]
    segments_list = [s for s in raw_segments if s in SEGMENT_LABELS]
    if not segments_list:
        segments_list = ['electronics']

    region_key    = config.get('region', 'moscow')
    target_count  = int(config.get('count', 10))
    keywords      = config.get('keywords', '').strip()
    company_scale = config.get('company_scale', 'any')
    require_email = bool(config.get('require_email'))
    require_phone = bool(config.get('require_phone'))
    active_only   = bool(config.get('active_only', True))

    region_label = REGION_SUFFIX.get(region_key, 'Москва')
    scale_suffix = SCALE_SUFFIX.get(company_scale, '')
    active_str   = 'действующая компания' if active_only else ''

    seg_labels = [SEGMENT_LABELS.get(s, s) for s in segments_list]
    _log(run_id, f'🚀 Старт поиска: {", ".join(seg_labels)}')
    _log(run_id, f'   Регион: {region_label} | Цель: {target_count} | Масштаб: {SCALE_SUFFIX.get(company_scale) or "любой"}')
    _log(run_id, f'🤖 Модель: {OLLAMA_MODEL} (Ollama)')

    # Проверить Ollama
    if not _check_ollama(client):
        _log(run_id, f'❌ Ollama недоступна или модель {OLLAMA_MODEL} не загружена.')
        _log(run_id, 'Запустите: ollama serve')
        _log(run_id, f'Скачайте модель: ollama pull {OLLAMA_MODEL}')
        _set_run_status(run_id, 'failed')
        return

    # ── Загрузить память: все известные компании и email ──────────────────
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

    _log(run_id, f'📋 Память: {len(existing_companies)} компаний, {len(existing_emails)} email — новые пропущены не будут')
    _log(run_id, f'🔍 Ищем только НОВЫЕ компании, которых нет в базе')

    if keywords:
        _log(run_id, f'🔑 Доп. слова: {keywords}')

    # ── Строим список запросов ─────────────────────────────────────────────
    all_queries = []
    for seg in segments_list:
        for q in SEGMENT_QUERIES.get(seg, SEGMENT_QUERIES['electronics']):
            full_q = ' '.join(filter(None, [q, region_label, scale_suffix, active_str, keywords]))
            all_queries.append((full_q, SEGMENT_LABELS.get(seg, seg)))

    found_contacts   = []
    searched_names   = set()   # имена, уже проверенные в этой сессии

    for query, segment_label in all_queries:
        if len(found_contacts) >= target_count:
            break

        _log(run_id, f'🔍 [{segment_label}] {query}')
        try:
            search_res = tavily.search(query, max_results=8)
        except Exception as e:
            _log(run_id, f'❌ Ошибка Tavily: {e}')
            continue

        results_text = _results_to_text(search_res)
        companies    = _extract_companies(client, results_text, segment_label)
        _log(run_id, f'   Компаний в выдаче: {len(companies)}')

        for company in companies:
            if len(found_contacts) >= target_count:
                break

            name     = (company.get('name') or '').strip()
            norm     = normalize_company_name(name)

            if not name or not norm:
                continue

            # Проверить: компания уже в базе?
            if norm in existing_companies:
                _log(run_id, f'   ⏭  {name} — уже в базе, пропускаем')
                continue

            # Проверить: уже обрабатывали в этой сессии?
            if norm in searched_names:
                continue
            searched_names.add(norm)

            _log(run_id, f'🏢 Новая компания: {name}')

            contact_query = f'{name} контакты директор email телефон сайт'
            try:
                contact_res = tavily.search(contact_query, max_results=5)
            except Exception as e:
                _log(run_id, f'   ⚠️ Ошибка Tavily контакты: {e}')
                continue

            contact_text = _results_to_text(contact_res, 800)
            lpr          = _extract_lpr(client, company, contact_text)

            if not lpr:
                _log(run_id, '   ⚠️  ЛПР не найден')
                continue

            email = (lpr.get('email') or '').lower().strip()
            phone = (lpr.get('phone') or '').strip()

            # Фильтр: общий email
            if email and is_generic_email(email):
                _log(run_id, f'   ⛔  {email} — общий адрес (info/sales/office), пропускаем')
                continue

            # Фильтр: email уже в базе
            if email and email in existing_emails:
                _log(run_id, f'   ⏭  {email} — email уже в базе')
                continue

            # Фильтр: требуется email
            if require_email and not email:
                _log(run_id, '   ⏭  нет email (фильтр: только с email)')
                continue

            # Фильтр: требуется телефон
            if require_phone and not phone:
                _log(run_id, '   ⏭  нет телефона (фильтр: только с телефоном)')
                continue

            # Добавляем в найденное
            if email:
                existing_emails.add(email)
            existing_companies.add(norm)

            lpr['segment'] = segment_label
            lpr['region']  = region_label
            lpr['email']   = email or None
            found_contacts.append(lpr)

            person = lpr.get('person_name') or '???'
            detail = ' | '.join(filter(None, [email, phone]))
            _log(run_id, f'   ✅ {person} — {detail}')

            time.sleep(0.3)

    # ── Сохранить в базу ───────────────────────────────────────────────────
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
            _log(run_id, f'   ⚠️ Ошибка записи: {e}')

    conn.execute(
        "UPDATE research_runs SET status='done', completed_at=datetime('now'), found_count=? WHERE id=?",
        (saved, run_id)
    )
    conn.commit()
    conn.close()

    _log(run_id, f'')
    _log(run_id, f'✅ Поиск завершён.')
    _log(run_id, f'   Найдено и сохранено в базу: {saved} новых контактов')
    _log(run_id, f'   Запрошено: {target_count} | Обработано компаний: {len(searched_names)}')

    _set_run_status(run_id, 'done', found_count=saved)


def _set_run_status(run_id: int, status: str, found_count: int = 0):
    with _lock:
        if run_id in _runs:
            _runs[run_id]['status']      = status
            _runs[run_id]['found_count'] = found_count
    try:
        conn = get_db()
        conn.execute(
            "UPDATE research_runs SET status=?, completed_at=datetime('now'), found_count=? WHERE id=?",
            (status, found_count, run_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def start_research(config: dict) -> int:
    conn = get_db()
    cur  = conn.execute(
        'INSERT INTO research_runs(config_json, status) VALUES(?,?)',
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
