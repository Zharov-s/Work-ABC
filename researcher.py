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
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'qwen2.5:1.5b')

_runs: dict = {}
_lock = threading.Lock()
_pause_events: dict = {}  # run_id -> threading.Event  (set=идёт, clear=пауза)


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

INDUSTRY_LABELS = {
    'construction': 'Строительство',
    'transport':    'Транспорт',
    'media':        'Медиа',
    'it_telecom':   'ИТ и связь',
    'finance':      'Финансы',
    'healthcare':   'Здравоохранение',
    'education':    'Образование',
    'culture':      'Культура',
    'government':   'Госуправление',
    'associations': 'Объединения',
    'trade':        'Торговля',
    'services':     'Услуги',
    'production':   'Производство',
}

INDUSTRY_QUERY_TERMS = {
    'construction': ['строительные технологии', 'инженерные системы', 'производство строительных материалов'],
    'transport':    ['транспортное оборудование', 'логистические технологии', 'техника для транспорта'],
    'media':        ['медиаоборудование', 'производство контента оборудование', 'студийные технологии'],
    'it_telecom':   ['ИТ оборудование', 'телекоммуникационное оборудование', 'hardware'],
    'finance':      ['финтех оборудование', 'платежные терминалы', 'банковское оборудование'],
    'healthcare':   ['медицинское оборудование', 'диагностика', 'лабораторное оборудование'],
    'education':    ['образовательные технологии оборудование', 'учебные лаборатории', 'edtech hardware'],
    'culture':      ['музейное оборудование', 'выставочные технологии', 'культурные проекты производство'],
    'government':   ['госзаказ производство', 'импортозамещение', 'поставщик для государства'],
    'associations': ['отраслевое объединение производство', 'ассоциация производителей', 'кластер производителей'],
    'trade':        ['дистрибьютор с сервисным центром', 'шоурум и сервис', 'торговая компания производство'],
    'services':     ['сервисный центр оборудование', 'технический сервис', 'инжиниринговые услуги'],
    'production':   ['производственная компания', 'R&D производство', 'сборочное производство'],
}

SCALE_LABELS = {
    'any':    'Любой',
    'small':  'Малый',
    'medium': 'Средний',
    'large':  'Крупный',
}

SCALE_SUFFIX = {
    'any':    '',
    'small':  'малый бизнес',
    'medium': 'средний бизнес',
    'large':  'крупный бизнес',
}

CONTACT_REQUIREMENT_LABELS = {
    'company_name':    'Наименование компании',
    'website':         'Сайт',
    'generic_email':   'Email общий',
    'personal_email':  'Email личный',
    'generic_phone':   'Телефон общий',
    'mobile_phone':    'Телефон мобильный',
    'inn':             'ИНН',
}

DEFAULT_CONTACT_REQUIREMENTS = ['company_name', 'website', 'personal_email', 'mobile_phone']

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
_PHONE_RE = re.compile(r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}')
_INN_RE = re.compile(r'(?:ИНН|инн)?\s*[:№#-]?\s*\b(\d{10}|\d{12})\b')


# ── Вспомогательные функции ────────────────────────────────────────────────

def normalize_company_name(name: str) -> str:
    if not name:
        return ''
    s = _LEGAL_PREFIX.sub('', name)
    s = re.sub(r'["«»""„\'\`]', '', s)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


_VALID_EMAIL_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

def is_valid_email_format(email: str) -> bool:
    """Валидный email: ASCII-локальная часть, домен с точкой и TLD ≥2 символов."""
    return bool(email and _VALID_EMAIL_RE.match(email))


def is_generic_email(email: str) -> bool:
    if not email or '@' not in email:
        return True
    local = email.split('@')[0].lower()
    # Точное совпадение
    if local in BLOCKED_EMAIL_PREFIXES:
        return True
    # Префикс из списка + разделитель (info-site@, info123@, info_corp@, info.ru@)
    return any(
        local == p or local.startswith(p + '-') or local.startswith(p + '_')
        or local.startswith(p + '.') or (local.startswith(p) and local[len(p):len(p)+1].isdigit())
        for p in BLOCKED_EMAIL_PREFIXES
    )


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


def extract_all_emails_from_text(text: str) -> list[str]:
    found = _EMAIL_RE.findall(text)
    emails = []
    seen = set()
    for email in found:
        email = email.lower()
        if is_valid_email_format(email) and email not in seen:
            emails.append(email)
            seen.add(email)
    return emails


def extract_emails_from_text(text: str) -> list[str]:
    """Извлекает личные email-адреса из текста, фильтруя общие."""
    return [e for e in extract_all_emails_from_text(text) if not is_generic_email(e)]


def extract_generic_emails_from_text(text: str) -> list[str]:
    return [e for e in extract_all_emails_from_text(text) if is_generic_email(e)]


def extract_phones_from_text(text: str) -> list[str]:
    phones = []
    seen = set()
    for phone in _PHONE_RE.findall(text or ''):
        normalized = re.sub(r'\s+', ' ', phone).strip()
        key = re.sub(r'\D', '', normalized)
        if key and key not in seen:
            phones.append(normalized)
            seen.add(key)
    return phones


def is_mobile_phone(phone: str) -> bool:
    digits = re.sub(r'\D', '', str(phone or ''))
    return (
        len(digits) == 11 and (digits.startswith('79') or digits.startswith('89'))
    ) or (
        len(digits) == 10 and digits.startswith('9')
    )


def extract_inn_from_text(text: str) -> str | None:
    for m in _INN_RE.finditer(text or ''):
        return m.group(1)
    return None


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
    if status in ('done', 'failed'):
        _pause_events.pop(run_id, None)
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


def pause_research(run_id: int) -> bool:
    with _lock:
        if run_id not in _runs or _runs[run_id]['status'] != 'running':
            return False
        _runs[run_id]['status'] = 'paused'
    _pause_events.get(run_id, threading.Event()).clear()
    try:
        conn = get_db()
        conn.execute("UPDATE research_runs SET status='paused' WHERE id=?", (run_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    _log(run_id, '⏸ Поиск поставлен на паузу')
    return True


def resume_research(run_id: int) -> bool:
    with _lock:
        if run_id not in _runs or _runs[run_id]['status'] != 'paused':
            return False
        _runs[run_id]['status'] = 'running'
    try:
        conn = get_db()
        conn.execute("UPDATE research_runs SET status='running' WHERE id=?", (run_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    _pause_events.get(run_id, threading.Event()).set()
    _log(run_id, '▶ Поиск возобновлён')
    return True


# ── Ollama ─────────────────────────────────────────────────────────────────

def _ollama_chat(client, messages: list, expect_json: bool = False) -> str:
    kwargs = dict(model=OLLAMA_MODEL, messages=messages, temperature=0.1, max_tokens=400)
    if expect_json:
        kwargs['response_format'] = {'type': 'json_object'}
    resp = client.chat.completions.create(**kwargs)
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

def _extract_companies(client, results_text: str, segment_label: str, industry_label: str = '') -> list:
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
            {'role': 'user',   'content': (
                f'Сегмент: {segment_label}\n'
                f'Отрасль: {industry_label or "не задана"}\n\n'
                f'{results_text}'
            )},
        ], expect_json=True)
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
        'Разделяй личные и общие контакты. Личный email: имя.фамилия@, i.ivanov@ и т.п. '
        'Общий email: info@, sales@, office@, support@ и т.п. '
        'Мобильный телефон — номер конкретного человека, общий телефон — номер компании/офиса. '
        'Извлекай ТОЛЬКО то, что есть в тексте. Не придумывай. '
        'Верни ТОЛЬКО JSON: {"person_name": "ФИО или null", "title": "должность или null", '
        '"personal_email": "личный email или null", "generic_email": "общий email или null", '
        '"mobile_phone": "мобильный телефон или null", "generic_phone": "общий телефон или null", '
        '"inn": "ИНН или null", "source_url": "URL или null"}'
    )
    try:
        raw  = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': (
                f'Компания: {company.get("name")}\n'
                f'Сайт: {company.get("website") or "неизвестен"}\n\n'
                f'Собранная информация:\n{combined_text}'
            )},
        ], expect_json=True)
        data = json.loads(_extract_json(raw))
        # Чистим "null"-строки от модели
        for field in (
            'person_name', 'title', 'email', 'phone', 'personal_email', 'generic_email',
            'mobile_phone', 'generic_phone', 'inn', 'source_url'
        ):
            if str(data.get(field, '') or '').lower() in ('null', 'none', ''):
                data[field] = None

        personal_email = (data.get('personal_email') or data.get('email') or '').lower().strip()
        generic_email = (data.get('generic_email') or '').lower().strip()
        if personal_email and (not is_valid_email_format(personal_email) or is_generic_email(personal_email)):
            if is_valid_email_format(personal_email) and is_generic_email(personal_email) and not generic_email:
                generic_email = personal_email
            personal_email = ''
        if generic_email and not is_valid_email_format(generic_email):
            generic_email = ''
        if generic_email and not is_generic_email(generic_email):
            if not personal_email:
                personal_email = generic_email
            generic_email = ''
        data['personal_email'] = personal_email or None
        data['generic_email'] = generic_email or None

        # ФИО: директор из реестра если модель не нашла
        if known_director and not data.get('person_name'):
            data['person_name'] = known_director
            data['title']       = data.get('title') or 'Генеральный директор'

        # Email: regex-фолбэк если модель не нашла
        if not data.get('personal_email'):
            regex_emails = extract_emails_from_text(combined_text)
            if regex_emails:
                data['personal_email'] = regex_emails[0]
        if not data.get('generic_email'):
            generic_emails = extract_generic_emails_from_text(combined_text)
            if generic_emails:
                data['generic_email'] = generic_emails[0]

        # Телефон: regex-фолбэк если модель не нашла
        phone = data.get('phone')
        mobile_phone = data.get('mobile_phone')
        generic_phone = data.get('generic_phone')
        if phone and not mobile_phone and is_mobile_phone(phone):
            mobile_phone = phone
        elif phone and not generic_phone:
            generic_phone = phone
        phones = extract_phones_from_text(combined_text)
        if not is_valid_phone(mobile_phone):
            mobile_phone = next((p for p in phones if is_mobile_phone(p)), None)
        if not is_valid_phone(generic_phone):
            generic_phone = next((p for p in phones if not is_mobile_phone(p)), None) or (phones[0] if phones else None)
        data['mobile_phone'] = mobile_phone if is_valid_phone(mobile_phone) else None
        data['generic_phone'] = generic_phone if is_valid_phone(generic_phone) else None

        inn = re.sub(r'\D', '', str(data.get('inn') or ''))
        if len(inn) not in (10, 12):
            inn = extract_inn_from_text(combined_text) or ''
        data['inn'] = inn or None

        data['email'] = data.get('personal_email') or data.get('generic_email')
        data['phone'] = data.get('mobile_phone') or data.get('generic_phone')

        # Возвращаем если есть хотя бы имя ЛПР
        if data.get('person_name') or data.get('email') or data.get('phone') or data.get('inn'):
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

def _multi_pass_lpr_search(tavily, company: dict, log_fn, requirements: set[str] | None = None) -> tuple[str | None, str]:
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
    found_email    = None
    found_phone    = None

    def _quick_scan(text: str):
        nonlocal found_email, found_phone
        if not found_email:
            emails = extract_emails_from_text(text)
            if emails:
                found_email = emails[0]
        if not found_phone:
            phones = extract_phones_from_text(text)
            if phones:
                found_phone = phones[0]

    # Проход 1: директор из российских реестров
    q1 = f'"{name}" генеральный директор'
    try:
        r1 = tavily.search(q1, max_results=5)
        text1 = _results_to_text(r1, 700)
        combined_parts.append(text1)
        _quick_scan(text1)
        for item in r1.get('results', []):
            found = extract_director_name(item.get('content') or '')
            if found:
                director_name = found
                log_fn(f'   📋 Директор из реестра: {director_name}')
                break
    except Exception:
        pass

    # Проход 2: личный email директора (только если ещё нет email)
    if director_name and not found_email:
        q2 = f'"{director_name}" "{name}" email'
        try:
            r2 = tavily.search(q2, max_results=4)
            text2 = _results_to_text(r2, 500)
            combined_parts.append(text2)
            _quick_scan(text2)
            if found_email:
                log_fn(f'   📧 Email в выдаче: {found_email}')
        except Exception:
            pass

    # Проход 3: контакты компании (нужен если нет email или телефона)
    if not (found_email and found_phone):
        q3 = (f'site:{domain} контакты email телефон' if domain
              else f'"{name}" контакты email телефон официальный')
        try:
            r3 = tavily.search(q3, max_results=4)
            text3 = _results_to_text(r3, 600)
            combined_parts.append(text3)
            _quick_scan(text3)
            if found_phone:
                log_fn(f'   📞 Телефон в выдаче: {found_phone}')
        except Exception:
            pass

    # Проход 4: телефон директора (только если до сих пор нет телефона)
    if director_name and not found_phone:
        q4 = f'"{name}" телефон мобильный директор контакты'
        try:
            r4 = tavily.search(q4, max_results=3)
            combined_parts.append(_results_to_text(r4, 400))
        except Exception:
            pass

    requirements = requirements or set()
    if 'inn' in requirements:
        q5 = f'"{name}" ИНН реквизиты'
        try:
            r5 = tavily.search(q5, max_results=3)
            combined_parts.append(_results_to_text(r5, 500))
        except Exception:
            pass

    if 'generic_email' in requirements or 'generic_phone' in requirements:
        q6 = (f'site:{domain} реквизиты контакты email телефон' if domain
              else f'"{name}" реквизиты контакты email телефон')
        try:
            r6 = tavily.search(q6, max_results=3)
            combined_parts.append(_results_to_text(r6, 500))
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

    raw_regions = config.get('regions', config.get('region', 'moscow'))
    if isinstance(raw_regions, str):
        raw_regions = [raw_regions]
    regions_list = [r for r in raw_regions if r in REGION_SUFFIX] or ['moscow']

    raw_scales = config.get('company_scales', config.get('company_scale', 'any'))
    if isinstance(raw_scales, str):
        raw_scales = [raw_scales]
    scales_list = [s for s in raw_scales if s in SCALE_SUFFIX] or ['any']
    if len(scales_list) > 1 and 'any' in scales_list:
        scales_list = [s for s in scales_list if s != 'any']

    raw_industries = config.get('industries', [])
    if isinstance(raw_industries, str):
        raw_industries = [raw_industries]
    industries_list = [i for i in raw_industries if i in INDUSTRY_LABELS]

    raw_requirements = config.get('contact_requirements', DEFAULT_CONTACT_REQUIREMENTS)
    if isinstance(raw_requirements, str):
        raw_requirements = [raw_requirements]
    requirements = {r for r in raw_requirements if r in CONTACT_REQUIREMENT_LABELS} or set(DEFAULT_CONTACT_REQUIREMENTS)

    target_count = int(config.get('count', 10))
    keywords     = config.get('keywords', '').strip()

    seg_labels = [SEGMENT_LABELS.get(s, s) for s in segments_list]
    region_labels = [REGION_SUFFIX.get(r, r) for r in regions_list]
    scale_labels = [SCALE_LABELS.get(s, s) for s in scales_list]
    industry_labels = [INDUSTRY_LABELS.get(i, i) for i in industries_list]
    requirement_labels = [CONTACT_REQUIREMENT_LABELS.get(r, r) for r in requirements]
    _log(run_id, f'🚀 Старт: {", ".join(seg_labels)} | {", ".join(region_labels)} | цель={target_count}')
    _log(run_id, f'🏷 Отрасли: {", ".join(industry_labels) if industry_labels else "все подходящие"}')
    _log(run_id, f'📏 Масштаб: {", ".join(scale_labels)}')
    _log(run_id, f'📌 Обязательные поля: {", ".join(requirement_labels)}')
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
        segment_label = SEGMENT_LABELS.get(seg, seg)
        industry_keys = industries_list or [None]
        for region_key in regions_list:
            region_label = REGION_SUFFIX.get(region_key, 'Москва')
            for scale_key in scales_list:
                scale_suffix = SCALE_SUFFIX.get(scale_key, '')
                for industry_key in industry_keys:
                    industry_label = INDUSTRY_LABELS.get(industry_key, '') if industry_key else ''
                    industry_terms = INDUSTRY_QUERY_TERMS.get(industry_key, ['']) if industry_key else ['']
                    industry_suffix = ' '.join(industry_terms[:2])
                    requirement_terms = []
                    if 'website' in requirements:
                        requirement_terms.append('официальный сайт')
                    if 'inn' in requirements:
                        requirement_terms.append('ИНН реквизиты')
                    if 'personal_email' in requirements:
                        requirement_terms.append('личный email руководитель')
                    if 'generic_email' in requirements:
                        requirement_terms.append('общий email контакты')
                    if 'mobile_phone' in requirements:
                        requirement_terms.append('мобильный телефон руководитель')
                    if 'generic_phone' in requirements:
                        requirement_terms.append('городской телефон контакты')
                    requirement_suffix = ' '.join(requirement_terms)
                    for q in SEGMENT_QUERIES.get(seg, []):
                        full_q = ' '.join(filter(None, [q, industry_suffix, requirement_suffix, region_label, scale_suffix, keywords]))
                        all_queries.append((full_q, segment_label, industry_label, region_label, 'tavily'))
                    # Дополнительные каналы: технопарки, выставки, импортозамещение
                    for q in EXTRA_DISCOVERY_QUERIES.get(seg, []):
                        full_q = ' '.join(filter(None, [q, industry_suffix, requirement_suffix, region_label, scale_suffix, keywords]))
                        all_queries.append((full_q, segment_label, industry_label, region_label, 'extra'))

    found_contacts = []
    searched_names = set()

    for query, segment_label, industry_label, region_label, source_tag in all_queries:
        _pause_events[run_id].wait()  # блокируется, пока стоит на паузе
        if len(found_contacts) >= target_count:
            break

        icon = '🔍' if source_tag == 'tavily' else '🏭'
        filter_label = f'{segment_label}' + (f' / {industry_label}' if industry_label else '')
        _log(run_id, f'{icon} [{filter_label}] {query}')

        try:
            search_res = tavily.search(query, max_results=7)
        except Exception as e:
            _log(run_id, f'❌ Tavily: {e}')
            continue

        companies = _extract_companies(client, _results_to_text(search_res), segment_label, industry_label)
        _log(run_id, f'   Компаний в выдаче: {len(companies)}')

        for company in companies:
            _pause_events[run_id].wait()  # пауза между компаниями
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
                tavily, company, lambda m: _log(run_id, m), requirements
            )

            if not combined_text.strip():
                _log(run_id, '   ⚠️  Ничего не найдено по контактам')
                continue

            lpr = _extract_lpr_from_combined(client, company, combined_text, director_name)

            if not lpr:
                if requirements.issubset({'company_name', 'website'}):
                    lpr = {
                        'company_name': company.get('name', ''),
                        'website': company.get('website', ''),
                    }
                else:
                    _log(run_id, '   ⚠️  ЛПР/контакты не определены, пропускаем')
                    continue

            # ── Гибкая валидация по выбранным требованиям ───────────────────
            person = (lpr.get('person_name') or '').strip()
            personal_email = (lpr.get('personal_email') or '').lower().strip()
            generic_email = (lpr.get('generic_email') or '').lower().strip()
            mobile_phone = (lpr.get('mobile_phone') or '').strip()
            generic_phone = (lpr.get('generic_phone') or '').strip()
            inn = (lpr.get('inn') or '').strip()
            website = (lpr.get('website') or company.get('website') or '').strip()

            # Чистим "null" строки от модели
            personal_email = '' if personal_email in ('null', 'none') else personal_email
            generic_email = '' if generic_email in ('null', 'none') else generic_email
            mobile_phone = '' if mobile_phone in ('null', 'none') else mobile_phone
            generic_phone = '' if generic_phone in ('null', 'none') else generic_phone
            inn = '' if inn in ('null', 'none') else inn
            person = '' if person in ('null', 'none') else person

            if 'company_name' in requirements and not name:
                _log(run_id, '   ⛔  нет наименования компании — компания не засчитывается')
                continue

            if 'website' in requirements and not website:
                _log(run_id, '   ⛔  нет сайта — компания не засчитывается')
                continue

            if requirements.intersection({'personal_email', 'mobile_phone'}) and (not person or len(person.split()) < 2):
                _log(run_id, f'   ⛔  нет ФИО ЛПР для личного контакта — компания не засчитывается, ищем дальше')
                continue

            if 'personal_email' in requirements and (
                not personal_email or not is_valid_email_format(personal_email) or is_generic_email(personal_email)
            ):
                _log(run_id, f'   ⛔  нет личного email — компания не засчитывается, ищем дальше')
                continue

            if 'generic_email' in requirements and (
                not generic_email or not is_valid_email_format(generic_email) or not is_generic_email(generic_email)
            ):
                _log(run_id, f'   ⛔  нет общего email — компания не засчитывается, ищем дальше')
                continue

            if 'mobile_phone' in requirements and (not is_valid_phone(mobile_phone) or not is_mobile_phone(mobile_phone)):
                _log(run_id, f'   ⛔  нет мобильного телефона — компания не засчитывается, ищем дальше')
                continue

            if 'generic_phone' in requirements and not is_valid_phone(generic_phone):
                _log(run_id, f'   ⛔  нет общего телефона — компания не засчитывается, ищем дальше')
                continue

            if 'inn' in requirements and not inn:
                _log(run_id, f'   ⛔  нет ИНН — компания не засчитывается, ищем дальше')
                continue

            primary_email = personal_email or generic_email or None
            primary_phone = mobile_phone or generic_phone or None

            # Email уже в базе
            if primary_email and primary_email in existing_emails:
                _log(run_id, f'   ⏭  {primary_email} — уже в базе')
                continue

            if primary_email:
                existing_emails.add(primary_email)
            existing_companies.add(norm)

            lpr['segment'] = segment_label
            lpr['region']  = region_label
            lpr['website'] = website or None
            lpr['email'] = primary_email
            lpr['phone'] = primary_phone
            lpr['personal_email'] = personal_email or None
            lpr['generic_email'] = generic_email or None
            lpr['mobile_phone'] = mobile_phone or None
            lpr['generic_phone'] = generic_phone or None
            lpr['inn'] = inn or None
            found_contacts.append(lpr)
            _update_found_count(run_id, len(found_contacts))

            # Сохраняем сразу — чтобы контакт был виден в UI до завершения запуска
            today_str = datetime.now().strftime('%Y-%m-%d')
            try:
                conn_now = get_db()
                conn_now.execute(
                    """INSERT OR IGNORE INTO contacts
                       (company_name, website, person_name, title, email, personal_email, generic_email,
                        phone, mobile_phone, generic_phone, inn, source_url, segment, region,
                        date_found, status, run_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?)""",
                    (lpr.get('company_name'), lpr.get('website'), lpr.get('person_name'),
                     lpr.get('title'), lpr.get('email') or None, lpr.get('personal_email') or None,
                     lpr.get('generic_email') or None, lpr.get('phone') or None,
                     lpr.get('mobile_phone') or None, lpr.get('generic_phone') or None,
                     lpr.get('inn') or None, lpr.get('source_url'), lpr.get('segment'), lpr.get('region'),
                     today_str, run_id)
                )
                conn_now.commit()
                conn_now.close()
            except Exception as e:
                _log(run_id, f'⚠️ Ошибка записи: {e}')

            person = lpr.get('person_name') or director_name or '???'
            detail = ' | '.join(filter(None, [primary_email, primary_phone, f'ИНН {inn}' if inn else '']))
            remaining = target_count - len(found_contacts)
            _log(run_id, f'   ✅ {person} — {detail} | найдено {len(found_contacts)}/{target_count}, осталось {remaining}')

            time.sleep(0.1)

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
    main_query_count = sum(1 for *_, source_tag in all_queries if source_tag == 'tavily')
    extra_query_count = sum(1 for *_, source_tag in all_queries if source_tag == 'extra')
    _log(run_id, f'   Запросов выполнено: {len(all_queries)} ({main_query_count} основных + {extra_query_count} дополнительных)')

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

    ev = threading.Event()
    ev.set()
    _pause_events[run_id] = ev

    t = threading.Thread(target=_research_worker, args=(run_id, config), daemon=True)
    t.start()
    return run_id
