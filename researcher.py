# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ВНИМАНИЕ ДЛЯ ИИ: перед любой правкой этого файла прочитай             ║
# ║  RESEARCH_RULES.md — там зафиксированы правила, которые нельзя менять  ║
# ║  без явного разрешения пользователя.                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝

import os
import re
import json
import time
import threading
from datetime import datetime
from database import get_db

TAVILY_API_KEY  = os.getenv('TAVILY_API_KEY', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'gemma3:4b')

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
_DASH   = r'[-–—]'   # дефис, en-dash U+2013, em-dash U+2014
_FIO_3  = r'([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)'   # Фамилия Имя Отчество
_FIO_IO = r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)'              # Фамилия И.О.

_DIRECTOR_PATTERNS = [
    # "Генеральный директор – Фамилия Имя Отчество" (любой разделитель)
    re.compile(rf'(?:Генеральный директор|Ген\.\s*директор|ГД).{{0,80}}{_DASH}\s*{_FIO_3}', re.IGNORECASE),
    # "Директор - Фамилия Имя Отчество"
    re.compile(rf'(?:Директор|Руководитель|Президент)\s*{_DASH}\s*{_FIO_3}'),
    # "Директор: Фамилия Имя Отчество"
    re.compile(rf'(?:Директор|Руководитель)\s*:\s*{_FIO_3}'),
    # "Генеральный директор: Фамилия Имя Отчество"
    re.compile(rf'(?:Генеральный директор|директор)[^.{{}}]{{0,40}}:\s*{_FIO_3}', re.IGNORECASE),
    # "Директор - Фамилия И.О."
    re.compile(rf'(?:Директор|Руководитель)\s*{_DASH}\s*{_FIO_IO}'),
    # "ГД Фамилия Имя Отчество"
    re.compile(rf'\bГД\s+{_FIO_3}'),
    # "директор Фамилия Имя Отчество" в середине текста
    re.compile(rf'директор\s+{_FIO_3}', re.IGNORECASE),
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


def _update_found_count(run_id: int, count: int):
    with _lock:
        if run_id in _runs:
            _runs[run_id]['found_count'] = count
    try:
        conn = get_db()
        conn.execute('UPDATE research_runs SET found_count=? WHERE id=?', (count, run_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Ollama ─────────────────────────────────────────────────────────────────

def _ollama_chat(client, messages: list, expect_json: bool = False) -> str:
    """
    Вызов Ollama. response_format НЕ используем — gemma3:4b/llama3.2 его
    игнорируют или возвращают пустой ответ. Вместо этого парсим JSON из
    сырого текста через _extract_json().
    """
    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=messages,
        temperature=0.1,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ''


def _strip_think(raw: str) -> str:
    if '<think>' in raw and '</think>' in raw:
        return raw[raw.rfind('</think>') + 8:].strip()
    return raw


def _extract_json(raw: str) -> str:
    """
    Надёжно извлекает JSON из ответа модели — работает с любым форматом:
    - Чистый JSON
    - JSON в ```json ... ``` блоке
    - JSON с думательным блоком <think>
    - JSON с пояснениями до/после
    """
    if not raw:
        return ''
    # 1. Убрать thinking блок
    raw = _strip_think(raw)
    # 2. Убрать markdown code block (```json ... ``` или ``` ... ```)
    md = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', raw)
    if md:
        return md.group(1).strip()
    # 3. Попробовать найти JSON-объект напрямую
    obj = re.search(r'\{[\s\S]*\}', raw)
    if obj:
        return obj.group(0)
    return raw.strip()


def _check_ollama(client) -> bool:
    try:
        models = client.models.list()
        return any(OLLAMA_MODEL in m.id for m in models.data)
    except Exception:
        return False


# ── AI-экстракторы ─────────────────────────────────────────────────────────

def _extract_companies(client, results_text: str, segment_label: str) -> list:
    prompt = (
        'Ты помогаешь находить компании для аренды в промышленном технопарке класса A+ в Москве. '
        'Подходят: производство, R&D, лаборатории, шоурум, light industrial. '
        'НЕ подходят: склады, чистый ритейл, офисы без производства. '
        'Из результатов поиска выдели реальные российские компании. '
        'Верни ТОЛЬКО JSON без пояснений: '
        '{"companies": [{"name": "название компании", "website": "url или null", "description": "краткое описание"}]}'
    )
    try:
        raw = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': f'Сегмент: {segment_label}\n\n{results_text}'},
        ], expect_json=False)
        clean = _extract_json(raw)
        if not clean:
            return []
        return json.loads(clean).get('companies', [])
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
        ], expect_json=False)
        data = json.loads(_extract_json(raw))
        # Чистим "null"-строки от модели
        for field in ('person_name', 'title', 'email', 'phone', 'source_url'):
            if str(data.get(field, '') or '').lower() in ('null', 'none', ''):
                data[field] = None

        email = (data.get('email') or '').lower().strip()
        if email and is_generic_email(email):
            data['email'] = None
            email = ''
        data['email'] = email or None

        # ФИО: директор из реестра если модель не нашла
        if known_director and not data.get('person_name'):
            data['person_name'] = known_director
            data['title']       = data.get('title') or 'Генеральный директор'

        # Email: regex-фолбэк если модель не нашла
        if not data.get('email'):
            regex_emails = extract_emails_from_text(combined_text)
            if regex_emails:
                data['email'] = regex_emails[0]

        # Телефон: regex-фолбэк если модель не нашла
        if not is_valid_phone(data.get('phone', '')):
            phones = re.findall(
                r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}',
                combined_text
            )
            if phones:
                data['phone'] = phones[0]

        # Возвращаем если есть хотя бы имя ЛПР
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


def is_valid_phone(phone: str) -> bool:
    """Телефон валиден если содержит минимум 7 цифр."""
    if not phone or str(phone).lower() in ('null', 'none', ''):
        return False
    digits = re.sub(r'\D', '', str(phone))
    return len(digits) >= 7


# ── Многопроходный поиск ЛПР ──────────────────────────────────────────────

def _multi_pass_lpr_search(tavily, company: dict, log_fn) -> tuple[str | None, str]:
    """
    4-проходный поиск полного комплекта ЛПР (ФИО + email + телефон):
    1. Rusprofile/Zachestnyibiznes → директор (regex из сниппета)
    2. Email по имени директора + компания
    3. Контакты с официального сайта (email + телефон)
    4. Телефон ЛПР — если не нашли на шаге 3

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
        r1 = tavily.search(q1, max_results=5)
        text1 = _results_to_text(r1, 700)
        combined_parts.append(text1)
        for item in r1.get('results', []):
            found = extract_director_name(item.get('content') or '')
            if found:
                director_name = found
                log_fn(f'   📋 Директор из реестра: {director_name}')
                break
    except Exception:
        pass
    time.sleep(0.2)

    # Проход 2: личный email директора
    if director_name:
        q2 = f'"{director_name}" "{name}" email'
        try:
            r2 = tavily.search(q2, max_results=4)
            text2 = _results_to_text(r2, 500)
            combined_parts.append(text2)
            for item in r2.get('results', []):
                emails = extract_emails_from_text(item.get('content', ''))
                if emails:
                    log_fn(f'   📧 Email в выдаче: {emails[0]}')
                    break
        except Exception:
            pass
        time.sleep(0.2)

    # Проход 3: контакты компании (email + телефон)
    q3 = (f'site:{domain} контакты email телефон' if domain
          else f'"{name}" контакты email телефон официальный')
    try:
        r3 = tavily.search(q3, max_results=4)
        text3 = _results_to_text(r3, 600)
        combined_parts.append(text3)
        # Быстрая проверка на телефон в сниппетах
        for item in r3.get('results', []):
            phones = re.findall(r'[\+7|8][\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', item.get('content', ''))
            if phones:
                log_fn(f'   📞 Телефон в выдаче: {phones[0]}')
                break
    except Exception:
        pass
    time.sleep(0.2)

    # Проход 4: отдельный поиск телефона директора (если нужно)
    if director_name:
        q4 = f'"{name}" телефон мобильный директор контакты'
        try:
            r4 = tavily.search(q4, max_results=3)
            combined_parts.append(_results_to_text(r4, 400))
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
    # ФИО + email + телефон всегда обязательны — это жёсткое требование, не настройка

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
                _log(run_id, '   ⚠️  ЛПР не определён, пропускаем')
                continue

            # ── Строгая валидация: нужны ФИО + email + телефон ──────────────
            person = (lpr.get('person_name') or '').strip()
            email  = (lpr.get('email') or '').lower().strip()
            phone  = (lpr.get('phone') or '').strip()

            # Чистим "null" строки от модели
            email = '' if email  in ('null', 'none') else email
            phone = '' if phone  in ('null', 'none') else phone
            person = '' if person in ('null', 'none') else person

            # ФИО: минимум 2 слова
            if not person or len(person.split()) < 2:
                _log(run_id, f'   ⛔  нет ФИО ЛПР — компания не засчитывается, ищем дальше')
                continue

            # Email: личный, не общий
            if not email or is_generic_email(email):
                _log(run_id, f'   ⛔  нет личного email — компания не засчитывается, ищем дальше')
                continue

            # Телефон: минимум 7 цифр
            if not is_valid_phone(phone):
                _log(run_id, f'   ⛔  нет телефона — компания не засчитывается, ищем дальше')
                continue

            # Email уже в базе
            if email in existing_emails:
                _log(run_id, f'   ⏭  {email} — уже в базе')
                continue

            if email:
                existing_emails.add(email)
            existing_companies.add(norm)

            lpr['segment'] = segment_label
            lpr['region']  = region_label
            lpr['email']   = email or None
            found_contacts.append(lpr)
            _update_found_count(run_id, len(found_contacts))

            # Сохраняем сразу — чтобы контакт был виден в UI до завершения запуска
            today_str = datetime.now().strftime('%Y-%m-%d')
            try:
                conn_now = get_db()
                conn_now.execute(
                    """INSERT OR IGNORE INTO contacts
                       (company_name, website, person_name, title, email, phone,
                        source_url, segment, region, date_found, status, run_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'new',?)""",
                    (lpr.get('company_name'), lpr.get('website'), lpr.get('person_name'),
                     lpr.get('title'), lpr.get('email') or None, lpr.get('phone') or None,
                     lpr.get('source_url'), lpr.get('segment'), lpr.get('region'),
                     today_str, run_id)
                )
                conn_now.commit()
                conn_now.close()
            except Exception as e:
                _log(run_id, f'⚠️ Ошибка записи: {e}')

            person = lpr.get('person_name') or director_name or '???'
            detail = ' | '.join(filter(None, [email, phone]))
            remaining = target_count - len(found_contacts)
            _log(run_id, f'   ✅ {person} — {detail} | найдено {len(found_contacts)}/{target_count}, осталось {remaining}')

            time.sleep(0.3)

    # Финальное обновление статуса
    conn  = get_db()
    saved = len(found_contacts)
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
        _runs[run_id] = {'status': 'running', 'log': [], 'found_count': 0,
                         'target_count': int(config.get('count', 10))}

    t = threading.Thread(target=_research_worker, args=(run_id, config), daemon=True)
    t.start()
    return run_id
