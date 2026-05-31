import os
import json
import time
import threading
from datetime import datetime
from database import get_db

TAVILY_API_KEY  = os.getenv('TAVILY_API_KEY', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'qwen3:4b')

# Хранилище запусков в памяти (run_id -> dict)
_runs: dict = {}
_lock = threading.Lock()


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
        'производство электроники Москва компания контакты директор',
        'приборостроение Москва производитель сайт',
        'электронная промышленность компания Москва разработка',
    ],
    'medtech': [
        'медицинское оборудование производство Москва компания',
        'медтех производитель Москва контакты',
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
        'производственная компания Москва технопарк',
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

OKVED_SEARCH_TERMS = {
    'A':    'сельское хозяйство агропромышленный',
    'B':    'горнодобывающая добыча ископаемых',
    'C':    'обрабатывающее производство промышленность',
    'C10':  'пищевое производство продукты питания',
    'C13':  'текстильное производство',
    'C20':  'химическое производство реагенты',
    'C21':  'фармацевтика лекарства производство',
    'C22':  'пластмассы полимеры резина производство',
    'C25':  'металлоизделия металлообработка',
    'C26':  'электроника производство оптика компьютеры',
    'C27':  'электрооборудование производство',
    'C28':  'машиностроение оборудование',
    'C29':  'автомобилестроение автокомпоненты',
    'C32':  'производство готовых изделий',
    'C32.5':'медицинские инструменты оборудование производство',
    'C33':  'ремонт сервис техническое обслуживание',
    'D':    'энергетика электроснабжение',
    'E':    'водоснабжение утилизация',
    'F':    'строительство застройщик',
    'G':    'торговля дистрибуция',
    'H':    'транспорт логистика',
    'I':    'общественное питание гостиницы',
    'J':    'IT информационные технологии software',
    'J62':  'разработка программного обеспечения',
    'J63':  'IT услуги технологии',
    'K':    'финансы банки страхование',
    'L':    'недвижимость аренда',
    'M':    'научно-техническая деятельность R&D',
    'M71':  'проектирование инжиниринг',
    'M72':  'научные исследования разработки R&D лаборатория',
    'M73':  'маркетинговые исследования',
    'M74':  'консалтинг техническая деятельность',
    'N':    'административные услуги',
    'O':    'государственное управление',
    'P':    'образование обучение',
    'Q':    'здравоохранение медицина клиника',
    'R':    'культура спорт',
    'S':    'прочие услуги',
}

INDUSTRY_SEARCH_TERMS = {
    'manufacturing': 'производство промышленность завод',
    'it':            'IT информационные технологии',
    'healthcare':    'здравоохранение медицина',
    'construction':  'строительство',
    'transport':     'транспорт логистика',
    'media':         'медиа СМИ',
    'finance':       'финансы банки',
    'education':     'образование',
    'culture':       'культура спорт',
    'gov':           'государственное управление',
    'unions':        'объединения ассоциации',
    'trade':         'торговля',
    'services':      'сервисные услуги',
}


def _log(run_id: int, msg: str):
    ts    = datetime.now().strftime('%H:%M:%S')
    entry = f'[{ts}] {msg}'
    with _lock:
        if run_id in _runs:
            _runs[run_id]['log'].append(entry)
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


def _ollama_chat(client, messages: list, expect_json: bool = True) -> str:
    """Вызов Ollama через OpenAI-совместимый API."""
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


def _extract_companies(client, results_text: str, segment_label: str,
                       exclude_hint: str = '') -> list:
    exclude_clause = (
        f'Исключай компании из сфер: {exclude_hint}. ' if exclude_hint else ''
    )
    prompt = (
        'Ты помогаешь находить компании для аренды в промышленном технопарке класса A+ в Москве. '
        'Объект подходит для: производства, R&D, лабораторий, шоурума, light industrial. '
        'НЕ подходит: склады, ритейл, офисы без производства. '
        f'{exclude_clause}'
        'Из результатов поиска извлеки список реальных российских компаний. '
        'Верни ТОЛЬКО валидный JSON без лишнего текста: '
        '{"companies": [{"name": "...", "website": "...", "description": "..."}]}'
    )
    try:
        raw = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': f'Сегмент: {segment_label}\n\nРезультаты поиска:\n{results_text}'},
        ])
        # Qwen3 иногда добавляет <think>...</think> блок — убираем
        if '<think>' in raw:
            raw = raw[raw.rfind('</think>') + 8:].strip()
        data = json.loads(raw)
        return data.get('companies', [])
    except Exception:
        return []


def _extract_lpr(client, company: dict, results_text: str) -> dict | None:
    prompt = (
        'Ты ищешь контакты ЛПР (лица, принимающего решения) в компании. '
        'Приоритет ролей: Административный директор, Исполнительный директор, '
        'Заместитель генерального директора, HR-директор, Технический директор, '
        'Финансовый директор, Генеральный директор. '
        'ВАЖНО: извлекай ТОЛЬКО реальные данные из текста. Не придумывай. '
        'Верни ТОЛЬКО валидный JSON без лишнего текста: '
        '{"person_name": "ФИО или null", "title": "Должность или null", '
        '"email": "email или null", "phone": "телефон или null", "source_url": "URL или null"}'
    )
    try:
        raw = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': (
                f'Компания: {company.get("name")}\n'
                f'Сайт: {company.get("website")}\n\n'
                f'Найденная информация:\n{results_text}'
            )},
        ])
        if '<think>' in raw:
            raw = raw[raw.rfind('</think>') + 8:].strip()
        data = json.loads(raw)
        if data.get('email'):
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


def _check_ollama(client) -> bool:
    """Проверяет что Ollama доступна и модель загружена."""
    try:
        models = client.models.list()
        available = [m.id for m in models.data]
        return any(OLLAMA_MODEL in m for m in available)
    except Exception:
        return False


SCALE_SUFFIX = {
    'any':    '',
    'small':  'малый бизнес выручка до 800 млн',
    'medium': 'средний бизнес выручка 800 млн – 2 млрд',
    'large':  'крупный бизнес выручка от 2 млрд',
}


def _research_worker(run_id: int, config: dict):
    from openai import OpenAI
    from tavily import TavilyClient

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key='ollama')
    tavily = TavilyClient(api_key=TAVILY_API_KEY)

    # Поддержка нескольких сегментов
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
    active_only   = bool(config.get('active_only'))
    okved_type    = config.get('okved_type', 'main')

    # ОКВЭД и отрасль
    okved_include_raw = config.get('okved_include', '') or ''
    okved_exclude_raw = config.get('okved_exclude', '') or ''
    industries_raw    = config.get('industries', [])

    okved_include = [c.strip() for c in okved_include_raw.split(',') if c.strip()]
    okved_exclude = [c.strip() for c in okved_exclude_raw.split(',') if c.strip()]
    industries    = industries_raw if isinstance(industries_raw, list) else [industries_raw]

    # Строим доп. термины из ОКВЭД include
    okved_terms = ' '.join(
        OKVED_SEARCH_TERMS.get(c, '') for c in okved_include if c in OKVED_SEARCH_TERMS
    ).strip()
    # Строим доп. термины из отрасли
    industry_terms = ' '.join(
        INDUSTRY_SEARCH_TERMS.get(i, '') for i in industries if i in INDUSTRY_SEARCH_TERMS
    ).strip()
    # Строим термины для исключения (используем в промпте ИИ)
    okved_exclude_terms = ' '.join(
        OKVED_SEARCH_TERMS.get(c, '') for c in okved_exclude if c in OKVED_SEARCH_TERMS
    ).strip()

    region_label = REGION_SUFFIX.get(region_key, 'Москва')
    scale_suffix = SCALE_SUFFIX.get(company_scale, '')
    active_str   = 'активная компания' if active_only else ''

    seg_labels = [SEGMENT_LABELS.get(s, s) for s in segments_list]
    _log(run_id, f'🚀 Старт поиска: {", ".join(seg_labels)}')
    _log(run_id, f'   Регион: {region_label} | Цель: {target_count} | Масштаб: {company_scale or "любой"}')
    if okved_include:
        _log(run_id, f'   ОКВЭД включить: {", ".join(okved_include)} ({okved_type})')
    if okved_exclude:
        _log(run_id, f'   ОКВЭД исключить: {", ".join(okved_exclude)}')
    if industries:
        _log(run_id, f'   Отрасли: {", ".join(industries)}')
    _log(run_id, f'🤖 Модель: {OLLAMA_MODEL} (Ollama)')

    # Проверить Ollama
    if not _check_ollama(client):
        _log(run_id, f'❌ Ollama недоступна или модель {OLLAMA_MODEL} не загружена.')
        _log(run_id, 'Убедитесь что Ollama запущена: ollama serve')
        _log(run_id, f'И модель скачана: ollama pull {OLLAMA_MODEL}')
        with _lock:
            if run_id in _runs:
                _runs[run_id]['status'] = 'failed'
        conn = get_db()
        conn.execute(
            "UPDATE research_runs SET status='failed', completed_at=datetime('now') WHERE id=?",
            (run_id,)
        )
        conn.commit()
        conn.close()
        return

    if keywords:
        _log(run_id, f'🔑 Доп. слова: {keywords}')

    # Собираем запросы для всех выбранных сегментов
    all_queries = []
    for seg in segments_list:
        seg_queries = SEGMENT_QUERIES.get(seg, SEGMENT_QUERIES['electronics'])
        for q in seg_queries:
            full_q = ' '.join(filter(None, [
                q, region_label, scale_suffix, active_str,
                okved_terms, industry_terms, keywords
            ]))
            all_queries.append((full_q, SEGMENT_LABELS.get(seg, seg)))

    found_contacts = []
    searched_names: set = set()

    conn_main = get_db()
    existing_emails = {
        r['email'] for r in conn_main.execute('SELECT email FROM contacts').fetchall()
    }
    conn_main.close()

    for query, segment_label in all_queries:
        if len(found_contacts) >= target_count:
            break

        _log(run_id, f'🔍 [{segment_label}] {query}')
        try:
            search_res = tavily.search(query, max_results=8)
        except Exception as e:
            _log(run_id, f'❌ Ошибка поиска Tavily: {e}')
            continue

        results_text = _results_to_text(search_res)
        companies    = _extract_companies(
            client, results_text, segment_label,
            exclude_hint=okved_exclude_terms
        )
        _log(run_id, f'   Компаний в выдаче: {len(companies)}')

        for company in companies:
            if len(found_contacts) >= target_count:
                break

            name = (company.get('name') or '').strip()
            if not name or name in searched_names:
                continue
            searched_names.add(name)

            _log(run_id, f'🏢 Ищем контакты: {name}')

            contact_query = f'{name} контакты директор email телефон'
            try:
                contact_res = tavily.search(contact_query, max_results=5)
            except Exception as e:
                _log(run_id, f'   ⚠️ Ошибка поиска контактов: {e}')
                continue

            contact_text = _results_to_text(contact_res, 800)
            lpr          = _extract_lpr(client, company, contact_text)

            if not lpr:
                _log(run_id, f'   ⚠️  контакт не найден')
                continue

            email = lpr.get('email')
            phone = lpr.get('phone')

            # Применяем фильтры контактных данных
            if require_email and not email:
                _log(run_id, f'   ⏭  пропущен (нет email)')
                continue
            if require_phone and not phone:
                _log(run_id, f'   ⏭  пропущен (нет телефона)')
                continue
            if email and email in existing_emails:
                _log(run_id, f'   ⏭  {email} уже в базе')
                continue

            if email:
                existing_emails.add(email)
            lpr['segment'] = segment_label
            lpr['region']  = region_label
            found_contacts.append(lpr)
            _log(run_id, f'   ✅ {lpr.get("person_name", "???")}'
                         + (f' — {email}' if email else '')
                         + (f' | {phone}' if phone else ''))

            time.sleep(0.2)

    # Сохранить в БД
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

    _log(run_id, f'✅ Готово! Сохранено {saved} новых контактов из {target_count} запрошенных')
    with _lock:
        if run_id in _runs:
            _runs[run_id]['status']      = 'done'
            _runs[run_id]['found_count'] = saved


def start_research(config: dict) -> int:
    conn = get_db()
    cur  = conn.execute(
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
