# RESEARCH MAP — Полная карта системы поиска компаний и контактов

> Формат: машиночитаемый Markdown для AI-агентов.  
> Проект: ABCENTRUM Outreach Platform (`webapp/researcher.py`)  
> Дата актуальности: 2026-06-02

---

## 1. ОБЗОР СИСТЕМЫ

```
Пользователь (UI Research)
  → Фильтры (сегмент, регион, масштаб, отрасль, требования к контакту)
  → start_research(config) [app.py]
  → _research_worker(run_id, config) [researcher.py — daemon thread]
      ├── ФАЗА 0: Фоновый скрапинг (rusprofile.ru + 2GIS) — daemon thread
      ├── ФАЗА 1: Построение пула запросов (SEGMENT_QUERIES + EXTRA_DISCOVERY_QUERIES)
      ├── ФАЗА 2: Цикл запросов → Tavily → DDG → извлечение компаний
      ├── ФАЗА 3: На каждую компанию — многопроходный поиск ЛПР (8 passes)
      ├── ФАЗА 4: Извлечение контактов (regex fast path → LLM slow path)
      ├── ФАЗА 5: Валидация по требованиям пользователя
      └── ФАЗА 6: Сохранение в SQLite + пост-обработка rusprofile/2GIS
```

---

## 2. ВХОДНЫЕ ПАРАМЕТРЫ (config dict)

| Поле | Тип | Допустимые значения | По умолчанию |
|------|-----|---------------------|--------------|
| `segments` | list[str] | electronics, medtech, robotics, it_hardware, laser_optics, rd_nii, light_industrial | ['electronics'] |
| `regions` | list[str] | moscow, mo, russia | ['moscow'] |
| `company_scales` | list[str] | any, small, medium, large | ['any'] |
| `industries` | list[str] | construction, transport, media, it_telecom, finance, healthcare, education, culture, government, associations, trade, services, production | [] (все) |
| `contact_requirements` | list[str] | company_name, website, email, generic_email, personal_email, phone, generic_phone, mobile_phone, inn | ['email'] |
| `count` | int | целевое число контактов | 10 |
| `keywords` | str | дополнительные ключевые слова для запросов | '' |

---

## 3. СЕГМЕНТЫ И ОКВЭД

```yaml
electronics:
  label: "Электроника и приборостроение"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.51, 26.52, 26.11, 26.12, 26.20]
  queries_count: 10

medtech:
  label: "Медтех и фармацевтика"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.60, 32.50, 21.20, 21.10]
  queries_count: 9

robotics:
  label: "Робототехника и автоматизация"
  vri: "ВРИ 6.3, 6.3.3"
  okved_codes: [28.41, 28.99, 28.12, 28.11]
  queries_count: 9

it_hardware:
  label: "IT-производство и hardware"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.20, 26.30, 26.12]
  queries_count: 9

laser_optics:
  label: "Лазерные и оптические технологии"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.70, 27.40]
  queries_count: 8

rd_nii:
  label: "R&D и научная деятельность"
  vri: "ВРИ 6.12"
  okved_codes: [72.19, 72.11, 72.20]
  queries_count: 10

light_industrial:
  label: "Прочее light industrial"
  vri: "ВРИ 6.3.2"
  okved_codes: [33.12, 27.11, 28.21, 27.90]
  queries_count: 8
```

---

## 4. ФАЗА 0 — ФОНОВЫЙ СКРАПИНГ (daemon thread)

Запускается в `threading.Thread(daemon=True)` параллельно с основным поиском.  
Результаты присоединяются через `.join(timeout=30)` и обрабатываются ПОСЛЕ основного цикла.

### 4a. Rusprofile.ru — ОКВЭД скрапинг

```
Функция: _scrape_rusprofile_okved(okved_code, region_key, max_pages=2, timeout=8)
URL: GET https://www.rusprofile.ru/search?query={okved}&region={code}&page={n}
Метод: requests.get + regex парсинг HTML (без JS)
Паттерн: href="/id/(\d+)">([^<]{3,80})</a>

Коды регионов: moscow→77, mo→50, russia→''
Лимит: 30 компаний / вызов, 2 страницы / ОКВЭД
Данные: название, source_url (rusprofile), ИНН (если виден)
Ограничения: 403/429 при интенсивном скрапинге
```

### 4b. 2GIS Catalog API

```
Функция: _fetch_2gis_companies(segment, region_key, max_results=20, timeout=8)
URL: GET https://catalog.api.2gis.com/3.0/items
Params: q={query}, type=branch, region_id={id}, page_size=20, locale=ru_RU

Region IDs: moscow→4504222397915426, mo→4504202380095685
Запросы: до 2 вариантов на сегмент (из _2GIS_SEGMENT_QUERIES)
Данные: название компании, сайт (из contact_groups), source_url
Авторизация: не требуется (публичный API)
Ограничения: rate limit ~10-20 req/min
```

---

## 5. ФАЗА 1 — ПОСТРОЕНИЕ ПУЛА ЗАПРОСОВ

### Структура запроса

```
full_query = compact_join([
    raw_query,           # SEGMENT_QUERIES или EXTRA_DISCOVERY_QUERIES
    industry_suffix,     # до 2 терминов отрасли
    requirement_suffix,  # "email контакты" / "личный email руководитель" / ...
    region_label,        # "Москва" / "Московская область" / "Россия"
    scale_suffix,        # "малый бизнес" / "средний бизнес" / ""
    keywords,            # пользовательские ключевые слова
], max_len=180)
```

### Суффиксы требований

| Требование | Суффикс в запросе |
|-----------|-------------------|
| email | "email контакты" |
| personal_email | "личный email руководитель" |
| generic_email | "общий email контакты" |
| mobile_phone | "мобильный телефон руководитель" |
| generic_phone | "городской телефон контакты" |
| phone | "телефон контакты" |
| inn | "ИНН реквизиты" |
| website | "официальный сайт" |

### Источники запросов

```
SEGMENT_QUERIES:        ~10 запросов/сегмент
  - ОКВЭД-запросы: "ОКВЭД 26.51" производство Москва директор
  - Синонимы: завод/предприятие/НПП + ключевые слова

EXTRA_DISCOVERY_QUERIES: ~10 запросов/сегмент
  - технопарки, выставки, импортозамещение
  - site:rusprofile.ru + ОКВЭД
  - site:checko.ru + отрасль
  - site:list-org.com + отрасль
  - site:2gis.ru + категория

Дедупликация запросов: по lowercase ключу — дубли не добавляются
```

---

## 6. ФАЗА 2 — ДИСКАВЕРИ КОМПАНИЙ

### 6a. Поиск через Tavily

```
Функция: _search(tavily, query, max_results=10)
API: POST https://api.tavily.com/search
Params: search_depth=basic, include_answer=false, include_raw_content=false
Timeout: 8 сек
Auth: TAVILY_API_KEY (env)
Fallback: _ddgs_search() если Tavily вернул ошибку или пустой ответ
```

### 6b. DuckDuckGo (бесплатный fallback)

```
Функция: _ddgs_search(query, max_results=5)
Библиотека: ddgs (pip install ddgs)
Фильтрация по title: пропускаем новости, статьи, рейтинги, каталоги, форумы,
  колледжи, университеты, шаблонный нерелевантный контент
Возвращает: {results: [{title, url, content}]} — формат совместим с Tavily
```

### 6c. Извлечение компаний из результатов

```
Функция: _extract_companies_fast(search_results)
Метод: regex, без LLM, ~0.5 мс

Алгоритм:
  1. Для каждого result в results:
     - text = title + content[:600]
     - Паттерн 1: regex ищет ООО «Название» / ООО "Название"
     - Паттерн 2: regex ищет ООО Название (без кавычек, до пунктуации)
     - Юр. формы: ООО АО ПАО ЗАО НКО НПО НПП НПЦ ГУП МУП ФГУП ОАО ИП ГК
  2. Если юр. форм нет:
     - Берёт title только если URL указывает на официальный сайт компании
  3. Нормализация: strip юр.формы → strip кавычки → lowercase → compare
  4. Дедупликация в батче + глобально (existing_companies)

Лимит: 20 компаний из одного поискового ответа
```

### 6d. Проверка официального сайта

```
Функция: is_company_website_url(company_name, url, evidence_text)

Логика (OR-цепочка):
  1. Домен в BLOCKED_WEBSITE_DOMAINS → False (сразу)
  2. _domain_matches_company(name, url):
     - Токенизация: убрать ООО/АО → split на буквы → транслитерация в латиницу
     - Проверить: base_domain совпадает с joined_tokens, acronym, или любым токеном ≥4 символа
  3. Если домен — source-only (rusprofile, 2gis, nalog.ru и т.п.) → False
  4. Название компании встречается в evidence_text → True (мягкий матч)

Заблокированные домены (BLOCKED_WEBSITE_DOMAINS):
  rusprofile.ru, zachestnyibiznes.ru, checko.ru, list-org.com,
  sbis.ru, audit-it.ru, kartoteka.ru, nalog.ru, egrul.nalog.ru,
  hh.ru, habr.com, vc.ru, avito.ru, tiu.ru, pulscen.ru, all.biz,
  linkedin.com, vk.com, facebook.com, t.me, youtube.com, instagram.com,
  2gis.ru, maps.google.com, yandex.ru, wikipedia.org, ...
```

---

## 7. ФАЗА 3 — МНОГОПРОХОДНЫЙ ПОИСК ЛПР

```
Функция: _multi_pass_lpr_search(tavily, company, log_fn, requirements)
Возвращает: (director_name: str|None, combined_text: str)
Все проходы накапливают текст в combined_parts → joined как combined_text
```

### Pass 0 — ЕГРЮЛ API nalog.ru (без Tavily, ~1 сек)

```
URL: POST https://egrul.nalog.ru/ → GET /search-result/{token}
Протокол: получаем token → polling 3 попытки с паузой 0.3 сек
Поля ответа: i=ИНН, g=должность+ФИО директора, n=название, a=адрес, o=ОГРН
Даёт: inn, director, address, ogrn
Ограничения: captchaRequired=true → возвращаем None (graceful)
Если успешен: Pass 5 (ИНН через Tavily) и Pass 8 (директор по ИНН) пропускаются
```

### Pass 1 + Pass 3 — ПАРАЛЛЕЛЬНО (ThreadPoolExecutor(2))

```
Pass 1 и Pass 3 запускаются одновременно → экономия ~8 сек на компанию
```

### Pass 1 — Директор из ЕГРЮЛ-прокси

```
Запрос: "{company}" директор руководитель rusprofile.ru zachestnyibiznes.ru checko.ru list-org.com
max_results=6, text[:800]
Парсинг: regex _DIRECTOR_PATTERNS (14 паттернов):
  "Генеральный директор – ФИО" | "Директор: ФИО" | "Руководитель – ФИО"
  "ФИО руководителя: ФИО" | "ЕИО: ФИО" | "ФИО — Директор" (обратный)
  "ГД ФИО" | "Управляющий: ФИО" | "Председатель: ФИО"
ФИО валидация: ≥2 слова, кирилица, нет цифр
```

### Pass 1b — Резервный директор

```
Условие: директор не найден И нужны personal_email или mobile_phone
Запрос: "{company}" руководитель ФИО checko egrul реестр
max_results=4
```

### Pass 2 — Личный email директора (несколько вариантов)

```
Условие: директор найден И email ещё не найден
Запросы (последовательно, стоп при первом результате):
  1. "{director_name}" "{company}" email
  2. "{director_name}" @{domain}   (если домен известен)
  3. site:{domain} "{director_name}"
max_results=4 на каждый запрос
```

### Pass 3 — Контакты с сайта компании

```
Запрос (если домен известен): site:{domain} контакты email телефон
Запрос (если домен неизвестен): "{company}" контакты email телефон официальный
max_results=4, text[:600]
Запускается параллельно с Pass 1
```

### Pass 4 — Мобильный телефон директора

```
Условие: директор найден И телефон не найден
Запрос: "{company}" телефон мобильный директор контакты
max_results=3, text[:400]
```

### Pass 5 — ИНН компании

```
Условие: 'inn' in requirements И ИНН не получен из ЕГРЮЛ (Pass 0)
Запрос: "{company}" ИНН реквизиты
max_results=3, text[:500]
```

### Pass 6 — Общий email / телефон

```
Условие: нужен email ИЛИ phone ИЛИ generic_email ИЛИ generic_phone
Запрос (домен известен): site:{domain} реквизиты контакты email телефон
Запрос (домен неизвестен): "{company}" реквизиты контакты email телефон
max_results=3, text[:500]
```

### Pass 7 — 2ГИС: верифицированный офисный телефон

```
Условие: телефон не найден И нужен phone/mobile_phone/generic_phone
Запрос: "{company}" 2гис телефон адрес
max_results=3, text[:400]
Источник: 2gis.ru — наиболее полный справочник РФ
```

### Pass 8 — Директор по ИНН

```
Условие: директор не найден И нужен personal_email/mobile_phone И ИНН известен
Запрос: ИНН {inn} директор руководитель rusprofile checko egrul
max_results=4, text[:500]
Приоритет ИНН: ЕГРЮЛ Pass 0 → из combined_text (regex)
```

### Ранний выход

```
Если после Passes 1+3 уже есть: email + phone → Passes 4, 6, 7 пропускаются
```

---

## 8. ФАЗА 4 — ИЗВЛЕЧЕНИЕ КОНТАКТОВ

```
Функция: _extract_lpr_from_combined(client, company, combined_text, known_director)
```

### Fast path — regex (~0.5 мс, LLM не вызывается)

```
Условие запуска: regex нашёл ФИО + (email ИЛИ телефон)

Что извлекает:
  personal_emails: regex _EMAIL_RE → фильтр NOT is_generic_email()
  generic_emails:  regex _EMAIL_RE → фильтр is_generic_email()
  phones:          regex (\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}
  inn:             regex ИНН[\s:№]*(\d{10}|\d{12})
  director:        14 regex паттернов _DIRECTOR_PATTERNS

Приоритет:
  personal_email = первый найденный personal
  generic_email  = первый найденный generic
  mobile_phone   = первый phone начинающийся на 79.../89.../9...
  generic_phone  = первый не-мобильный phone
```

### Slow path — LLM (~4-6 сек)

```
Условие: regex дал неполный результат (нет email ИЛИ нет телефона)

LLM выбор:
  Если GROQ_API_KEY задан → Groq: llama-3.3-70b-versatile (приоритет)
  Иначе → Ollama: qwen2.5:1.5b (OLLAMA_BASE_URL + OLLAMA_MODEL)

Параметры: temperature=0.1, max_tokens=600, response_format=json_object
Prompt содержит:
  - Разделяй личный и общий контакт
  - Игнорируй банки, справочники, агрегаторы
  - Не придумывай — только из текста
  - Директор-подсказка если known_director задан

Приоритет ролей ЛПР (в prompt):
  Административный директор > Исполнительный директор >
  Зам. гендиректора > HR-директор > Технический директор >
  Финансовый директор > Генеральный директор

Выходной JSON:
  {person_name, title, personal_email, generic_email,
   mobile_phone, generic_phone, inn, source_url}

После LLM: regex-фолбэки для любых полей которые LLM не нашёл
```

---

## 9. ФАЗА 5 — ВАЛИДАЦИЯ И ФИЛЬТРАЦИЯ

### 9a. Дедупликация (ДО обработки)

```
При старте загружаем из БД:
  existing_companies: set → normalize_company_name(company_name)
  existing_emails:    set → email.lower()
  existing_inns:      set → digits-only INN, len ∈ {10, 12}

В процессе:
  searched_names: set → компании проверенные в ТЕКУЩЕМ запуске

Проверки (по порядку):
  1. normalize(name) in existing_companies → "⏭ уже в базе", пропуск
  2. normalize(name) in searched_names    → тихий пропуск
  3. (после LPR) clean_inn in existing_inns → "⏭ ИНН уже в базе", пропуск
  4. row_email in existing_emails         → "⏭ email уже в базе", пропуск
```

### 9b. Регион-фильтр (ЕГРЮЛ адрес)

```
Включается только если 'russia' НЕ в regions_list

Источник: строка "Адрес: {value}" из ЕГРЮЛ Pass 0 в combined_text
Токены совпадения:
  moscow: {'москва', 'москве', 'московск'}
  mo:     {'московская', 'московской', 'подмосковье'}

Поведение:
  - Адрес найден + не совпадает с регионом → пропуск компании
  - Адрес не найден → фильтр НЕ применяется (мягкий)
```

### 9c. Блокировка общих email (BLOCKED_EMAIL_PREFIXES, 70+ штук)

```
info, sales, office, support, mail, contact, zakaz, hello, admin,
reception, corp, marketing, pr, press, media, hr, career, post,
inbox, noreply, feedback, help, service, request, quality, tender,
zakupki, buh, director, general, business, welcome, client, customer,
personal, manager, tech, job, work, connect, team, news, events,
promo, dealer, partner, agent, torg, opt, price, order, secretary,
ceo, cto, cfo, coo, ask, send, contract, doc, document, ...

Алгоритм: local_part == prefix  OR  starts_with(prefix + [-_.digit])
```

### 9d. Блокировка бесплатных почтовых доменов

```
_FREEMAIL_DOMAINS: gmail.com, googlemail.com, mail.ru, bk.ru, inbox.ru,
  list.ru, internet.ru, yandex.ru, yandex.com, ya.ru, rambler.ru,
  hotmail.com, outlook.com, live.com, yahoo.com, icloud.com,
  protonmail.com, proton.me, tutanota.com, ukr.net, ...

Email на таком домене НЕ может быть корпоративным → отклоняется как personal_email
```

### 9e. Принадлежность email компании

```
Функция: email_belongs_to_company(email, company_name, website)
  1. domain ∈ _FREEMAIL_DOMAINS → False
  2. domain_base(email_domain) == domain_base(website_domain) → True
  3. _domain_matches_company(company_name, email_domain) → True/False
     (токенизация + транслитерация + acronym)
```

### 9f. Валидация по требованиям пользователя

```
Функция: contact_satisfies_requirements(contact, requirements)

company_name  → не пустое
website       → is_company_website_url() = True
personal_email → format valid + NOT generic + belongs_to_company
                 + ЛПР с ФИО ≥ 2 слов
generic_email  → format valid + IS generic + belongs_to_company
email         → хотя бы один из (personal_email | generic_email) валиден
mobile_phone   → digits начинается на 79 или 89 или 9, всего 11 или 10 цифр
generic_phone  → is_valid_phone() (≥7 цифр) + NOT mobile
phone         → хотя бы один из (mobile_phone | generic_phone) валиден
inn           → len(digits) ∈ {10, 12}
```

### 9g. MX-проверка email (мягкая)

```
Функция: _mx_ok(email) → bool
  Используется validate_email() из validator.py
  Кэширует по домену (_mx_domain_cache)
  True для 'valid' и 'unknown'

Поведение: ТОЛЬКО ПРЕДУПРЕЖДЕНИЕ в лог, сохранение не блокируется
Причина: многие корпоративные домены РФ не имеют MX-записей → давали
  ложные отрицания и блокировали сохранение всех контактов
```

---

## 10. ФАЗА 6 — СОХРАНЕНИЕ

### Правило multi-email (_build_contact_rows_for_save)

```
Выбраны personal_email И generic_email →
  2 строки в contacts (одна на каждый тип)
  Строка 1: email=personal, generic_email=NULL
  Строка 2: email=generic, personal_email=NULL
  Лимит: MAX_EMAILS_PER_COMPANY = 5 строк/компания

Выбран только один тип → 1 строка
```

### INSERT

```sql
INSERT OR IGNORE INTO contacts (
  company_name, website, person_name, title,
  email, personal_email, generic_email,
  phone, mobile_phone, generic_phone, inn,
  source_url, segment, region, date_found, status, run_id
) VALUES (?, ..., datetime('now', 'date'), 'new', ?)
```

`INSERT OR IGNORE` — UNIQUE(email) защищает от дублей на уровне БД.  
Запись видна в UI немедленно (коммит после каждой строки).

---

## 11. СХЕМА ДАННЫХ — таблица contacts

```
id             INTEGER PK AUTOINCREMENT
company_name   TEXT NOT NULL           — название компании
website        TEXT                    — официальный сайт (только собственный домен)
person_name    TEXT                    — ФИО директора/ЛПР (≥2 слова)
title          TEXT                    — должность (Генеральный директор и т.п.)
email          TEXT UNIQUE             — основной email (personal или generic)
personal_email TEXT                    — личный email ЛПР (i.ivanov@company.ru)
generic_email  TEXT                    — общий email (info@, sales@ и т.п.)
phone          TEXT                    — основной телефон
mobile_phone   TEXT                    — мобильный ЛПР (+7 9xx xxx xx xx)
generic_phone  TEXT                    — городской/офисный (+7 495 xxx xx xx)
inn            TEXT                    — ИНН (10 или 12 цифр)
source_url     TEXT                    — URL откуда найдена компания
segment        TEXT                    — метка сегмента ("Электроника и приборостроение")
region         TEXT                    — метка региона ("Москва")
date_found     TEXT                    — YYYY-MM-DD
status         TEXT DEFAULT 'new'      — new / sent / failed / unsubscribed
notes          TEXT
created_at     TEXT DEFAULT datetime() — ISO timestamp
run_id         INTEGER → research_runs.id
bounce_count   INTEGER DEFAULT 0       — счётчик отбивок (правило двух сигналов)
last_verified_at TEXT                  — дата последней верификации (email открыт/ответ)
freshness_score  REAL DEFAULT 1.0      — 1.0=новый, decay 25%/год, 0=>4 лет
```

---

## 12. ВНЕШНИЕ API И ЗАВИСИМОСТИ

```yaml
tavily:
  url: https://api.tavily.com/search
  auth: TAVILY_API_KEY (env, обязателен)
  timeout: 8 сек
  limits: ~1000 запросов/месяц (free tier)
  fallback: duckduckgo

groq:
  url: https://api.groq.com/openai/v1
  model: llama-3.3-70b-versatile
  auth: GROQ_API_KEY (env, опционален)
  limits: 14400 req/day, 6000 tokens/min (free)
  priority: 1 (если ключ задан)

ollama:
  url: OLLAMA_BASE_URL (default http://localhost:11434/v1)
  model: OLLAMA_MODEL (default qwen2.5:1.5b)
  priority: 2 (если Groq недоступен)
  note: qwen2.5:1.5b — 3.3 сек, валидный JSON
  ЗАПРЕЩЕНО: qwen3:4b — сжигает токены на thinking, возвращает пустую строку

egrul_nalog:
  url: https://egrul.nalog.ru/
  auth: нет
  data: ИНН, ОГРН, директор, адрес
  limits: captcha при частых запросах

rusprofile_scraper:
  url: https://www.rusprofile.ru/search
  auth: нет
  limits: 403/429 при >5-10 req/min

2gis_catalog:
  url: https://catalog.api.2gis.com/3.0/items
  auth: нет (публичный)
  limits: ~10-20 req/min

duckduckgo:
  library: ddgs (pip)
  auth: нет
  limits: rate limit при >5-10 concurrent requests
  используется как: основной fallback для Tavily

egrul_proxies (через Tavily/DDG поиск):
  rusprofile.ru       — директора по названию/ИНН
  zachestnyibiznes.ru — директора, ИНН
  checko.ru           — директора, ИНН
  list-org.com        — директора, ИНН
  2gis.ru             — телефоны офисов (Pass 7)
```

---

## 13. КЛЮЧЕВЫЕ ОГРАНИЧЕНИЯ (НЕЛЬЗЯ МЕНЯТЬ)

```
1. МОДЕЛЬ: qwen2.5:1.5b — qwen3:4b ЗАПРЕЩЕНА (мышление съедает токены)
2. ДЕДУПЛИКАЦИЯ: по company_name + email + INN — обязательна всегда
3. BLOCKED_EMAIL_PREFIXES: 70+ префиксов — personal email должен быть личным
4. САЙТ: только официальный домен, не rusprofile/hh/avito/соцсети
5. ЛПР: ФИО ≥ 2 слов для personal_email / mobile_phone
6. SMTP БАТЧ: max 30 адресов (ограничение Mail.ru)
7. SMTP_PASS: никогда не логируется, не попадает в HTML
8. SQL: только параметризованные запросы — НИКОГДА f-string в SQL
9. ПАРАЛЛЕЛЬНОСТЬ: max 2 потока внутри _multi_pass_lpr_search (Pass 1+3)
   Внешний цикл компаний — последовательно (иначе Tavily rate limit)
```

---

## 14. ПОТОК УПРАВЛЕНИЯ (псевдокод)

```python
def _research_worker(run_id, config):
    client = OpenAI(Groq|Ollama)
    tavily = TavilyClient(TAVILY_API_KEY)

    # Фаза 0: фоновый скрапинг (не блокирует старт)
    scrape_thread = Thread(target=_run_scraping, daemon=True)
    scrape_thread.start()

    # Загрузка существующих данных
    existing_companies, existing_emails, existing_inns = load_from_db()

    # Фаза 1: пул запросов
    all_queries = build_queries(segments, regions, scales, industries, requirements)

    # Фазы 2-6: основной цикл
    for query in all_queries:
        if found >= target: break
        search_res = tavily_search(query, max_results=10)
                     or ddgs_search(query, max_results=5)  # fallback
        companies = extract_companies(search_res)

        for company in filter_new(companies):
            if found >= target: break
            # Фаза 3
            director, text = _multi_pass_lpr_search(tavily, company)
            # Фаза 4
            lpr = regex_extract(text, director)
                  or llm_extract(client, text, director)  # slow path
            # Фаза 5
            if not contact_satisfies_requirements(lpr): continue
            if inn in existing_inns: continue
            if address_wrong_region(text): continue
            # Фаза 6
            rows = build_contact_rows(lpr)
            for row in rows:
                INSERT OR IGNORE INTO contacts ...
                found += 1

    # Обработка rusprofile/2GIS после основного цикла
    scrape_thread.join(timeout=30)
    for company in rusprofile_companies:
        # тот же пайплайн что выше
        _do_company(company)

    set_status(run_id, 'done', found_count=found)
```

---

## 15. СТРУКТУРА ФАЙЛОВ ПРОЕКТА

```
webapp/
├── researcher.py     — ВСЯ логика поиска (~2300 строк)
│   Ключевые функции:
│     start_research(config) → run_id
│     _research_worker(run_id, config)   — main daemon thread
│     _multi_pass_lpr_search(...)        — 8-проходный поиск ЛПР
│     _extract_lpr_from_combined(...)    — regex + LLM извлечение
│     _extract_companies_fast(...)       — regex дискавери компаний
│     _fetch_egrul_nalog(...)            — Pass 0: официальный ЕГРЮЛ
│     _scrape_rusprofile_okved(...)      — Rusprofile ОКВЭД скрапинг
│     _fetch_2gis_companies(...)         — 2GIS дискавери
│     contact_satisfies_requirements()  — валидация по требованиям
│     _build_contact_rows_for_save()    — multi-email правило
│
├── app.py            — Flask роуты
│   /research         — UI страница
│   /research/start   — POST: запустить поиск
│   /research/status  — GET: статус и лог текущего запуска
│   /research/pause   — POST: пауза
│   /research/resume  — POST: возобновить
│   /research/finish  — POST: завершить досрочно
│
├── database.py       — SQLite: schema, init_db, get_db
├── mailer.py         — SMTP, трекинг открытий/кликов, разбор отбивок
├── validator.py      — MX-валидация email через DNS
├── auth.py           — bcrypt login/logout
├── RESEARCH_RULES.md — Зафиксированные правила (что нельзя менять)
├── RESEARCH_MAP.md   — Этот файл (архитектура и логика)
└── data/contacts.db  — SQLite БД
```

---

## 16. ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ

```bash
# Обязательные
TAVILY_API_KEY=tvly-...          # поиск (без него — только DDG, медленно)
SECRET_KEY=...                    # Flask сессии

# LLM (хотя бы один)
GROQ_API_KEY=gsk_...             # приоритет: Groq llama-3.3-70b (бесплатно)
OLLAMA_BASE_URL=http://localhost:11434/v1  # fallback
OLLAMA_MODEL=qwen2.5:1.5b        # обязательно qwen2.5:1.5b, не qwen3

# SMTP (настраивается через UI /settings, хранится в sqlite)
# smtp_host, smtp_port, smtp_user, smtp_pass, from_name, from_email
```

---

*Актуально на 2026-06-02. При изменении researcher.py — обновить этот файл.*
