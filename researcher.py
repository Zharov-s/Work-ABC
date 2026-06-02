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
import requests
from concurrent.futures import ThreadPoolExecutor
from database import get_db

TAVILY_API_KEY  = os.getenv('TAVILY_API_KEY', '')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL    = os.getenv('OLLAMA_MODEL', 'gemma3:4b')   # улучшен с qwen2.5:1.5b

# Groq API — бесплатный, мощный (llama-3.3-70b = 70B params, 500+ t/s)
GROQ_API_KEY   = os.getenv('GROQ_API_KEY', '')
GROQ_BASE_URL  = 'https://api.groq.com/openai/v1'
GROQ_MODEL     = 'llama-3.3-70b-versatile'

TAVILY_TIMEOUT_SECONDS = 8

# Активный LLM: Groq если есть ключ, иначе Ollama
if GROQ_API_KEY:
    ACTIVE_LLM_BASE  = GROQ_BASE_URL
    ACTIVE_LLM_KEY   = GROQ_API_KEY
    ACTIVE_LLM_MODEL = GROQ_MODEL
else:
    ACTIVE_LLM_BASE  = OLLAMA_BASE_URL
    ACTIVE_LLM_KEY   = 'ollama'
    ACTIVE_LLM_MODEL = OLLAMA_MODEL

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
    'rd_nii':          'R&D и научная деятельность',
    'light_industrial':'Прочее light industrial',
}

# ВРИ (Вид разрешённого использования) и ОКВЭД для каждого сегмента.
# Используется в UI Research для подсказок и в поисковых запросах.
SEGMENT_VRI = {
    'electronics':     'ВРИ 6.3.1 · ОКВЭД 26.1–26.5',
    'medtech':         'ВРИ 6.3.1 · ОКВЭД 26.60, 32.50',
    'robotics':        'ВРИ 6.3, 6.3.3 · ОКВЭД 28, 29',
    'it_hardware':     'ВРИ 6.3.1 · ОКВЭД 26.20, 26.30',
    'laser_optics':    'ВРИ 6.3.1 · ОКВЭД 26.70',
    'rd_nii':          'ВРИ 6.12 · ОКВЭД 72',
    'light_industrial':'ВРИ 6.3.2 · ОКВЭД 27, 33',
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
    'email':           'Почты',
    'generic_email':   'Email общий',
    'personal_email':  'Email личный',
    'phone':           'Телефоны',
    'generic_phone':   'Телефон общий',
    'mobile_phone':    'Телефон мобильный',
    'inn':             'ИНН',
}

DEFAULT_CONTACT_REQUIREMENTS = ['email']

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

SOURCE_ONLY_DOMAINS = {
    'tbank.ru', 'www.tbank.ru', 'saby.ru', 'www.saby.ru',
    'rusprofile.ru', 'www.rusprofile.ru',
    'zachestnyibiznes.ru', 'www.zachestnyibiznes.ru',
    'checko.ru', 'www.checko.ru',
    'list-org.com', 'www.list-org.com',
    'sbis.ru', 'www.sbis.ru',
    'audit-it.ru', 'www.audit-it.ru',
    'spark-interfax.ru', 'www.spark-interfax.ru',
    'kartoteka.ru', 'www.kartoteka.ru',
    'nalog.ru', 'egrul.nalog.ru', 'www.nalog.ru',
    '2gis.ru', 'www.2gis.ru',
}


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


def _domain_base(domain_or_url: str) -> str:
    raw = (domain_or_url or '').strip().lower()
    if not raw:
        return ''
    if '/' in raw or ':' in raw:
        raw = _url_domain(raw)
    if raw.startswith('www.'):
        raw = raw[4:]
    labels = [p for p in raw.split('.') if p]
    if not labels:
        return ''
    if len(labels) >= 3 and labels[-2] in {'com', 'net', 'org', 'msk', 'spb'} and labels[-1] == 'ru':
        return labels[-3]
    if len(labels) >= 2:
        return labels[-2]
    return labels[0]


_CYR_TO_LAT = str.maketrans({
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
})


def _translit(value: str) -> str:
    return (value or '').lower().translate(_CYR_TO_LAT)


_COMPANY_TOKEN_STOPWORDS = {
    'ооо', 'ао', 'пао', 'зао', 'оао', 'нко', 'нпп', 'нпо', 'нпц', 'фгуп',
    'гуп', 'муп', 'ип', 'инн', 'кпп', 'огрн', 'москва', 'московская',
    'область', 'россия', 'рф', 'г', 'город', 'в', 'из', 'компания',
    'company', 'llc', 'jsc', 'pjsc',
}


def _company_tokens(name: str) -> list[str]:
    cleaned = normalize_company_name(name)
    cleaned = re.sub(r'\b(?:инн|кпп|огрн)\b.*$', '', cleaned, flags=re.IGNORECASE)
    raw_tokens = re.findall(r'[a-zA-Zа-яёА-ЯЁ0-9]+', cleaned)
    tokens = []
    for token in raw_tokens:
        token_l = token.lower()
        if token_l in _COMPANY_TOKEN_STOPWORDS or token_l.isdigit():
            continue
        translit = re.sub(r'[^a-z0-9]', '', _translit(token_l))
        if len(translit) >= 2:
            tokens.append(translit)
    return tokens


def _source_only_domain(domain: str) -> bool:
    domain = (domain or '').lower()
    if domain in SOURCE_ONLY_DOMAINS:
        return True
    return any(domain.endswith('.' + d) for d in SOURCE_ONLY_DOMAINS if not d.startswith('www.'))


def _domain_matches_company(name: str, domain_or_url: str) -> bool:
    base = _domain_base(domain_or_url)
    if len(base) < 3:
        return False
    tokens = _company_tokens(name)
    if not tokens:
        return False

    joined = ''.join(tokens)
    if len(joined) >= 3 and (base in joined or joined in base):
        return True

    acronym = ''.join(t[0] for t in tokens if t)
    if len(acronym) >= 3 and (base == acronym or base in acronym or acronym in base):
        return True

    return any(len(t) >= 4 and (base in t or t in base) for t in tokens)


def _company_name_in_text(name: str, text: str) -> bool:
    haystack = re.sub(r'[^a-z0-9]+', ' ', _translit(text or '')).strip()
    if not haystack:
        return False
    tokens = [t for t in _company_tokens(name) if len(t) >= 3]
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in haystack)
    return hits >= min(2, len(tokens))


def is_company_website_url(company_name: str, url: str, evidence_text: str = '') -> bool:
    official = normalize_official_website(url)
    if not official or not company_name:
        return False
    domain = _url_domain(official)
    if _domain_matches_company(company_name, official):
        return True
    if _source_only_domain(domain):
        return False
    return _company_name_in_text(company_name, evidence_text)


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
    if 'website' in reqs and not is_company_website_url(company_name, website):
        return False, 'нет официального сайта'
    if reqs.intersection({'personal_email', 'mobile_phone'}) and (not person or len(person.split()) < 2):
        return False, 'нет ФИО ЛПР для личного контакта'
    if 'personal_email' in reqs and (
        not personal_email or not is_valid_email_format(personal_email) or is_generic_email(personal_email)
    ):
        return False, 'нет личного email'
    if 'personal_email' in reqs and not email_belongs_to_company(personal_email, company_name, website):
        return False, 'личный email не относится к компании'
    if 'generic_email' in reqs and (
        not generic_email or not is_valid_email_format(generic_email) or not is_generic_email(generic_email)
    ):
        return False, 'нет общего email'
    if 'generic_email' in reqs and not email_belongs_to_company(generic_email, company_name, website):
        return False, 'общий email не относится к компании'
    if 'email' in reqs:
        valid_personal = (
            personal_email and is_valid_email_format(personal_email)
            and not is_generic_email(personal_email)
            and email_belongs_to_company(personal_email, company_name, website)
        )
        valid_generic = (
            generic_email and is_valid_email_format(generic_email)
            and is_generic_email(generic_email)
            and email_belongs_to_company(generic_email, company_name, website)
        )
        if not (valid_personal or valid_generic):
            return False, 'нет почты компании'
        if valid_personal and (not person or len(person.split()) < 2):
            return False, 'нет ФИО ЛПР для личного контакта'
    if 'mobile_phone' in reqs and (not is_valid_phone(mobile_phone) or not is_mobile_phone(mobile_phone)):
        return False, 'нет мобильного телефона'
    if 'generic_phone' in reqs and (
        not is_valid_phone(generic_phone) or is_mobile_phone(generic_phone)
    ):
        return False, 'нет общего телефона'
    if 'phone' in reqs and not (is_valid_phone(mobile_phone) or is_valid_phone(generic_phone)):
        return False, 'нет телефона'
    if 'inn' in reqs and len(inn) not in (10, 12):
        return False, 'нет ИНН'
    return True, ''


def project_contact_to_requirements(contact: dict, requirements) -> dict:
    """Return only the fields the user selected for the research result."""
    reqs = set(normalize_contact_requirements(requirements))
    projected = dict(contact)

    if 'website' not in reqs:
        projected['website'] = None
    if 'email' not in reqs and 'personal_email' not in reqs:
        projected['personal_email'] = None
    if 'email' not in reqs and 'generic_email' not in reqs:
        projected['generic_email'] = None
    if 'phone' not in reqs and 'mobile_phone' not in reqs:
        projected['mobile_phone'] = None
    if 'phone' not in reqs and 'generic_phone' not in reqs:
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
    want_any_email = 'email' in reqs

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

    elif want_any_email:
        best_email = personal or generic
        if not best_email:
            return []
        projected = project_contact_to_requirements(lpr, requirements_list)
        projected['email'] = best_email
        projected['phone'] = projected.get('mobile_phone') or projected.get('generic_phone')
        rows.append((best_email, projected))

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
        'электронные компоненты датчики контроллеры производитель Москва',
        'разработка производство электроника Москва контакты директор',
        '"ОКВЭД 26.51" производство приборов Москва компания директор',
        '"ОКВЭД 26.52" измерительные приборы контроль производство Москва',
        '"ОКВЭД 26.11" электронные компоненты производство Москва компания',
        # синонимы: завод, предприятие
        'завод электроника приборостроение Москва директор контакты',
        'предприятие электронные приборы измерения производство Москва',
        'НПП приборостроение электроника Москва сайт email',
        'ООО электроника разработка производство Москва email телефон',
    ],
    'medtech': [
        'медицинское оборудование производство компания Москва контакты',
        'медтех диагностика лабораторное оборудование производитель Москва',
        'фармацевтика биотехнологии пилотное производство Москва компания',
        '"ОКВЭД 26.60" медицинское хирургическое оборудование производство Москва',
        '"ОКВЭД 32.50" медицинские изделия инструменты производство Москва',
        '"ОКВЭД 21.20" фармацевтика производство препаратов Москва компания',
        'завод медицинского оборудования Москва директор email',
        'предприятие медицинские изделия производство Москва контакты',
        'медицинская техника производитель Москва ООО АО директор',
    ],
    'robotics': [
        'робототехника промышленная автоматизация производство Москва компания',
        'беспилотные системы БПЛА дроны производитель Москва',
        'мехатроника приводы сервосистемы разработка Москва',
        '"ОКВЭД 28.41" металлорежущие станки ЧПУ производство Москва',
        '"ОКВЭД 28.99" оборудование специального назначения производство Москва',
        '"ОКВЭД 28.12" гидравлическое пневматическое оборудование Москва',
        'завод станков ЧПУ автоматизация производство Москва email',
        'предприятие промышленные роботы автоматизация Москва контакты директор',
        'НПО робототехника автоматика Москва сайт директор',
    ],
    'it_hardware': [
        'производство серверов телекоммуникационное оборудование Москва',
        'отечественное ИТ hardware производство Москва компания',
        'вычислительная техника сетевое оборудование производитель Москва',
        '"ОКВЭД 26.20" производство компьютеров серверов Москва компания',
        '"ОКВЭД 26.30" коммуникационное оборудование производство Москва',
        '"ОКВЭД 26.12" монтаж печатных плат производство Москва',
        'российский производитель сервер коммутатор маршрутизатор Москва директор',
        'отечественный hardware ИТ оборудование производство Москва email',
        'завод вычислительная техника печатные платы Москва контакты',
    ],
    'laser_optics': [
        'лазерные системы оптические приборы производство Москва',
        'фотоника волоконная оптика производитель Москва',
        'лазерные технологии производство научное оборудование Москва',
        '"ОКВЭД 26.70" оптические приборы фотографическое оборудование Москва',
        '"ОКВЭД 27.40" светодиодная светотехника производство Москва',
        'завод лазерное оборудование оптика Москва директор email',
        'предприятие лазерные системы производство Москва контакты',
        'НПП лазерные оптические технологии Москва сайт руководитель',
    ],
    'rd_nii': [
        'НИИ научно-исследовательский институт опытное производство Москва директор',
        'конструкторское бюро КБ разработки производство Москва',
        'научно-производственное предприятие НПП НИОКР Москва',
        'R&D центр разработки технологии прототип Москва компания',
        'опытный образец инжиниринг технологии Москва компания директор',
        '"ОКВЭД 72.19" научные исследования разработки Москва компания',
        '"ОКВЭД 72.11" биотехнологии исследования лаборатория Москва',
        'ОКБ особое конструкторское бюро Москва разработки директор email',
        'ФГУП ФГБУ научное производство Москва контакты руководитель',
        'инжиниринговый центр НИОКР разработки производство Москва',
    ],
    'light_industrial': [
        'лёгкое производство технопарк Москва компания',
        'производственная компания технопарк сборка Москва',
        'сборочное производство инжиниринг сервисный центр Москва',
        '"ОКВЭД 27.11" электродвигатели трансформаторы производство Москва',
        '"ОКВЭД 33.12" ремонт монтаж машин оборудования Москва компания',
        'малое производство мастерская цех Москва компания директор email',
        'производство нестандартного оборудования Москва контакты',
        'ООО производство сборка монтаж оборудования Москва директор',
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
        # rusprofile ОКВЭД: прямые запросы к ЕГРЮЛ-прокси
        'rusprofile.ru "ОКВЭД 26.51" Москва производство электроника директор ИНН',
        'rusprofile.ru "ОКВЭД 26.11" электронные компоненты Москва директор',
        'site:rusprofile.ru производство приборов электроники Москва руководитель',
    ],
    'medtech': [
        'резиденты технопарка Москва медицинское оборудование производство',
        'Pharmtech 2024 2025 экспоненты Москва производитель медтех',
        'импортозамещение медицинские изделия производство Москва компания',
        'московский медицинский кластер резидент производитель',
        'site:2gis.ru медицинское оборудование производство Москва',
        'checko.ru медтех производство медицинские изделия Москва руководитель',
        'list-org.com биотехнологии медоборудование Москва компания директор',
        'rusprofile.ru "ОКВЭД 26.60" медицинское оборудование Москва директор ИНН',
        'rusprofile.ru "ОКВЭД 32.50" медицинские изделия производство Москва',
        'site:rusprofile.ru биотехнологии лабораторное диагностика Москва директор',
    ],
    'robotics': [
        'технопарк Москва робототехника автоматизация резидент компания',
        'ИННОПРОМ 2024 2025 промышленная автоматизация Москва экспонент',
        'импортозамещение промышленные роботы производство Москва',
        'ОЭЗ Москва мехатроника приводы производство резидент',
        'site:2gis.ru промышленная автоматизация робототехника Москва',
        'checko.ru станки ЧПУ робототехника автоматизация Москва директор ИНН',
        'list-org.com мехатроника сервоприводы производство Москва руководитель',
        'rusprofile.ru "ОКВЭД 28.41" станки ЧПУ промышленное оборудование Москва',
        'rusprofile.ru "ОКВЭД 28.99" специализированное оборудование Москва ИНН',
        'site:rusprofile.ru робототехника промышленная автоматизация Москва директор',
    ],
    'it_hardware': [
        'резиденты технопарка Москва производство ИТ оборудование серверы',
        'российские производители серверов коммутаторов Москва 2024 2025',
        'импортозамещение ИТ инфраструктура серверы производство Москва компания',
        'Rusnanotech ОЭЗ Москва ИТ оборудование резидент',
        'site:2gis.ru производство вычислительной техники серверов Москва',
        'checko.ru производство телекоммуникационного оборудования Москва директор',
        'list-org.com ИТ hardware серверы коммутаторы Москва производитель',
        'rusprofile.ru "ОКВЭД 26.20" производство компьютеров серверов Москва ИНН',
        'rusprofile.ru "ОКВЭД 26.30" телекоммуникационное оборудование Москва',
        'site:rusprofile.ru отечественное ИТ hardware производство Москва ИНН',
    ],
    'laser_optics': [
        'технопарк Москва лазерные оптические системы производство резидент',
        'Фотоника 2024 2025 Москва участники производитель лазеры',
        'импортозамещение лазеры оптика производство Москва компания',
        'site:2gis.ru лазерные оптические технологии производство Москва',
        'checko.ru лазерные системы оптические приборы Москва директор ИНН',
        'rusprofile.ru "ОКВЭД 26.70" оптические приборы фотоника Москва директор',
        'site:rusprofile.ru лазерные технологии волоконная оптика Москва руководитель',
    ],
    'rd_nii': [
        'резиденты технопарка НИИ научные организации разработки Москва',
        'СКОЛКОВО резидент разработки производство Москва компания',
        'ОЭЗ Технополис Москва резидент НИИ научная деятельность',
        'импортозамещение R&D НИОКР разработки производство Москва',
        'site:2gis.ru научно-производственное предприятие Москва',
        'checko.ru ОКВЭД 72 НИИ КБ Москва директор ИНН',
        'list-org.com научные исследования разработки Москва руководитель',
        'rusprofile.ru "ОКВЭД 72.19" НИОКР НИИ КБ Москва директор ИНН',
        'rusprofile.ru "ОКВЭД 72.11" биотехнологии исследования Москва',
        'site:rusprofile.ru научно-производственное предприятие НПП НПО Москва',
    ],
    'light_industrial': [
        'резиденты промышленного технопарка Москва лёгкое производство R&D',
        'технопарк Москва производство шоурум офис аренда класс А',
        'московские производственные компании технопарк сборка инжиниринг',
        'резиденты технополис Москва производство 2024',
        'site:2gis.ru производство инжиниринг сборка Москва компания',
        'checko.ru промышленное производство сборка Москва ИНН директор',
        'list-org.com лёгкое производство R&D Москва компания руководитель',
        'rusprofile.ru "ОКВЭД 33.12" ремонт монтаж машин Москва директор ИНН',
        'rusprofile.ru "ОКВЭД 27.11" электродвигатели трансформаторы Москва',
        'site:rusprofile.ru сборочное производство инжиниринг технопарк Москва',
    ],
}

# ОКВЭД → список кодов для каждого сегмента (для rusprofile scraper)
SEGMENT_OKVED_CODES = {
    'electronics':      ['26.51', '26.52', '26.11', '26.12', '26.20'],
    'medtech':          ['26.60', '32.50', '21.20', '21.10'],
    'robotics':         ['28.41', '28.99', '28.12', '28.11'],
    'it_hardware':      ['26.20', '26.30', '26.12'],
    'laser_optics':     ['26.70', '27.40'],
    'rd_nii':           ['72.19', '72.11', '72.20'],
    'light_industrial': ['33.12', '27.11', '28.21', '27.90'],
}

# Коды регионов rusprofile (Москва=77, МО=50)
_RUSPROFILE_REGION = {'moscow': '77', 'mo': '50', 'russia': ''}


def _scrape_rusprofile_okved(okved_code: str, region_key: str = 'moscow',
                              max_pages: int = 2, timeout: int = 8) -> list[dict]:
    """
    Прямой скрапинг rusprofile.ru/search по ОКВЭД + регион.
    Возвращает список компаний [{name, inn, website, source_url}].
    Бесплатно, без API-ключей. Graceful fallback при любой ошибке.
    """
    region_code = _RUSPROFILE_REGION.get(region_key, '77')
    companies: list[dict] = []
    seen: set[str] = set()

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    for page in range(1, max_pages + 1):
        try:
            params = {'query': okved_code, 'page': str(page)}
            if region_code:
                params['region'] = region_code
            resp = requests.get(
                'https://www.rusprofile.ru/search',
                params=params,
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code != 200:
                break
            text = resp.text

            # Извлекаем названия компаний из HTML (ищем ссылки /id/...)
            for m in re.finditer(
                r'href="/id/(\d+)"[^>]*>([^<]{3,80})</a>',
                text
            ):
                raw_name = m.group(2).strip()
                if not raw_name or len(raw_name) < 3:
                    continue
                norm = normalize_company_name(raw_name)
                if norm and norm not in seen:
                    seen.add(norm)
                    source_url = f'https://www.rusprofile.ru/id/{m.group(1)}'
                    companies.append({
                        'name': raw_name,
                        'website': None,
                        'source_url': source_url,
                        'description': '',
                    })

            # ИНН рядом с названием (rusprofile показывает его в карточке)
            for m_inn in re.finditer(r'ИНН[:\s]*(\d{10}|\d{12})', text):
                inn_val = m_inn.group(1)
                # Привязываем к последней добавленной компании без ИНН
                for c in reversed(companies):
                    if not c.get('inn'):
                        c['inn'] = inn_val
                        break

            if not companies and page == 1:
                break

        except Exception:
            break

    return companies[:30]


_2GIS_REGION_ID = {'moscow': '4504222397915426', 'mo': '4504202380095685', 'russia': ''}

_2GIS_SEGMENT_QUERIES = {
    'electronics':      ['производство электроники', 'приборостроение', 'электронные компоненты'],
    'medtech':          ['медицинское оборудование производство', 'медтех', 'лабораторное оборудование'],
    'robotics':         ['робототехника', 'промышленная автоматизация', 'станки с ЧПУ'],
    'it_hardware':      ['производство серверов', 'телекоммуникационное оборудование'],
    'laser_optics':     ['лазерные технологии', 'оптические приборы'],
    'rd_nii':           ['научно-производственное предприятие', 'НИИ', 'R&D'],
    'light_industrial': ['производство оборудования', 'инжиниринговая компания'],
}


def _fetch_2gis_companies(segment: str, region_key: str = 'moscow',
                           max_results: int = 20, timeout: int = 8) -> list[dict]:
    """
    Поиск компаний через 2ГИС (бесплатный, без API-ключа).
    Возвращает [{name, website, source_url, description}].
    """
    queries = _2GIS_SEGMENT_QUERIES.get(segment, [])
    region_id = _2GIS_REGION_ID.get(region_key, '')
    companies: list[dict] = []
    seen: set[str] = set()

    for q_text in queries[:2]:
        try:
            params = {
                'q': q_text,
                'type': 'branch',
                'fields': 'items.name,items.org.name,items.point,items.contact_groups',
                'page_size': str(max_results),
                'locale': 'ru_RU',
            }
            if region_id:
                params['region_id'] = region_id

            resp = requests.get(
                'https://catalog.api.2gis.com/3.0/items',
                params=params,
                timeout=timeout,
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            for item in data.get('result', {}).get('items', []):
                raw_name = (item.get('org', {}) or {}).get('name') or item.get('name') or ''
                raw_name = raw_name.strip()
                if not raw_name or len(raw_name) < 3:
                    continue
                norm = normalize_company_name(raw_name)
                if not norm or norm in seen:
                    continue
                seen.add(norm)

                website = None
                for cg in (item.get('contact_groups') or []):
                    for contact in (cg.get('contacts') or []):
                        if contact.get('type') == 'website':
                            website = normalize_official_website(contact.get('value', ''))
                            break
                    if website:
                        break

                companies.append({
                    'name': raw_name,
                    'website': website,
                    'source_url': f'https://2gis.ru/search/{requests.utils.quote(raw_name)}',
                    'description': '',
                })
                if len(companies) >= max_results:
                    break

        except Exception:
            continue

    return companies


# ── DuckDuckGo поиск (бесплатно, без API-ключа) ───────────────────────────

def _search(tavily, query: str, max_results: int = 5) -> dict:
    """
    Универсальный поиск с автоматическим fallback:
    Tavily (если работает) → DuckDuckGo (всегда бесплатно).
    Используется везде вместо прямых _search(tavily, ) вызовов.
    """
    try:
        result = requests.post(
            tavily.base_url + '/search',
            data=json.dumps({
                'query': query,
                'search_depth': 'basic',
                'topic': 'general',
                'include_answer': False,
                'include_raw_content': False,
                'max_results': max_results,
            }),
            headers=tavily.headers,
            timeout=TAVILY_TIMEOUT_SECONDS,
        )
        result.raise_for_status()
        result = result.json()
        if result.get('results'):
            return result
    except Exception:
        pass
    return _ddgs_search(query, max_results=max_results)


def _ddgs_search(query: str, max_results: int = 5) -> dict:
    """
    Поиск через DuckDuckGo — бесплатная альтернатива Tavily.
    Возвращает dict в формате Tavily (results: [{title, url, content}]).
    """
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results + 5):
                url   = item.get('href', '')
                title = item.get('title', '')
                # Пропускаем статьи, каталоги, образование и прочий нерелевантный контент
                title_lower = title.lower()
                if any(w in title_lower for w in [
                    'не работает', 'сбой', 'проблема', 'ошибка', 'обновление',
                    'скачать', 'установить', 'почему', 'как войти', 'советы',
                    'рейтинг', 'топ ', 'обзор', 'новости', 'статья', 'блог',
                    'все о ', 'все об ', 'что такое', 'как выбрать', 'каталог',
                    'купить', 'цена', 'стоимость', 'отзывы', 'форум',
                    'колледж', 'университет', 'академия',
                    'поступление', 'абитуриент', 'учебный', 'курсы',
                    'контрольно-измерительн', 'датчики давления',
                ]):
                    continue
                results.append({
                    'title':   title,
                    'url':     url,
                    'content': item.get('body', ''),
                })
                if len(results) >= max_results:
                    break
        return {'results': results}
    except Exception:
        return {'results': []}


def _compact_search_query(parts: list[str], max_len: int = 180) -> str:
    query_parts: list[str] = []
    for part in parts:
        normalized = ' '.join(str(part or '').split())
        if not normalized:
            continue
        current = ' '.join(query_parts)
        if current and normalized.lower() in current.lower():
            continue
        candidate = ' '.join(query_parts + [normalized])
        if len(candidate) <= max_len:
            query_parts.append(normalized)
            continue

        remaining = max_len - len(current) - (1 if current else 0)
        if remaining > 20:
            trimmed = normalized[:remaining].rsplit(' ', 1)[0] or normalized[:remaining]
            query_parts.append(trimmed)
        break
    return ' '.join(query_parts)


def _requirement_query_suffix(requirements: set[str]) -> str:
    if 'email' in requirements:
        return 'email контакты'
    if 'personal_email' in requirements:
        return 'личный email руководитель'
    if 'generic_email' in requirements:
        return 'общий email контакты'
    if 'mobile_phone' in requirements:
        return 'мобильный телефон руководитель'
    if 'generic_phone' in requirements:
        return 'городской телефон контакты'
    if 'phone' in requirements:
        return 'телефон контакты'
    if 'inn' in requirements:
        return 'ИНН реквизиты'
    if 'website' in requirements:
        return 'официальный сайт'
    return 'контакты'


# Заблокированные общие email-адреса
BLOCKED_EMAIL_PREFIXES = {
    'info', 'sales', 'office', 'support', 'mail', 'contact', 'zakaz',
    'hello', 'admin', 'reception', 'corp', 'marketing', 'pr', 'press',
    'media', 'hr', 'career', 'communications', 'comms', 'post', 'inbox',
    'noreply', 'no-reply', 'feedback', 'help', 'service', 'request',
    'quality', 'tender', 'zakupki', 'buh', 'director', 'general',
    'business', 'welcome', 'client', 'clients', 'customer', 'personal',
    # дополнительные общие адреса
    'manager', 'managers', 'tech', 'job', 'jobs', 'work', 'connect',
    'team', 'news', 'events', 'promo', 'dealer', 'dealers',
    'partner', 'partners', 'agent', 'agents', 'torg', 'opt', 'optom',
    'price', 'prices', 'order', 'orders', 'secretary', 'kancel',
    'ceo', 'cto', 'cfo', 'coo', 'ask', 'send',
    'contract', 'contracts', 'doc', 'docs', 'document', 'documents',
    'consult', 'consulting', 'legal', 'law', 'accounting', 'finance',
}

# Бесплатные почтовые домены — не принадлежат конкретной компании
_FREEMAIL_DOMAINS: frozenset[str] = frozenset({
    'gmail.com', 'googlemail.com',
    'mail.ru', 'bk.ru', 'inbox.ru', 'list.ru', 'internet.ru',
    'yandex.ru', 'yandex.com', 'ya.ru',
    'rambler.ru', 'lenta.ru', 'ro.ru',
    'hotmail.com', 'hotmail.ru', 'outlook.com', 'live.com',
    'yahoo.com', 'yahoo.ru',
    'icloud.com', 'me.com', 'mac.com',
    'protonmail.com', 'proton.me',
    'tutanota.com',
    'mail.com', 'email.com', 'fastmail.com',
    'ukr.net',
})


def is_freemail_domain(email: str) -> bool:
    """True если email на публичном почтовом сервисе (gmail, mail.ru и т.п.)."""
    if not email or '@' not in email:
        return False
    domain = email.rsplit('@', 1)[1].lower().strip()
    return domain in _FREEMAIL_DOMAINS

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


def email_belongs_to_company(email: str, company_name: str, website: str | None = None) -> bool:
    if not is_valid_email_format(email) or '@' not in email:
        return False
    domain = email.rsplit('@', 1)[1].lower()
    # Бесплатные почтовые сервисы — не корпоративные адреса
    if domain in _FREEMAIL_DOMAINS:
        return False
    if website:
        website_domain = _url_domain(website)
        if _domain_base(domain) == _domain_base(website_domain):
            return True
    return _domain_matches_company(company_name, domain)


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


_REGION_ADDRESS_TOKENS = {
    'moscow':  {'москва', 'москве', 'московск'},
    'mo':      {'московская', 'московской', 'подмосковье'},
    'russia':  set(),  # любой адрес подходит
}


def _address_matches_region(address: str, regions: list[str]) -> bool:
    """True если адрес из ЕГРЮЛ соответствует одному из выбранных регионов."""
    if not address or not regions or 'russia' in regions:
        return True
    addr_lower = address.lower()
    for region in regions:
        tokens = _REGION_ADDRESS_TOKENS.get(region, set())
        if any(tok in addr_lower for tok in tokens):
            return True
    return False


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

def _ollama_chat(client, messages: list, expect_json: bool = False, model: str | None = None) -> str:
    active_model = model or ACTIVE_LLM_MODEL
    kwargs = dict(model=active_model, messages=messages, temperature=0.1, max_tokens=600)
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


def _check_llm(client) -> bool:
    """Проверяет доступность LLM — Groq или Ollama."""
    try:
        models = client.models.list()
        return any(ACTIVE_LLM_MODEL in m.id for m in models.data)
    except Exception:
        return False

def _check_ollama(client) -> bool:
    return _check_llm(client)


# ── Быстрый regex-экстрактор компаний (без LLM, ~0.1 мс) ──────────────────

# Юрлицо + название в кавычках или без
# Паттерн 1: ООО «Название с пробелами»
_COMPANY_QUOTED_RE = re.compile(
    r'\b((?:ООО|АО|ПАО|ЗАО|НКО|НПО|НПП|НПЦ|ГУП|МУП|ФГУП|ФГБОУ|ОАО|ИП|ГК)\s*'
    r'[«"\'"„]([^«»""\']{2,60})[»"\'""])',
    re.IGNORECASE,
)
# Паттерн 2: ООО Название без кавычек (до пунктуации)
_COMPANY_PLAIN_RE = re.compile(
    r'\b((?:ООО|АО|ПАО|ЗАО|НКО|НПО|НПП|НПЦ|ГУП|МУП|ФГУП|ОАО|ИП)\s+'
    r'([А-ЯЁA-Z][А-ЯЁA-Za-zёа-я0-9\-]{1,40}(?:\s+[А-ЯЁA-Za-zёа-я0-9\-]{1,40}){0,4}))'
    r'(?=\s*[,.\n\r;|–—(]|$)',
    re.IGNORECASE,
)

# Слова, указывающие что результат не про компанию
_NOT_COMPANY_WORDS = frozenset([
    'новости', 'статья', 'форум', 'вакансии', 'купить', 'отзывы',
    'wikipedia', 'vikipedia', 'рейтинг', 'список', 'каталог',
])


def _clean_company_candidate(name: str) -> str:
    cleaned = re.sub(r'\s+', ' ', (name or '').strip().rstrip('.,;:|–—-'))
    cleaned = re.sub(r'\s+(?:ИНН|КПП|ОГРН)\b.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+(?:официальный\s+сайт|сайт|контакты|реквизиты|профиль)\b.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+(?:Москва|Московская область|Россия|РФ)\b.*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+(?:в|из)$', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip().rstrip('.,;:|–—-')


def _extract_companies_fast(search_results: dict) -> list[dict]:
    """
    Regex-based экстракция компаний из Tavily-результатов.
    Замена LLM-based _extract_companies: <0.5 мс вместо ~4000 мс.

    Алгоритм:
    1. Ищет юр. формы (ООО/АО/...) в title + начале content
    2. URL выдачи сохраняет как source_url
    3. website заполняет только если домен похож на компанию или доказан текстом
    4. Извлекает компании из title только для не-агрегаторных доменов
    """
    companies: list[dict] = []
    seen: set[str] = set()
    by_norm: dict[str, dict] = {}

    for item in search_results.get('results', []):
        title   = (item.get('title') or '').strip()
        url     = (item.get('url') or '').strip()
        content = (item.get('content') or '')[:600]

        evidence_text = title + '\n' + content
        website = normalize_official_website(url)

        search_text = evidence_text

        # Ищем явные юридические формы
        found_any = False
        for pattern in (_COMPANY_QUOTED_RE, _COMPANY_PLAIN_RE):
            for m in pattern.finditer(search_text):
                full_name = _clean_company_candidate(m.group(1))
                core_name = m.group(2).strip().rstrip('.,;')
                if len(core_name) < 2 or len(full_name) > 120:
                    continue
                found_any = True
                norm = normalize_company_name(full_name)
                official_site = website if is_company_website_url(full_name, url, evidence_text) else None
                if not norm:
                    continue
                if norm in seen:
                    if official_site and by_norm.get(norm) and not by_norm[norm].get('website'):
                        by_norm[norm]['website'] = official_site
                    continue
                seen.add(norm)
                company_item = {
                    'name': full_name,
                    'website': official_site,
                    'source_url': url,
                    'description': '',
                }
                companies.append(company_item)
                by_norm[norm] = company_item

        # Если юрформы нет — пробуем title (только если у него есть сайт компании)
        # Требуем наличие реального сайта чтобы не брать мусор из DuckDuckGo
        if not found_any and title and len(title) <= 80 and website and not _source_only_domain(_url_domain(url)):
            title_l = title.lower()
            if not any(w in title_l for w in _NOT_COMPANY_WORDS):
                short = re.split(r'\s*[|/—–]\s*', title)[0].strip().rstrip('.,;')
                if 3 <= len(short) <= 70:
                    norm = normalize_company_name(short)
                    if norm and norm not in seen and len(norm) > 2:
                        seen.add(norm)
                        company_item = {
                            'name': short,
                            'website': website if is_company_website_url(short, url, evidence_text) else None,
                            'source_url': url,
                            'description': '',
                        }
                        companies.append(company_item)
                        by_norm[norm] = company_item

    return companies[:20]


# ── AI-экстракторы ─────────────────────────────────────────────────────────

def _extract_companies(client, results_text: str, segment_label: str, industry_label: str = '') -> list:
    """Оставлен для совместимости. Не вызывается из основного цикла."""
    prompt = (
        'Из результатов поиска выдели реальные российские производственные компании. '
        'Верни ТОЛЬКО JSON: '
        '{"companies": [{"name": "название", "website": "url или null", "description": ""}]}'
    )
    try:
        raw = _ollama_chat(client, [
            {'role': 'system', 'content': prompt},
            {'role': 'user',   'content': f'Сегмент: {segment_label}\n\n{results_text}'},
        ], expect_json=True)
        clean = _extract_json(raw)
        if not clean:
            return []
        companies = json.loads(clean).get('companies', [])
        for company in companies:
            company['website'] = normalize_official_website(company.get('website'))
        return companies
    except Exception:
        return []


def _extract_lpr_from_combined(client, company: dict, combined_text: str,
                                known_director: str | None = None) -> dict | None:
    """
    Regex-first, LLM-fallback экстракция контактов ЛПР.

    Fast path (~0.5 мс): если regex нашёл ФИО + email + телефон — LLM не вызывается.
    Slow path (~4с): LLM только если regex дал неполный результат.
    """
    # ── FAST PATH: regex-экстракция ────────────────────────────────────────
    personal_emails = extract_emails_from_text(combined_text)
    generic_emails  = extract_generic_emails_from_text(combined_text)
    all_phones      = extract_phones_from_text(combined_text)
    inn_found       = extract_inn_from_text(combined_text) or ''

    # Директор из известного или из regex-паттернов
    person_name = known_director
    if not person_name:
        for pat in _DIRECTOR_PATTERNS:
            m = pat.search(combined_text)
            if m:
                candidate = m.group(1).strip()
                # Базовая валидация: 2+ слова, нет цифр
                if len(candidate.split()) >= 2 and not re.search(r'\d', candidate):
                    person_name = candidate
                    break

    personal_email = personal_emails[0] if personal_emails else None
    generic_email  = generic_emails[0]  if generic_emails  else None
    mobile_phone   = next((p for p in all_phones if is_mobile_phone(p)), None)
    generic_phone  = next((p for p in all_phones if not is_mobile_phone(p)), None) or \
                     (all_phones[0] if all_phones else None)

    # Если regex дал полный комплект — возвращаем без LLM (экономим 4с)
    has_contact = bool(person_name and (personal_email or generic_email or mobile_phone or generic_phone))
    has_email   = bool(personal_email or generic_email)
    has_phone   = bool(mobile_phone or generic_phone)

    if has_contact and has_email and has_phone:
        data = {
            'person_name':   person_name,
            'title':         'Генеральный директор' if known_director else None,
            'personal_email': personal_email,
            'generic_email':  generic_email,
            'mobile_phone':   mobile_phone if is_valid_phone(mobile_phone) else None,
            'generic_phone':  generic_phone if is_valid_phone(generic_phone) else None,
            'inn':            inn_found or None,
            'source_url':     None,
            'company_name':   company.get('name', ''),
            'website':        company.get('website', ''),
        }
        data['email'] = data['personal_email'] or data['generic_email']
        data['phone'] = data['mobile_phone']   or data['generic_phone']
        return data

    # ── SLOW PATH: LLM-экстракция (только если regex не дал достаточно) ────
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
        'Игнорируй контакты банков, справочников, агрегаторов и страниц-источников, '
        'если они не принадлежат самой компании. '
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

        pe = (data.get('personal_email') or data.get('email') or '').lower().strip()
        ge = (data.get('generic_email') or '').lower().strip()
        if pe and (not is_valid_email_format(pe) or is_generic_email(pe)):
            if is_valid_email_format(pe) and is_generic_email(pe) and not ge:
                ge = pe
            pe = ''
        if ge and not is_valid_email_format(ge):
            ge = ''
        if ge and not is_generic_email(ge):
            if not pe:
                pe = ge
            ge = ''
        data['personal_email'] = pe or None
        data['generic_email']  = ge or None

        # ФИО из реестра если модель не нашла
        if known_director and not data.get('person_name'):
            data['person_name'] = known_director
            data['title']       = data.get('title') or 'Генеральный директор'

        # Regex-фолбэки для email/phone/INN
        if not data.get('personal_email') and personal_emails:
            data['personal_email'] = personal_emails[0]
        if not data.get('generic_email') and generic_emails:
            data['generic_email'] = generic_emails[0]

        mp = data.get('mobile_phone')
        gp = data.get('generic_phone')
        ph = data.get('phone')
        if ph and not mp and is_mobile_phone(ph):
            mp = ph
        elif ph and not gp:
            gp = ph
        if not is_valid_phone(mp):
            mp = mobile_phone
        if not is_valid_phone(gp):
            gp = generic_phone or (all_phones[0] if all_phones else None)
        data['mobile_phone']  = mp if is_valid_phone(mp) else None
        data['generic_phone'] = gp if is_valid_phone(gp) else None

        raw_inn = re.sub(r'\D', '', str(data.get('inn') or ''))
        if len(raw_inn) not in (10, 12):
            raw_inn = inn_found
        data['inn']   = raw_inn or None
        data['email'] = data.get('personal_email') or data.get('generic_email')
        data['phone'] = data.get('mobile_phone')   or data.get('generic_phone')

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
        if official and is_company_website_url(name, official, combined_text):
            return official

    for candidate in _extract_urls_from_text(combined_text):
        official = normalize_official_website(candidate)
        if official and is_company_website_url(name, official, combined_text):
            return official

    if not name:
        return None

    queries = [
        f'"{name}" официальный сайт',
        f'"{name}" сайт компании',
    ]
    for query in queries:
        try:
            res = _search(tavily, query, max_results=5)
        except Exception:
            continue
        for item in res.get('results', []):
            candidate = item.get('url') or ''
            evidence = '\n'.join([
                item.get('title') or '',
                item.get('content') or item.get('raw_content') or '',
            ])
            official = normalize_official_website(candidate)
            if official and is_company_website_url(name, official, evidence):
                log_fn(f'   🌐 Официальный сайт: {official}')
                return official
    return None


def is_valid_phone(phone: str) -> bool:
    """Телефон валиден если содержит минимум 7 цифр."""
    if not phone or str(phone).lower() in ('null', 'none', ''):
        return False
    digits = re.sub(r'\D', '', str(phone))
    return len(digits) >= 7



# ── ЕГРЮЛ: прямой API nalog.ru (Pass 0) ───────────────────────────────────

def _fetch_egrul_nalog(company_name: str, timeout: int = 5) -> dict | None:
    """
    Pass 0: прямой запрос к официальному ЕГРЮЛ (egrul.nalog.ru).
    Протокол: POST / → токен, затем GET /search-result/{token}.
    Поля ответа: i=ИНН, g=должность+ФИО директора, n=полное название, o=ОГРН.
    Graceful fallback: при любой ошибке возвращает None.
    """
    try:
        if not company_name or len(company_name.strip()) < 3:
            return None
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://egrul.nalog.ru/',
            'Origin': 'https://egrul.nalog.ru',
        })
        # Шаг 1: получаем токен поиска
        r1 = s.post(
            'https://egrul.nalog.ru/',
            data={'query': company_name.strip(), 'regionCode': '', 'pg': ''},
            timeout=timeout,
        )
        if r1.status_code != 200:
            return None
        token_data = r1.json()
        if token_data.get('captchaRequired'):
            return None
        token = token_data.get('t', '')
        if not token:
            return None
        # Шаг 2: получаем результаты — nalog.ru обрабатывает поиск асинхронно,
        # нужен polling с паузой. Формат URL: /search-result/{token}
        import time as _time
        rows = []
        for _attempt in range(3):
            _time.sleep(0.3)
            r2 = s.get(f'https://egrul.nalog.ru/search-result/{token}', timeout=timeout)
            if r2.status_code != 200:
                break
            rows = r2.json().get('rows', [])
            if rows:
                break
        if not rows:
            return None

        name_norm = normalize_company_name(company_name)
        best = None
        for row in rows[:5]:
            if row.get('e'):  # е = дата ликвидации, непустое = ликвидирована
                continue
            # n = полное название, c = краткое (в этом API c = краткое имя, i = ИНН)
            row_name = row.get('n') or row.get('c') or ''
            row_norm = normalize_company_name(row_name)
            if row_norm == name_norm:
                best = row
                break
            if not best and _company_name_in_text(company_name, row_name):
                best = row
        if not best:
            best = next((r for r in rows[:3] if not r.get('e')), None)
        if not best:
            return None

        # i = ИНН (10 или 12 цифр)
        inn = re.sub(r'\D', '', best.get('i') or '')
        ogrn = re.sub(r'\D', '', best.get('o') or '')

        # g = "ДОЛЖНОСТЬ: Фамилия Имя Отчество" — парсим ФИО
        director_raw = (best.get('g') or '').strip()
        director = None
        if director_raw:
            # Убираем должность: "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР: Садриев Хурсандджон..."
            fio_part = re.sub(r'^[А-ЯЁABCDEFGHIJKLMNOPQRSTUVWXYZ\s]+:\s*', '', director_raw).strip()
            if not fio_part:
                fio_part = director_raw
            # Валидируем: 2+ слова, кириллица
            if len(fio_part.split()) >= 2 and re.search(r'[а-яё]', fio_part, re.IGNORECASE):
                director = fio_part

        return {
            'inn':      inn if len(inn) in (10, 12) else None,
            'ogrn':     ogrn or None,
            'director': director,
            'address':  (best.get('a') or '').strip() or None,
        }
    except Exception:
        return None

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

    # ── Pass 0: ЕГРЮЛ API (nalog.ru) — без Tavily, ~1с ─────────────────────
    egrul = _fetch_egrul_nalog(name)
    if egrul:
        if egrul.get('director'):
            director_name = egrul['director']
            log_fn(f'   📋 Директор из ЕГРЮЛ (nalog.ru): {director_name}')
        if egrul.get('inn'):
            combined_parts.append(f'ИНН из ЕГРЮЛ: {egrul["inn"]}')
        if egrul.get('address'):
            combined_parts.append(f'Адрес: {egrul["address"]}')
    else:
        egrul = {}

    # ── Passes 1 + 3 параллельно (экономим ~8с на компанию) ─────────────────
    def _run_pass1():
        q = (f'"{name}" директор руководитель '
             f'rusprofile.ru zachestnyibiznes.ru checko.ru list-org.com')
        r = _search(tavily, q, max_results=6)
        return _results_to_text(r, 800), r.get('results', [])

    def _run_pass3():
        q = (f'site:{domain} контакты email телефон' if domain
             else f'"{name}" контакты email телефон официальный')
        r = _search(tavily, q, max_results=4)
        return _results_to_text(r, 600)

    _pass1_text, _pass1_results = '', []
    _pass3_text = ''
    _par_timeout = TAVILY_TIMEOUT_SECONDS + 3

    with ThreadPoolExecutor(max_workers=2) as exc:
        f1 = exc.submit(_run_pass1)
        f3 = exc.submit(_run_pass3)
        try:
            _pass1_text, _pass1_results = f1.result(timeout=_par_timeout)
        except Exception:
            _pass1_text, _pass1_results = '', []
        try:
            _pass3_text = f3.result(timeout=_par_timeout)
        except Exception:
            _pass3_text = ''

    # Обрабатываем Pass 1
    combined_parts.append(_pass1_text)
    _quick_scan(_pass1_text)
    if not director_name:
        # ЕГРЮЛ не дал директора — ищем через регекс в результатах Tavily
        for item in _pass1_results:
            found = extract_director_name(item.get('content') or '')
            if found:
                director_name = found
                log_fn(f'   📋 Директор из реестра: {director_name}')
                break
    else:
        log_fn(f'   ✓ Директор подтверждён через ЕГРЮЛ: {director_name}')

    # Pass 1b: резервный поиск директора только если нужен личный контакт
    if not director_name and requirements and \
            requirements.intersection({'personal_email', 'mobile_phone'}):
        q1b = f'"{name}" руководитель ФИО checko egrul реестр'
        try:
            r1b = _search(tavily, q1b, max_results=4)
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
        queries_2 = [f'"{director_name}" "{name}" email']
        # Если домен известен — ищем директора на домене компании
        if domain:
            queries_2.append(f'"{director_name}" @{domain}')
            queries_2.append(f'site:{domain} "{director_name}"')
        for q2 in queries_2:
            if found_email:
                break
            try:
                r2 = _search(tavily, q2, max_results=4)
                text2 = _results_to_text(r2, 500)
                combined_parts.append(text2)
                _quick_scan(text2)
                if found_email:
                    log_fn(f'   📧 Email в выдаче: {found_email}')
            except Exception:
                pass

    # Обрабатываем Pass 3 (был запущен параллельно с Pass 1)
    combined_parts.append(_pass3_text)
    _quick_scan(_pass3_text)
    if found_phone:
        log_fn(f'   📞 Телефон в выдаче: {found_phone}')

    # Проход 4: телефон директора (только если до сих пор нет телефона)
    if director_name and not found_phone:
        q4 = f'"{name}" телефон мобильный директор контакты'
        try:
            r4 = _search(tavily, q4, max_results=3)
            combined_parts.append(_results_to_text(r4, 400))
        except Exception:
            pass

    requirements = requirements or set()
    if 'inn' in requirements:
        # Если ИНН уже получен из ЕГРЮЛ в Pass 0 — Tavily не нужен
        inn_from_egrul = egrul.get('inn')
        if inn_from_egrul:
            log_fn(f'   🔢 ИНН из ЕГРЮЛ: {inn_from_egrul} (Tavily Pass 5 пропущен)')
        else:
            q5 = f'"{name}" ИНН реквизиты'
            try:
                r5 = _search(tavily, q5, max_results=3)
                combined_parts.append(_results_to_text(r5, 500))
            except Exception:
                pass

    if 'email' in requirements or 'phone' in requirements or 'generic_email' in requirements or 'generic_phone' in requirements:
        q6 = (f'site:{domain} реквизиты контакты email телефон' if domain
              else f'"{name}" реквизиты контакты email телефон')
        try:
            r6 = _search(tavily, q6, max_results=3)
            combined_parts.append(_results_to_text(r6, 500))
        except Exception:
            pass

    # Проход 7 (2ГИС): только если явно нужен телефон и его нет
    if not found_phone and requirements and \
            requirements.intersection({'phone', 'mobile_phone', 'generic_phone'}):
        q7 = f'"{name}" 2гис телефон адрес'
        try:
            r7 = _search(tavily, q7, max_results=3)
            text7 = _results_to_text(r7, 400)
            combined_parts.append(text7)
            if not found_phone:
                phones7 = extract_phones_from_text(text7)
                if phones7:
                    found_phone = phones7[0]
                    log_fn(f'   📞 Телефон из 2ГИС: {found_phone}')
        except Exception:
            pass

    # Проход 8 (ИНН-поиск директора): только если нужен личный контакт и директор не найден
    if not director_name and requirements and \
            requirements.intersection({'personal_email', 'mobile_phone'}):
        # Приоритет: ИНН из ЕГРЮЛ (Pass 0) → затем из текста
        found_inn = egrul.get('inn') or extract_inn_from_text('\n'.join(combined_parts))
        if found_inn:
            q8 = f'ИНН {found_inn} директор руководитель rusprofile checko egrul'
            try:
                r8 = _search(tavily, q8, max_results=4)
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

    # Создаём LLM-клиент: Groq (70B, быстрый) если есть ключ, иначе Ollama
    client = OpenAI(base_url=ACTIVE_LLM_BASE, api_key=ACTIVE_LLM_KEY)
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
    if GROQ_API_KEY:
        _log(run_id, f'🤖 Модель: {GROQ_MODEL} (Groq API — 70B, быстро)')
    else:
        _log(run_id, f'🤖 Модель: {OLLAMA_MODEL} (Ollama)')

    # Проверяем LLM доступность
    if not GROQ_API_KEY and not _check_ollama(client):
        _log(run_id, f'❌ Ollama недоступна. Установите GROQ_API_KEY или запустите: ollama serve')
        _set_run_status(run_id, 'failed')
        return
    if GROQ_API_KEY:
        try:
            client.models.list()   # быстрая проверка Groq
        except Exception as e:
            _log(run_id, f'❌ Groq API недоступен: {e}')
            _set_run_status(run_id, 'failed')
            return

    from validator import validate_email as _validate_email

    # Кэш MX-проверок: домен → bool, чтобы не повторять DNS для одного домена
    _mx_domain_cache: dict[str, bool] = {}

    def _mx_ok(email: str) -> bool:
        if not email or '@' not in email:
            return False
        domain = email.rsplit('@', 1)[1].lower()
        if domain in _mx_domain_cache:
            return _mx_domain_cache[domain]
        result = _validate_email(email)
        ok = result in ('valid', 'unknown')
        _mx_domain_cache[domain] = ok
        return ok

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
    existing_inns = {
        re.sub(r'\D', '', r['inn'])
        for r in conn_main.execute('SELECT inn FROM contacts WHERE inn IS NOT NULL').fetchall()
        if r['inn'] and len(re.sub(r'\D', '', r['inn'])) in (10, 12)
    }
    conn_main.close()
    _log(run_id, f'📋 В базе: {len(existing_companies)} компаний, {len(existing_emails)} email — дубли пропустим')

    if keywords:
        _log(run_id, f'🔑 Доп. слова: {keywords}')

    # Строим список запросов: основные + дополнительные каналы
    all_queries = []
    seen_queries = set()
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
                    requirement_suffix = _requirement_query_suffix(requirements)

                    def add_query(raw_query: str, source_tag: str):
                        parts = [raw_query, industry_suffix, requirement_suffix, region_label]
                        if scale_suffix and scale_suffix != 'any':
                            parts.append(scale_suffix)
                        parts.append(keywords)
                        full_q = _compact_search_query(parts)
                        dedupe_key = full_q.lower()
                        if full_q and dedupe_key not in seen_queries:
                            seen_queries.add(dedupe_key)
                            all_queries.append(
                                (full_q, segment_label, industry_label, region_label, source_tag)
                            )

                    for q in SEGMENT_QUERIES.get(seg, []):
                        add_query(q, 'tavily')
                    # Дополнительные каналы: технопарки, выставки, импортозамещение
                    for q in EXTRA_DISCOVERY_QUERIES.get(seg, []):
                        add_query(q, 'extra')

    # ── Rusprofile + 2ГИС скрапинг в фоне (не блокирует старт Tavily-поиска) ──
    rusprofile_companies: list[dict] = []
    _scrape_lock = threading.Lock()

    def _run_scraping():
        for seg in segments_list:
            for okved in SEGMENT_OKVED_CODES.get(seg, []):
                for region_key in regions_list:
                    try:
                        batch = _scrape_rusprofile_okved(okved, region_key, max_pages=2)
                        if batch:
                            _log(run_id, f'🏭 Rusprofile ОКВЭД {okved}: {len(batch)} компаний')
                        with _scrape_lock:
                            rusprofile_companies.extend(batch)
                    except Exception:
                        pass
        for seg in segments_list:
            for region_key in regions_list:
                try:
                    batch_2gis = _fetch_2gis_companies(seg, region_key)
                    if batch_2gis:
                        _log(run_id, f'🗺 2ГИС {SEGMENT_LABELS.get(seg, seg)}: {len(batch_2gis)} компаний')
                    with _scrape_lock:
                        rusprofile_companies.extend(batch_2gis)
                except Exception:
                    pass

    _scrape_thread = threading.Thread(target=_run_scraping, daemon=True)
    _scrape_thread.start()

    found_contacts = []
    searched_names = set()
    state_lock = threading.Lock()

    for query, segment_label, industry_label, region_label, source_tag in all_queries:
        _pause_events[run_id].wait()  # блокируется, пока стоит на паузе
        if _finish_requested(run_id):
            break
        if len(found_contacts) >= target_count:
            break

        icon = '🔍' if source_tag == 'tavily' else '🏭'
        filter_label = f'{segment_label}' + (f' / {industry_label}' if industry_label else '')
        _log(run_id, f'{icon} [{filter_label}] {query}')

        # ── Поиск через Tavily ─────────────────────────────────────────────
        try:
            search_res = _search(tavily, query, max_results=10)
        except Exception as e:
            _log(run_id, f'❌ Tavily: {e}')
            search_res = {'results': []}

        companies_tavily = _extract_companies_fast(search_res)

        # ── Параллельный поиск через DuckDuckGo (бесплатно, без ключа) ───
        # Запускается для основных запросов (не extra), чтобы не перегружать
        companies_ddgs: list = []
        if source_tag == 'tavily':
            ddgs_res = _ddgs_search(query, max_results=5)
            if ddgs_res['results']:
                companies_ddgs = _extract_companies_fast(ddgs_res)

        # ── Объединяем результаты, дедупликация по нормализованному имени ─
        seen_in_batch: set[str] = set()
        companies: list = []
        for c in companies_tavily + companies_ddgs:
            norm = normalize_company_name(c.get('name', ''))
            if norm and norm not in seen_in_batch:
                seen_in_batch.add(norm)
                companies.append(c)

        ddgs_extra = max(0, len(companies) - len(companies_tavily))
        log_parts = [f'{len(companies)} компаний']
        if ddgs_extra:
            log_parts.append(f'+{ddgs_extra} из DuckDuckGo')
        if not search_res.get('results'):
            log_parts.append('Tavily пустой')
        _log(run_id, f'   {" | ".join(log_parts)}')

        # ── Параллельная обработка компаний (до 4 одновременно) ──────────────
        _seg_lbl = segment_label
        _reg_lbl = region_label

        def _do_company(company, _sl=_seg_lbl, _rl=_reg_lbl):
            name = (company.get('name') or '').strip()
            norm = normalize_company_name(name)
            if not name or not norm:
                return

            with state_lock:
                if _finish_requested(run_id) or len(found_contacts) >= target_count:
                    return
                if norm in existing_companies:
                    _log(run_id, f'   ⏭  {name} — уже в базе')
                    return
                if norm in searched_names:
                    return
                searched_names.add(norm)

            _pause_events[run_id].wait()
            _log(run_id, f'🏢 Новая: {name}')

            director_name, combined_text = _multi_pass_lpr_search(
                tavily, company, lambda m: _log(run_id, m), requirements
            )

            if not combined_text.strip():
                _log(run_id, '   ⚠️  Ничего не найдено по контактам')
                return

            if 'russia' not in regions_list:
                addr_match = re.search(r'Адрес:\s*(.+)', combined_text)
                egrul_address = addr_match.group(1).strip() if addr_match else ''
                if egrul_address and not _address_matches_region(egrul_address, regions_list):
                    _log(run_id, f'   ⏭  Адрес не соответствует региону ({egrul_address[:60]}) — пропускаем')
                    return

            lpr = _extract_lpr_from_combined(client, company, combined_text, director_name)

            if not lpr:
                if requirements.issubset({'company_name', 'website'}):
                    lpr = {
                        'company_name': company.get('name', ''),
                        'website': company.get('website', ''),
                        'source_url': company.get('source_url'),
                    }
                else:
                    _log(run_id, '   ⚠️  ЛПР/контакты не определены, пропускаем')
                    return

            person = (lpr.get('person_name') or '').strip()
            personal_email = (lpr.get('personal_email') or '').lower().strip()
            generic_email  = (lpr.get('generic_email') or '').lower().strip()
            mobile_phone   = (lpr.get('mobile_phone') or '').strip()
            generic_phone  = (lpr.get('generic_phone') or '').strip()
            inn            = (lpr.get('inn') or '').strip()
            result_company_name = _clean_company_candidate(lpr.get('company_name') or name)
            raw_website = lpr.get('website') or company.get('website')
            website = (
                normalize_official_website(raw_website)
                if is_company_website_url(result_company_name, raw_website, combined_text)
                else None
            )
            if 'website' in requirements and not website:
                website = _resolve_official_website(tavily, company, combined_text, lambda m: _log(run_id, m))

            for _f in ('null', 'none'):
                personal_email = '' if personal_email == _f else personal_email
                generic_email  = '' if generic_email  == _f else generic_email
                mobile_phone   = '' if mobile_phone   == _f else mobile_phone
                generic_phone  = '' if generic_phone  == _f else generic_phone
                inn            = '' if inn            == _f else inn
                person         = '' if person         == _f else person

            lpr['company_name']   = result_company_name
            lpr['website']        = website or None
            lpr['email']          = personal_email or generic_email or None
            lpr['phone']          = mobile_phone or generic_phone or None
            lpr['personal_email'] = personal_email or None
            lpr['generic_email']  = generic_email or None
            lpr['mobile_phone']   = mobile_phone or None
            lpr['generic_phone']  = generic_phone or None
            lpr['inn']            = inn or None
            lpr['source_url']     = lpr.get('source_url') or company.get('source_url')

            clean_inn = re.sub(r'\D', '', inn) if inn else ''

            with state_lock:
                if clean_inn and len(clean_inn) in (10, 12) and clean_inn in existing_inns:
                    _log(run_id, f'   ⏭  ИНН {clean_inn} уже в базе — пропускаем')
                    existing_companies.add(norm)
                    return

            ok_requirements, requirement_error = contact_satisfies_requirements(lpr, requirements_list)
            if not ok_requirements:
                _log(run_id, f'   ⛔  {requirement_error} — компания не засчитывается')
                return

            contact_rows = _build_contact_rows_for_save(lpr, requirements_list)
            if not contact_rows:
                reqs_set = set(requirements_list)
                if 'personal_email' in reqs_set and 'generic_email' in reqs_set:
                    _log(run_id, '   ⛔  требуются оба типа email, но не оба найдены — пропускаем')
                else:
                    _log(run_id, '   ⛔  email не найден — пропускаем')
                return

            # Мягкая MX-проверка: только логируем, не блокируем сохранение
            for row_email, _ in contact_rows:
                if row_email and not _mx_ok(row_email):
                    _log(run_id, f'   ⚠️  {row_email} — MX не найден (сохраняем)')
            valid_rows = list(contact_rows)

            today_str = datetime.now().strftime('%Y-%m-%d')
            any_saved = False

            with state_lock:
                for row_email, contact_row in valid_rows:
                    if len(found_contacts) >= target_count:
                        break
                    if row_email and row_email in existing_emails:
                        _log(run_id, f'   ⏭  {row_email} — уже в базе')
                        continue
                    if row_email:
                        existing_emails.add(row_email)

                    contact_row['segment'] = _sl
                    contact_row['region']  = _rl
                    found_contacts.append(contact_row)
                    _update_found_count(run_id, len(found_contacts))

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

                    person_log = contact_row.get('person_name') or director_name or '???'
                    phone_log  = contact_row.get('phone') or ''
                    inn_log    = contact_row.get('inn') or ''
                    detail = ' | '.join(filter(None, [
                        row_email, phone_log, f'ИНН {inn_log}' if inn_log else ''
                    ]))
                    remaining = target_count - len(found_contacts)
                    _log(run_id, f'   ✅ {person_log} — {detail} | найдено {len(found_contacts)}/{target_count}, осталось {remaining}')

                if any_saved:
                    existing_companies.add(norm)
                    if clean_inn and len(clean_inn) in (10, 12):
                        existing_inns.add(clean_inn)

        # Фильтруем уже известные компании до запуска потоков
        pending = [c for c in companies
                   if normalize_company_name((c.get('name') or '').strip()) not in existing_companies
                   and normalize_company_name((c.get('name') or '').strip()) not in searched_names
                   and normalize_company_name((c.get('name') or '').strip())]
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(_do_company, pending))
        except Exception as e:
            _log(run_id, f'⚠️ Ошибка пакетной обработки: {e}')

        if _finish_requested(run_id):
            break

    # Ждём фоновый скрапинг максимум 30 секунд
    _scrape_thread.join(timeout=30)

    # ── Обработка компаний из Rusprofile ОКВЭД (после основного цикла) ───────
    if rusprofile_companies and not _finish_requested(run_id) and len(found_contacts) < target_count:
        _log(run_id, f'🏭 Rusprofile: обрабатываем {len(rusprofile_companies)} компаний')
        _rp_sl = seg_labels[0] if seg_labels else 'Производство'
        _rp_rl = region_labels[0] if region_labels else 'Москва'
        pending_rp = [c for c in rusprofile_companies
                      if normalize_company_name((c.get('name') or '').strip()) not in existing_companies
                      and normalize_company_name((c.get('name') or '').strip()) not in searched_names]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda c, sl=_rp_sl, rl=_rp_rl: _do_company(c, sl, rl), pending_rp))

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
