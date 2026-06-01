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
from urllib.parse import urlparse
from database import get_db

TAVILY_API_KEY  = os.getenv('TAVILY_API_KEY', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'qwen2.5:1.5b')

_runs: dict = {}
_lock = threading.Lock()
_pause_events: dict = {}  # run_id -> threading.Event  (set=идёт, clear=пауза)
_finish_events: dict = {}  # run_id -> threading.Event (set=завершить после текущего шага)


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

# Максимум строк в БД на одну компанию при multi-email поиске.
# Если выбраны оба типа email (личный + общий) — сохраняется по строке на каждый тип.
# При выборе только одного типа — одна строка. Ограничение: не более MAX_EMAILS_PER_COMPANY строк.
MAX_EMAILS_PER_COMPANY = 5

BLOCKED_WEBSITE_DOMAINS = {
    'rusprofile.ru', 'www.rusprofile.ru',
    'zachestnyibiznes.ru', 'www.zachestnyibiznes.ru',
    'checko.ru', 'www.checko.ru',
    'list-org.com', 'www.list-org.com',
    'sbis.ru', 'www.sbis.ru',
    'audit-it.ru', 'www.audit-it.ru',
    'spark-interfax.ru', 'www.spark-interfax.ru',
    'kartoteka.ru', 'www.kartoteka.ru',
    'nalog.ru', 'egrul.nalog.ru', 'www.nalog.ru',
    '4pda.to', '4pda.ru', 'www.4pda.to', 'www.4pda.ru',
    'forumhouse.ru', 'www.forumhouse.ru',
    'hh.ru', 'www.hh.ru',
    'habr.com', 'www.habr.com',
    'vc.ru', 'www.vc.ru',
    't.me', 'telegram.me', 'vk.com', 'www.vk.com',
    'facebook.com', 'www.facebook.com',
    'linkedin.com', 'www.linkedin.com',
    'youtube.com', 'www.youtube.com',
    'instagram.com', 'www.instagram.com',
    'avito.ru', 'www.avito.ru',
    'tiu.ru', 'www.tiu.ru',
    'pulscen.ru', 'www.pulscen.ru',
    'all.biz', 'www.all.biz',
    'promportal.su', 'www.promportal.su',
    'wikipedia.org', 'ru.wikipedia.org',
    '2gis.ru', 'www.2gis.ru',
    'maps.google.com', 'google.com', 'www.google.com',
    'yandex.ru', 'www.yandex.ru', 'yandex.com', 'www.yandex.com',
}

BLOCKED_WEBSITE_DOMAIN_SUFFIXES = (
    '.rusprofile.ru',
    '.zachestnyibiznes.ru',
    '.checko.ru',
    '.sbis.ru',
    '.nalog.ru',
    '.wikipedia.org',
)


def _url_domain(url: str) -> str:
    raw = (url or '').strip()
    if not raw:
        return ''
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', raw):
        raw = 'https://' + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return ''
    return (parsed.netloc or '').split('@')[-1].split(':')[0].lower()


def normalize_official_website(url: str) -> str | None:
    raw = (url or '').strip()
    if not raw or raw.lower() in ('null', 'none'):
        return None
    if raw.startswith(('mailto:', 'tel:', '#')):
        return None
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', raw):
        raw = 'https://' + raw
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    domain = _url_domain(raw)
    if not domain or domain in BLOCKED_WEBSITE_DOMAINS:
        return None
    if any(domain.endswith(suffix) for suffix in BLOCKED_WEBSITE_DOMAIN_SUFFIXES):
        return None
    if '.' not in domain:
        return None
    return f'{parsed.scheme}://{parsed.netloc.lower()}'


def is_official_website_url(url: str) -> bool:
    return normalize_official_website(url) is not None


def normalize_contact_requirements(raw_requirements) -> list[str]:
    if isinstance(raw_requirements, str):
        raw_requirements = [raw_requirements]
    if not raw_requirements:
        raw_requirements = DEFAULT_CONTACT_REQUIREMENTS
    seen = set()
    normalized = []
    for req in raw_requirements:
        if req in CONTACT_REQUIREMENT_LABELS and req not in seen:
            normalized.append(req)
            seen.add(req)
    return normalized or list(DEFAULT_CONTACT_REQUIREMENTS)


def contact_satisfies_requirements(contact: dict, requirements) -> tuple[bool, str]:
    reqs = set(normalize_contact_requirements(requirements))

    company_name = (contact.get('company_name') or '').strip()
    website = (contact.get('website') or '').strip()
    person = (contact.get('person_name') or '').strip()
    # Намеренно НЕ используем fallback на 'email': личный и общий должны лежать
    # в своих полях. Fallback мог бы дать generic при проверке personal_email.
    personal_email = (contact.get('personal_email') or '').lower().strip()
    generic_email  = (contact.get('generic_email') or '').lower().strip()
    mobile_phone = (contact.get('mobile_phone') or '').strip()
    generic_phone = (contact.get('generic_phone') or '').strip()
    inn = re.sub(r'\D', '', str(contact.get('inn') or ''))

    if 'company_name' in reqs and not company_name:
        return False, 'нет наименования компании'
    if 'website' in reqs and not is_official_website_url(website):
        return False, 'нет официального сайта'
    if reqs.intersection({'personal_email', 'mobile_phone'}) and (not person or len(person.split()) < 2):
        return False, 'нет ФИО ЛПР для личного контакта'
    if 'personal_email' in reqs and (
        not personal_email or not is_valid_email_format(personal_email) or is_generic_email(personal_email)
    ):
        return False, 'нет личного email'
    if 'generic_email' in reqs and (
        not generic_email or not is_valid_email_format(generic_email) or not is_generic_email(generic_email)
    ):
        return False, 'нет общего email'
    if 'mobile_phone' in reqs and (not is_valid_phone(mobile_phone) or not is_mobile_phone(mobile_phone)):
        return False, 'нет мобильного телефона'
    if 'generic_phone' in reqs and (
        not is_valid_phone(generic_phone) or is_mobile_phone(generic_phone)
    ):
        return False, 'нет общего телефона'
    if 'inn' in reqs and len(inn) not in (10, 12):
        return False, 'нет ИНН'
    return True, ''


def project_contact_to_requirements(contact: dict, requirements) -> dict:
    """Return only the fields the user selected for the research result."""
    reqs = set(normalize_contact_requirements(requirements))
    projected = dict(contact)

    if 'website' not in reqs:
        projected['website'] = None
    if 'personal_email' not in reqs:
        projected['personal_email'] = None
    if 'generic_email' not in reqs:
        projected['generic_email'] = None
    if 'mobile_phone' not in reqs:
        projected['mobile_phone'] = None
    if 'generic_phone' not in reqs:
        projected['generic_phone'] = None
    if 'inn' not in reqs:
        projected['inn'] = None

    projected['email'] = projected.get('personal_email') or projected.get('generic_email') or None
    projected['phone'] = projected.get('mobile_phone') or projected.get('generic_phone') or None
    return projected

def _build_contact_rows_for_save(
    lpr: dict,
    requirements_list: list,
) -> list[tuple[str | None, dict]]:
    """
    Из одного LPR-словаря строит список (email_key, contact_row) для INSERT в БД.

    Правила:
    • Выбраны personal_email И generic_email →
        создаём ДВЕ строки (по одной на каждый тип).
        Если хотя бы один из них не найден — возвращаем [] (компания пропускается).
    • Выбран только personal_email →
        одна строка с личным email; если не найден — [].
    • Выбран только generic_email →
        одна строка с общим email; если не найден — [].
    • Email не требуется →
        одна строка, email = лучший из найденных.

    Не более MAX_EMAILS_PER_COMPANY строк на компанию.
    Каждая строка имеет поле 'email' равное её основному адресу.
    """
    reqs = set(normalize_contact_requirements(requirements_list))

    personal = (lpr.get('personal_email') or '').lower().strip()
    generic  = (lpr.get('generic_email')  or '').lower().strip()

    want_personal = 'personal_email' in reqs
    want_generic  = 'generic_email'  in reqs

    rows: list[tuple[str | None, dict]] = []

    if want_personal and want_generic:
        # Оба типа нужны — оба обязаны присутствовать
        if not personal or not generic:
            return []          # не можем выполнить требование → пропустить компанию

        base = project_contact_to_requirements(lpr, requirements_list)

        # Строка 1: личный email
        r1 = dict(base)
        r1['email']          = personal
        r1['personal_email'] = personal
        r1['generic_email']  = None   # эта строка посвящена личному email
        r1['phone'] = r1.get('mobile_phone') or r1.get('generic_phone')
        rows.append((personal, r1))

        # Строка 2: общий email
        r2 = dict(base)
        r2['email']          = generic
        r2['personal_email'] = None   # эта строка посвящена общему email
        r2['generic_email']  = generic
        r2['phone'] = r2.get('mobile_phone') or r2.get('generic_phone')
        rows.append((generic, r2))

    elif want_personal:
        if not personal:
            return []
        projected = project_contact_to_requirements(lpr, requirements_list)
        projected['email'] = personal
        projected['phone'] = projected.get('mobile_phone') or projected.get('generic_phone')
        rows.append((personal, projected))

    elif want_generic:
        if not generic:
            return []
        projected = project_contact_to_requirements(lpr, requirements_list)
        projected['email'] = generic
        projected['phone'] = projected.get('mobile_phone') or projected.get('generic_phone')
        rows.append((generic, projected))

    else:
        # Email-требований нет — одна строка, лучший из найденных
        projected = project_contact_to_requirements(lpr, requirements_list)
        best_email = projected.get('personal_email') or projected.get('generic_email') or None
        projected['email'] = best_email
        projected['phone'] = projected.get('mobile_phone') or projected.get('generic_phone')
        rows.append((best_email, projected))

    return rows[:MAX_EMAILS_PER_COMPANY]


# ── Поисковые запросы ───────────────────────────────────────────────────────

# Основные запросы через Tavily (широкий поиск)
SEGMENT_QUERIES = {
    'electronics': [
        'производство электроники приборостроение компания Москва руководитель',
        'электронные компоненты датчики контроллеры производитель Москва офис',
        'разработка производство электроника Москва контакты директор',
        # 2ГИС: компании появляются в Tavily с телефонами и адресами
        'производство электронных приборов датчиков Москва 2гис телефон',
        'электроника приборостроение компания Москва 2гис сайт контакты',
    ],
    'medtech': [
        'медицинское оборудование производство компания Москва контакты',
        'медтех диагностика лабораторное оборудование производитель Москва',
        'фармацевтика биотехнологии пилотное производство Москва компания',
        'медицинское оборудование Москва 2гис телефон производитель',
        'медтех биотехнологии Москва компания сайт руководитель',
    ],
    'robotics': [
        'робототехника промышленная автоматизация производство Москва компания',
        'беспилотные системы дроны производитель Москва офис',
        'мехатроника приводы сервосистемы разработка Москва',
        'промышленная автоматизация роботы Москва 2гис телефон компания',
        'станки ЧПУ мехатроника производство Москва 2гис руководитель',
    ],
    'it_hardware': [
        'производство серверов телекоммуникационное оборудование Москва',
        'отечественное ИТ hardware производство офис Москва',
        'вычислительная техника сетевое оборудование производитель Москва',
        'производство серверов коммутаторов Москва 2гис телефон офис',
        'российский ИТ производитель hardware Москва компания директор',
    ],
    'laser_optics': [
        'лазерные системы оптические приборы производство Москва',
        'фотоника волоконная оптика производитель Москва',
        'лазерные технологии производство научное оборудование Москва',
        'лазеры оптика Москва 2гис компания телефон',
        'оптические приборы фотоника Москва производитель директор',
    ],
    'light_industrial': [
        'лёгкое производство R&D шоурум технопарк Москва компания',
        'производственная компания класс А технопарк Москва',
        'сборочное производство инжиниринг сервисный центр Москва',
        'производство Москва промышленный парк аренда 2гис компания',
        'сборочное производство инжиниринговый центр Москва 2гис',
    ],
}

# Дополнительные каналы: технопарки, выставки, импортозамещение
EXTRA_DISCOVERY_QUERIES = {
    'electronics': [
        'резиденты ОЭЗ технопарк Москва производство электроника 2024 2025',
        'ExpoElectronica 2025 экспоненты участники производитель Москва',
        'импортозамещение электроника производство Москва компания контракт',
        'кластер электроники Зеленоград ОЭЗ резиденты компании',
        # 2ГИС: категории справочника индексируются в поиске
        'site:2gis.ru производство электронного оборудования Москва',
        # checko.ru/list-org — ЕГРЮЛ-прокси с данными о директорах
        'checko.ru электроника приборостроение Москва компания руководитель ИНН',
        'list-org.com производство электронных компонентов Москва директор',
    ],
    'medtech': [
        'резиденты технопарка Москва медицинское оборудование производство',
        'Pharmtech 2024 2025 экспоненты Москва производитель медтех',
        'импортозамещение медицинские изделия производство Москва компания',
        'московский медицинский кластер резидент производитель',
        'site:2gis.ru медицинское оборудование производство Москва',
        'checko.ru медтех производство медицинские изделия Москва руководитель',
        'list-org.com биотехнологии медоборудование Москва компания директор',
    ],
    'robotics': [
        'технопарк Москва робототехника автоматизация резидент компания',
        'ИННОПРОМ 2024 2025 промышленная автоматизация Москва экспонент',
        'импортозамещение промышленные роботы производство Москва',
        'ОЭЗ Москва мехатроника приводы производство резидент',
        'site:2gis.ru промышленная автоматизация робототехника Москва',
        'checko.ru станки ЧПУ робототехника автоматизация Москва директор ИНН',
        'list-org.com мехатроника сервоприводы производство Москва руководитель',
    ],
    'it_hardware': [
        'резиденты технопарка Москва производство ИТ оборудование серверы',
        'российские производители серверов коммутаторов Москва 2024 2025',
        'импортозамещение ИТ инфраструктура серверы производство Москва компания',
        'Rusnanotech ОЭЗ Москва ИТ оборудование резидент',
        'site:2gis.ru производство вычислительной техники серверов Москва',
        'checko.ru производство телекоммуникационного оборудования Москва директор',
        'list-org.com ИТ hardware серверы коммутаторы Москва производитель',
    ],
    'laser_optics': [
        'технопарк Москва лазерные оптические системы производство резидент',
        'Фотоника 2024 2025 Москва участники производитель лазеры',
        'импортозамещение лазеры оптика производство Москва компания',
        'site:2gis.ru лазерные оптические технологии производство Москва',
        'checko.ru лазерные системы оптические приборы Москва директор ИНН',
    ],
    'light_industrial': [
        'резиденты промышленного технопарка Москва лёгкое производство R&D',
        'технопарк Москва производство шоурум офис аренда класс А',
        'московские производственные компании технопарк сборка инжиниринг',
        'резиденты технополис Москва производство 2024',
        'site:2gis.ru производство инжиниринг сборка Москва компания',
        'checko.ru промышленное производство сборка Москва ИНН директор',
        'list-org.com лёгкое производство R&D Москва компания руководитель',
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
    # ── Базовые паттерны ────────────────────────────────────────────────────
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

    # ── checko.ru / list-org.com (ЕГРЮЛ-прокси сайты) ──────────────────────
    # "Руководитель: Фамилия Имя Отчество" (checko.ru формат)
    re.compile(rf'Руководитель\s*:\s*{_FIO_3}', re.IGNORECASE),
    # "Руководитель — Фамилия И.О." (checko.ru сокращённый)
    re.compile(rf'Руководитель\s*{_DASH}\s*{_FIO_IO}'),
    # "Единоличный исполнительный орган: Фамилия Имя Отчество" (ЕГРЮЛ-термин)
    re.compile(rf'(?:Единоличный\s+исполнительный\s+орган|ЕИО)\s*[:{_DASH}]\s*{_FIO_3}', re.IGNORECASE),
    # "ФИО: Фамилия Имя Отчество" (list-org.com формат)
    re.compile(rf'\bФИО\s*:\s*{_FIO_3}', re.IGNORECASE),
    # "Исполнительный директор – Фамилия Имя Отчество"
    re.compile(rf'(?:Исполнительный директор|Коммерческий директор|Технический директор)\s*{_DASH}\s*{_FIO_3}', re.IGNORECASE),
    # "Фамилия Имя Отчество — Директор/Руководитель" (обратный порядок)
    re.compile(rf'{_FIO_3}\s*{_DASH}\s*(?:Директор|Руководитель|Генеральный директор)', re.IGNORECASE),
    # "Управляющий: Фамилия Имя Отчество" (ИП и некоммерческие)
    re.compile(rf'(?:Управляющий|Председатель|Директор-распорядитель)\s*:\s*{_FIO_3}', re.IGNORECASE),
    # "ФИО руководителя: Фамилия Имя Отчество" (egrul.itsoft.ru)
    re.compile(rf'ФИО\s+руководителя\s*:\s*{_FIO_3}', re.IGNORECASE),
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
        _finish_events.pop(run_id, None)
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


def finish_research(run_id: int) -> bool:
    with _lock:
        if run_id not in _runs or _runs[run_id]['status'] not in ('running', 'paused', 'finishing'):
            return False
        _runs[run_id]['status'] = 'finishing'
    finish_ev = _finish_events.get(run_id)
    if finish_ev:
        finish_ev.set()
    pause_ev = _pause_events.get(run_id)
    if pause_ev:
        pause_ev.set()
    try:
        conn = get_db()
        conn.execute("UPDATE research_runs SET status='finishing' WHERE id=?", (run_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    _log(run_id, '🏁 Пользователь завершает поиск — сохраняем найденное и останавливаемся')
    return True


def _finish_requested(run_id: int) -> bool:
    ev = _finish_events.get(run_id)
    return bool(ev and ev.is_set())


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
        companies = json.loads(clean).get('companies', [])
        for company in companies:
            website = normalize_official_website(company.get('website'))
            company['website'] = website
        return companies
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


def _extract_urls_from_text(text: str) -> list[str]:
    urls = []
    seen = set()
    for raw in re.findall(r'https?://[^\s<>"\')]+', text or ''):
        normalized = normalize_official_website(raw)
        if normalized and normalized not in seen:
            urls.append(normalized)
            seen.add(normalized)
    return urls


def _resolve_official_website(tavily, company: dict, combined_text: str, log_fn) -> str | None:
    name = company.get('name') or company.get('company_name') or ''

    for candidate in (company.get('website'), company.get('source_url')):
        official = normalize_official_website(candidate)
        if official:
            return official

    for candidate in _extract_urls_from_text(combined_text):
        official = normalize_official_website(candidate)
        if official:
            return official

    if not name:
        return None

    queries = [
        f'"{name}" официальный сайт',
        f'"{name}" сайт компании',
    ]
    for query in queries:
        try:
            res = tavily.search(query, max_results=5)
        except Exception:
            continue
        text = _results_to_text(res, 500)
        for candidate in _extract_urls_from_text(text):
            official = normalize_official_website(candidate)
            if official:
                log_fn(f'   🌐 Официальный сайт: {official}')
                return official
    return None


def is_valid_phone(phone: str) -> bool:
    """Телефон валиден если содержит минимум 7 цифр."""
    if not phone or str(phone).lower() in ('null', 'none', ''):
        return False
    digits = re.sub(r'\D', '', str(phone))
    return len(digits) >= 7


# ── Многопроходный поиск ЛПР ──────────────────────────────────────────────

def _multi_pass_lpr_search(tavily, company: dict, log_fn, requirements: set[str] | None = None) -> tuple[str | None, str]:
    """
    8-проходный поиск ЛПР (ФИО + email + телефон) с ранним выходом:

    Pass 1  — Директор из ЕГРЮЛ-прокси (rusprofile, zachestnyibiznes, checko, list-org)
    Pass 1b — Резервный поиск директора через checko/egrul если Pass 1 не дал результат
    Pass 2  — Личный email директора по имени + компании
    Pass 3  — Контакты с официального сайта (email + телефон)
    Pass 4  — Мобильный телефон директора если не нашли
    Pass 5  — ИНН компании (опционально по требованиям)
    Pass 6  — Общий email/телефон компании (опционально)
    Pass 7  — 2ГИС: верифицированный офисный телефон (если ещё нет)
    Pass 8  — Директор по ИНН через ЕГРЮЛ если не нашли через имя

    Источники: ЕГРЮЛ-прокси для директора, 2ГИС для телефонов.
    Возвращает (director_name, combined_text).
    """
    name    = company.get('name', '')
    website = company.get('website') or ''
    domain  = ''
    if website:
        website = normalize_official_website(website) or ''
    if website:
        domain = _url_domain(website)

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

    # Проход 1: директор из ЕГРЮЛ-прокси сайтов (rusprofile, zachestnyibiznes, checko, list-org)
    # Улучшено: явно таргетируем несколько бесплатных ЕГРЮЛ-источников
    q1 = (
        f'"{name}" директор руководитель '
        f'rusprofile.ru zachestnyibiznes.ru checko.ru list-org.com'
    )
    try:
        r1 = tavily.search(q1, max_results=6)
        text1 = _results_to_text(r1, 800)
        combined_parts.append(text1)
        _quick_scan(text1)
        for item in r1.get('results', []):
            found = extract_director_name(item.get('content') or '')
            if found:
                director_name = found
                log_fn(f'   📋 Директор из реестра: {director_name}')
                break
        # Если не нашли из первой выдачи — пробуем по другому запросу через checko
        if not director_name:
            q1b = f'"{name}" руководитель ФИО checko egrul реестр'
            r1b = tavily.search(q1b, max_results=4)
            text1b = _results_to_text(r1b, 500)
            combined_parts.append(text1b)
            for item in r1b.get('results', []):
                found = extract_director_name(item.get('content') or '')
                if found:
                    director_name = found
                    log_fn(f'   📋 Директор (доп. поиск): {director_name}')
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

    # Проход 7 (2ГИС): получаем верифицированный офисный телефон из 2ГИС.
    # 2ГИС — самый полный справочник компаний РФ, телефоны верифицируются владельцами.
    # Запускается если до сих пор нет телефона или нет общего email.
    if not found_phone or ('generic_email' in requirements and not found_email):
        q7 = f'"{name}" 2гис телефон адрес'
        try:
            r7 = tavily.search(q7, max_results=3)
            text7 = _results_to_text(r7, 400)
            combined_parts.append(text7)
            if not found_phone:
                phones7 = extract_phones_from_text(text7)
                if phones7:
                    found_phone = phones7[0]
                    log_fn(f'   📞 Телефон из 2ГИС: {found_phone}')
        except Exception:
            pass

    # Проход 8 (ИНН-поиск директора): если нашли ИНН но не нашли директора,
    # ищем напрямую по ИНН в ЕГРЮЛ-прокси сайтах — это даёт высокую точность.
    if not director_name:
        found_inn = extract_inn_from_text('\n'.join(combined_parts))
        if found_inn:
            q8 = f'ИНН {found_inn} директор руководитель rusprofile checko egrul'
            try:
                r8 = tavily.search(q8, max_results=4)
                text8 = _results_to_text(r8, 500)
                combined_parts.append(text8)
                for item in r8.get('results', []):
                    found = extract_director_name(item.get('content') or '')
                    if found:
                        director_name = found
                        log_fn(f'   📋 Директор по ИНН {found_inn}: {director_name}')
                        break
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

    requirements_list = normalize_contact_requirements(config.get('contact_requirements', DEFAULT_CONTACT_REQUIREMENTS))
    requirements = set(requirements_list)

    target_count = int(config.get('count', 10))
    keywords     = config.get('keywords', '').strip()

    seg_labels = [SEGMENT_LABELS.get(s, s) for s in segments_list]
    region_labels = [REGION_SUFFIX.get(r, r) for r in regions_list]
    scale_labels = [SCALE_LABELS.get(s, s) for s in scales_list]
    industry_labels = [INDUSTRY_LABELS.get(i, i) for i in industries_list]
    requirement_labels = [CONTACT_REQUIREMENT_LABELS.get(r, r) for r in requirements_list]
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
        if _finish_requested(run_id):
            break
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
            if _finish_requested(run_id):
                break
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
            website = normalize_official_website(lpr.get('website') or company.get('website'))
            if 'website' in requirements and not website:
                website = _resolve_official_website(tavily, company, combined_text, lambda m: _log(run_id, m))

            # Чистим "null" строки от модели
            personal_email = '' if personal_email in ('null', 'none') else personal_email
            generic_email = '' if generic_email in ('null', 'none') else generic_email
            mobile_phone = '' if mobile_phone in ('null', 'none') else mobile_phone
            generic_phone = '' if generic_phone in ('null', 'none') else generic_phone
            inn = '' if inn in ('null', 'none') else inn
            person = '' if person in ('null', 'none') else person

            lpr['company_name'] = lpr.get('company_name') or name
            lpr['website'] = website or None
            lpr['email'] = personal_email or generic_email or None
            lpr['phone'] = mobile_phone or generic_phone or None
            lpr['personal_email'] = personal_email or None
            lpr['generic_email'] = generic_email or None
            lpr['mobile_phone'] = mobile_phone or None
            lpr['generic_phone'] = generic_phone or None
            lpr['inn'] = inn or None

            ok_requirements, requirement_error = contact_satisfies_requirements(lpr, requirements_list)
            if not ok_requirements:
                _log(run_id, f'   ⛔  {requirement_error} — компания не засчитывается, ищем дальше')
                continue

            # Строим список строк для сохранения (1 или 2 при multi-email)
            contact_rows = _build_contact_rows_for_save(lpr, requirements_list)
            if not contact_rows:
                reqs_set = set(requirements_list)
                if 'personal_email' in reqs_set and 'generic_email' in reqs_set:
                    _log(run_id, '   ⛔  требуются оба типа email, но не оба найдены — пропускаем')
                else:
                    _log(run_id, '   ⛔  email не найден — пропускаем')
                continue

            today_str = datetime.now().strftime('%Y-%m-%d')
            any_saved  = False

            for row_email, contact_row in contact_rows:
                if len(found_contacts) >= target_count:
                    break

                if row_email and row_email in existing_emails:
                    _log(run_id, f'   ⏭  {row_email} — уже в базе')
                    continue

                if row_email:
                    existing_emails.add(row_email)

                contact_row['segment'] = segment_label
                contact_row['region']  = region_label
                found_contacts.append(contact_row)
                _update_found_count(run_id, len(found_contacts))

                # Сохраняем сразу — виден в UI до завершения запуска
                try:
                    conn_now = get_db()
                    conn_now.execute(
                        """INSERT OR IGNORE INTO contacts
                           (company_name, website, person_name, title,
                            email, personal_email, generic_email,
                            phone, mobile_phone, generic_phone,
                            inn, source_url, segment, region,
                            date_found, status, run_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',?)""",
                        (contact_row.get('company_name'),
                         contact_row.get('website'),
                         contact_row.get('person_name'),
                         contact_row.get('title'),
                         contact_row.get('email')          or None,
                         contact_row.get('personal_email') or None,
                         contact_row.get('generic_email')  or None,
                         contact_row.get('phone')          or None,
                         contact_row.get('mobile_phone')   or None,
                         contact_row.get('generic_phone')  or None,
                         contact_row.get('inn')            or None,
                         contact_row.get('source_url'),
                         contact_row.get('segment'),
                         contact_row.get('region'),
                         today_str, run_id)
                    )
                    conn_now.commit()
                    conn_now.close()
                    any_saved = True
                except Exception as e:
                    _log(run_id, f'⚠️ Ошибка записи: {e}')

                person_log  = contact_row.get('person_name') or director_name or '???'
                phone_log   = contact_row.get('phone') or ''
                inn_log     = contact_row.get('inn') or ''
                detail = ' | '.join(filter(None, [
                    row_email, phone_log, f'ИНН {inn_log}' if inn_log else ''
                ]))
                remaining = target_count - len(found_contacts)
                _log(run_id, f'   ✅ {person_log} — {detail} | найдено {len(found_contacts)}/{target_count}, осталось {remaining}')

            if any_saved:
                existing_companies.add(norm)

            time.sleep(0.1)

        if _finish_requested(run_id):
            break

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
    if _finish_requested(run_id):
        _log(run_id, f'✅ Поиск завершён пользователем. Сохранено в базу: {saved} новых контактов')
    else:
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
    _finish_events[run_id] = threading.Event()

    t = threading.Thread(target=_research_worker, args=(run_id, config), daemon=True)
    t.start()
    return run_id
