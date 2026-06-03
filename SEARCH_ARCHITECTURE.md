# RESEARCH MAP — Поисковая архитектура 10/10 без платных API

**Скорректированная версия 10/10 FREE:** добавлены benchmark protocol, human validation loop, parser health monitoring, anti-drift, deliverability feedback, source versioning и gold dataset. Все улучшения остаются в рамках бесплатных публичных источников, локальной обработки и собственной базы данных.

> Формат: машиночитаемый Markdown для AI-агентов и разработчиков.  
> Проект: ABCENTRUM Outreach Platform (`webapp/researcher.py`)  
> Цель: максимальная эффективность поиска компаний и контактов **без платных подписок и платных API**.  
> Принцип: бесплатные публичные источники + локальная обработка + кэш + скоринг + строгая валидация + измеримые метрики.  
> Дата актуальности: 2026-06-03  
> Ожидаемая архитектурная оценка после внедрения: **10/10 для бесплатного production-grade lead discovery**.

---

## 0. КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ОТНОСИТЕЛЬНО СТАРОЙ ВЕРСИИ

Старая схема была сильной, но держалась на Tavily/Groq и не имела полноценного confidence scoring, field attribution, очередей, кэша, backoff и измеримых метрик качества.

Новая схема:

1. Полностью убирает обязательные платные API.
2. Делает систему **offline-first / free-first**.
3. Использует только:
   - локальную БД SQLite;
   - локальный LLM через Ollama;
   - DuckDuckGo/HTML search fallback;
   - публичные HTML-источники;
   - официальный ЕГРЮЛ `egrul.nalog.ru`;
   - публичные страницы сайтов компаний;
   - публичные каталоги и агрегаторы только как discovery/evidence, а не как финальный сайт.
4. Вводит единый `EvidenceStore` — каждое найденное поле хранится с источником, временем, доверием и причиной принятия/отклонения.
5. Вводит `LeadScore` и `FieldConfidence` — система больше не сохраняет контакт просто потому, что regex что-то нашёл.
6. Добавляет retry/backoff/rate-limit менеджер для каждого источника.
7. Добавляет кэш запросов, HTML, DNS/MX, результатов ЕГРЮЛ и нормализации компаний.
8. Добавляет метрики эффективности и отчёт по причинам отказа.
9. Добавляет безопасный режим: не нарушать robots.txt, не долбить источники, не использовать платные сервисы, не обходить капчу.

---

## 1. ЦЕЛЕВАЯ ОЦЕНКА 10/10 — КРИТЕРИИ

Система считается архитектурно эффективной на 10/10, если выполняет следующие условия:

| Критерий | Требование |
|---|---|
| Бесплатность | Работает без Tavily, Groq, платных enrichment/API и подписок |
| Recall компаний | Находит компании минимум из 5 независимых бесплатных каналов |
| Precision компаний | Отбрасывает агрегаторы, вакансии, новости, маркетплейсы и нерелевантные страницы |
| Контакты | Разделяет corporate/generic/personal/mobile/office phone |
| Доверие | Каждое поле имеет confidence score и source attribution |
| Валидация | Сохраняются только контакты, прошедшие требования пользователя и quality gate |
| Устойчивость | Есть retry, backoff, per-domain rate limit, graceful degradation |
| Скорость | Есть кэш и приоритизация кандидатов до дорогого LPR-поиска |
| Масштабируемость | Есть очередь задач, статусы, дедупликация и возобновление после сбоя |
| Измеримость | Есть метрики: найдено, отклонено, почему отклонено, качество по источникам |
| Проверяемость качества | Есть benchmark protocol, gold dataset и ручная контрольная выборка |
| Анти-дрифт источников | Есть parser health checks, source versioning и fallback extractors |
| Feedback loop | Bounce/reply/manual feedback влияет на scoring без платных API |

---

## 2. ОБЗОР СИСТЕМЫ

```text
Пользователь (UI Research)
  → Фильтры: сегмент, регион, масштаб, отрасль, требования к контакту, count, keywords
  → start_research(config) [app.py]
  → _research_worker(run_id, config) [researcher.py]
      ├── ФАЗА 0: Подготовка окружения
      │     ├── проверка бесплатного режима
      │     ├── загрузка кэшей и существующей БД
      │     ├── инициализация RateLimitManager
      │     └── инициализация EvidenceStore
      │
      ├── ФАЗА 1: Построение расширенного пула запросов
      │     ├── сегментные запросы
      │     ├── ОКВЭД-запросы
      │     ├── отраслевые запросы
      │     ├── discovery-запросы по каталогам
      │     ├── site-запросы
      │     └── negative keywords
      │
      ├── ФАЗА 2: Бесплатный discovery компаний
      │     ├── DuckDuckGo HTML / ddgs
      │     ├── search-engine HTML fallback
      │     ├── Rusprofile/checko/list-org/zachestnyibiznes discovery
      │     ├── 2GIS публичные страницы / публичный catalog endpoint, если доступен
      │     ├── ЕГРЮЛ nalog по названию/ОКВЭД
      │     └── сайты технопарков, кластеров, реестров и выставок
      │
      ├── ФАЗА 3: Нормализация и первичный скоринг компаний
      │     ├── canonical company name
      │     ├── dedupe by normalized name + INN + domain
      │     ├── region pre-check
      │     ├── segment relevance score
      │     └── candidate priority queue
      │
      ├── ФАЗА 4: Бесплатный многопроходный поиск данных компании
      │     ├── Pass 0: ЕГРЮЛ nalog.ru
      │     ├── Pass 1: официальный сайт
      │     ├── Pass 2: страницы /contacts /company /about /requisites
      │     ├── Pass 3: реквизиты, ИНН, ОГРН, адрес
      │     ├── Pass 4: директор/ЛПР из ЕГРЮЛ и агрегаторов
      │     ├── Pass 5: email/phone с официального домена
      │     ├── Pass 6: 2GIS/карты/каталоги для телефонов
      │     ├── Pass 7: локальный LLM только для структурирования уже найденного текста
      │     └── Pass 8: финальная проверка принадлежности полей компании
      │
      ├── ФАЗА 5: Evidence scoring и field attribution
      │     ├── confidence per field
      │     ├── source reliability
      │     ├── cross-source agreement
      │     ├── freshness
      │     └── reject reasons
      │
      ├── ФАЗА 6: Валидация требований пользователя
      │     ├── contact_satisfies_requirements()
      │     ├── quality gate
      │     ├── MX soft check
      │     ├── duplicate checks
      │     └── compliance checks
      │
      ├── ФАЗА 7: Сохранение
      │     ├── contacts
      │     ├── contact_evidence
      │     ├── research_metrics
      │     └── rejected_candidates
      │
      ├── ФАЗА 8: Отчёт качества
      │     ├── найдено / сохранено / отклонено
      │     ├── причины отклонения
      │     ├── эффективность источников
      │     ├── средний confidence
      │     └── рекомендации для следующего запуска
      │
      └── ФАЗА 9: Самопроверка качества без платных API
            ├── benchmark на gold dataset
            ├── human validation sample
            ├── parser health report
            ├── source drift detection
            ├── bounce/reply feedback import
            └── auto-tuning весов scoring
```

---

## 3. БЕСПЛАТНЫЙ РЕЖИМ — ЖЁСТКОЕ ПРАВИЛО

```yaml
paid_api_policy:
  tavily: disabled
  groq: disabled
  apollo: forbidden
  clearbit: forbidden
  zoominfo: forbidden
  hunter: forbidden
  snov: forbidden
  any_paid_enrichment_api: forbidden

allowed_free_sources:
  - egrul.nalog.ru
  - official_company_websites
  - duckduckgo_html_or_ddgs
  - rusprofile_html_discovery
  - checko_html_discovery
  - list_org_html_discovery
  - zachestnyibiznes_html_discovery
  - 2gis_public_pages_or_public_endpoint_if_available
  - technopark_cluster_exhibition_pages
  - public_government_registers
  - company_pdf_pages
  - official_sitemap_xml
  - public_rss_or_news_pages_of_company
  - local_gold_dataset
  - local_manual_validation_queue
  - local_bounce_feedback_from_own_campaigns
  - local_sqlite_cache
  - local_ollama_llm

local_llm_policy:
  primary: ollama
  recommended_models:
    - qwen2.5:1.5b
    - qwen2.5:3b
    - llama3.2:3b
  prohibited:
    - remote_paid_llm
    - qwen3_thinking_models_for_extraction
  rule: LLM only structures text already collected; it must not invent data.
```

Если бесплатный источник недоступен, система не переключается на платный API. Она снижает coverage, пишет причину в `research_metrics` и продолжает работу.

---

## 4. ВХОДНЫЕ ПАРАМЕТРЫ `config`

| Поле | Тип | Допустимые значения | По умолчанию |
|---|---|---|---|
| `segments` | list[str] | electronics, medtech, robotics, it_hardware, laser_optics, rd_nii, light_industrial | ['electronics'] |
| `regions` | list[str] | moscow, mo, russia | ['moscow'] |
| `company_scales` | list[str] | any, small, medium, large | ['any'] |
| `industries` | list[str] | construction, transport, media, it_telecom, finance, healthcare, education, culture, government, associations, trade, services, production | [] |
| `contact_requirements` | list[str] | company_name, website, email, generic_email, personal_email, phone, generic_phone, mobile_phone, inn | ['email'] |
| `count` | int | целевое число контактов | 10 |
| `keywords` | str | дополнительные ключевые слова | '' |
| `quality_threshold` | float | 0.0–1.0 | 0.72 |
| `min_field_confidence` | float | 0.0–1.0 | 0.65 |
| `free_only` | bool | always true | true |
| `respect_robots_txt` | bool | true/false | true |
| `max_pages_per_domain` | int | 1–20 | 5 |
| `max_candidates_multiplier` | int | 3–20 | 8 |
| `use_local_llm` | bool | true/false | true |
| `save_rejected` | bool | true/false | true |
| `benchmark_mode` | bool | true/false | false |
| `gold_dataset_path` | str | локальный CSV/JSONL | data/gold_leads.csv |
| `human_validation_sample_rate` | float | 0.0–1.0 | 0.10 |
| `parser_health_check` | bool | true/false | true |
| `source_drift_threshold` | float | 0.0–1.0 | 0.35 |
| `auto_tune_scoring_weights` | bool | true/false | true |

---

## 5. СЕГМЕНТЫ И ОКВЭД

```yaml
electronics:
  label: "Электроника и приборостроение"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.51, 26.52, 26.11, 26.12, 26.20]
  query_intents: [оквэд, производство, нпп, приборы, измерительное оборудование, компоненты]

medtech:
  label: "Медтех и фармацевтика"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.60, 32.50, 21.20, 21.10]
  query_intents: [медицинское оборудование, медизделия, производство, регистрационное удостоверение]

robotics:
  label: "Робототехника и автоматизация"
  vri: "ВРИ 6.3, 6.3.3"
  okved_codes: [28.41, 28.99, 28.12, 28.11]
  query_intents: [робототехника, автоматизация, станки, промышленные роботы, интегратор]

it_hardware:
  label: "IT-производство и hardware"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.20, 26.30, 26.12]
  query_intents: [серверы, телеком оборудование, платы, электроника, hardware]

laser_optics:
  label: "Лазерные и оптические технологии"
  vri: "ВРИ 6.3.1"
  okved_codes: [26.70, 27.40]
  query_intents: [лазеры, оптика, фотоника, светотехника, оптические приборы]

rd_nii:
  label: "R&D и научная деятельность"
  vri: "ВРИ 6.12"
  okved_codes: [72.19, 72.11, 72.20]
  query_intents: [НИИ, НИОКР, лаборатория, разработка, инженерный центр]

light_industrial:
  label: "Прочее light industrial"
  vri: "ВРИ 6.3.2"
  okved_codes: [33.12, 27.11, 28.21, 27.90]
  query_intents: [оборудование, производство, сервис, ремонт, электромеханика]
```

---

## 6. НОВАЯ МОДЕЛЬ ДАННЫХ: EVIDENCE-FIRST

Главное изменение: контакт не является просто строкой. Он является результатом набора доказательств.

### 6.1. `CandidateCompany`

```python
@dataclass
class CandidateCompany:
    raw_name: str
    normalized_name: str
    legal_form: str | None
    inn: str | None
    ogrn: str | None
    website: str | None
    region: str | None
    address: str | None
    segment: str
    discovery_sources: list[str]
    discovery_score: float
    priority_score: float
    status: Literal['new', 'queued', 'processing', 'accepted', 'rejected', 'duplicate']
```

### 6.2. `EvidenceItem`

```python
@dataclass
class EvidenceItem:
    run_id: int
    company_key: str
    field_name: str       # website, inn, director, email, phone, address, source_url
    value: str
    source_url: str
    source_type: str      # official_site, egrul, 2gis, aggregator, search_snippet, pdf
    extraction_method: str # regex, html_parser, local_llm, egrul_json, manual_rule
    confidence: float
    reliability: float
    freshness_score: float
    collected_at: str
    accepted: bool
    reject_reason: str | None
    evidence_text_hash: str
```

### 6.3. `FieldConfidence`

```python
@dataclass
class FieldConfidence:
    value: str
    field_name: str
    confidence: float
    reasons: list[str]
    sources: list[str]
    conflicts: list[str]
```

### 6.4. `LeadScore`

```python
@dataclass
class LeadScore:
    total: float
    company_identity: float
    website_quality: float
    contact_quality: float
    lpr_quality: float
    region_match: float
    segment_match: float
    source_agreement: float
    freshness: float
    completeness: float
    penalties: list[str]
```

---

## 7. БЕСПЛАТНЫЕ ИСТОЧНИКИ И ИХ РОЛИ

| Источник | Роль | Можно сохранять как официальный сайт? | Надёжность |
|---|---|---:|---:|
| `egrul.nalog.ru` | ИНН, ОГРН, директор, адрес | Нет | 0.95 |
| Официальный сайт компании | email, phone, реквизиты, адрес, ЛПР | Да | 0.90 |
| PDF с официального сайта | реквизиты, договоры, карточка компании | Да | 0.88 |
| 2GIS публичные страницы | телефон, адрес, сайт | Нет, но сайт можно извлечь | 0.75 |
| Rusprofile | discovery, ИНН, директор | Нет | 0.72 |
| Checko | discovery, ИНН, директор | Нет | 0.72 |
| List-org | discovery, ИНН, директор | Нет | 0.65 |
| Zachestnyibiznes | discovery, ИНН, директор | Нет | 0.65 |
| Технопарки/кластеры | discovery и сегментная релевантность | Иногда | 0.70 |
| Выставки/ассоциации | discovery и сегментная релевантность | Иногда | 0.60 |
| Search snippets | discovery only | Нет | 0.45 |

Правило: агрегатор может подтвердить компанию, ИНН или директора, но **не должен становиться финальным сайтом компании**.

---

## 8. ФАЗА 0 — ПОДГОТОВКА ОКРУЖЕНИЯ

```python
def prepare_research_environment(config):
    assert config.get('free_only', True) is True

    disable_paid_clients()        # Tavily/Groq/Apollo/Hunter/etc.
    init_sqlite()
    init_http_cache()
    init_dns_cache()
    init_egrul_cache()
    init_robots_cache()
    init_rate_limit_manager()
    init_evidence_store()
    init_metrics_collector()
    init_local_llm_if_available()

    existing = load_existing_company_email_inn_domain_keys()
    return ResearchContext(config=config, existing=existing)
```

### 8.1. Запрещённые зависимости

```python
FORBIDDEN_ENV_KEYS = {
    'TAVILY_API_KEY',
    'GROQ_API_KEY',
    'APOLLO_API_KEY',
    'HUNTER_API_KEY',
    'CLEARBIT_API_KEY',
    'ZOOMINFO_API_KEY',
}
```

Наличие этих ключей не должно включать использование платных сервисов. В бесплатном режиме они игнорируются.

---

## 9. ФАЗА 1 — ПОСТРОЕНИЕ ПУЛА ЗАПРОСОВ

### 9.1. Структура запроса

```python
full_query = compact_join([
    segment_core_query,
    okved_term,
    industry_suffix,
    contact_requirement_suffix,
    region_label,
    scale_suffix,
    keywords,
    negative_hint,
], max_len=180)
```

### 9.2. Типы запросов

```yaml
query_types:
  okved:
    examples:
      - 'ОКВЭД 26.51 производство Москва'
      - '26.51 приборостроение ООО Москва ИНН'

  official_site:
    examples:
      - 'производство измерительных приборов Москва официальный сайт контакты'
      - 'НПП электроника Москва реквизиты email'

  aggregator_discovery:
    examples:
      - 'site:rusprofile.ru ОКВЭД 26.51 Москва ООО'
      - 'site:checko.ru производство медицинского оборудования Москва'
      - 'site:list-org.com робототехника Москва ООО'

  cluster_discovery:
    examples:
      - 'резидент технопарк электроника Москва производство'
      - 'кластер фотоника Москва компании контакты'
      - 'выставка робототехника участники Москва производитель'

  requisites:
    examples:
      - 'карточка предприятия ИНН email телефон производство Москва'
      - 'реквизиты ООО приборостроение Москва email'
```

### 9.3. Negative keywords

Добавлять в поисковую логику и фильтрацию:

```text
-вакансии -работа -резюме -новости -статья -форум -реферат -маркетплейс
-авито -hh -youtube -telegram -вконтакте -instagram -facebook -wikipedia
```

---

## 10. ФАЗА 2 — БЕСПЛАТНЫЙ DISCOVERY КОМПАНИЙ

### 10.1. FreeSearchProvider

```python
class FreeSearchProvider:
    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        providers = [
            self.ddgs_search,
            self.duckduckgo_html_search,
            self.search_engine_html_fallback,
            self.local_cache_search,
        ]
        for provider in providers:
            results = provider(query, max_results=max_results)
            if results:
                return results
        return []
```

### 10.2. Правила бесплатного поиска

```yaml
search_rules:
  max_concurrent_searches: 1
  delay_between_searches_sec: [2.0, 5.0]
  retry_count: 2
  exponential_backoff: true
  cache_ttl_days: 14
  respect_robots_txt: true
  user_agent: 'ABCENTRUMResearchBot/1.0 contact:admin'
```

### 10.3. Извлечение компаний

```python
def extract_companies_from_results(results):
    candidates = []
    for result in results:
        text = normalize_text(result.title + ' ' + result.snippet)
        candidates += extract_legal_entities(text)
        candidates += extract_title_as_company_if_official_domain(result)
        candidates += extract_company_from_aggregator_url(result.url, text)
    return dedupe_candidates(candidates)
```

### 10.4. Фильтр мусора

Отклонять результат discovery, если title/url/snippet содержит:

```text
вакансии, работа, отзывы сотрудников, новости, статья, рейтинг, топ-10,
маркетплейс, купить, цена, авито, hh.ru, youtube, vk.com, telegram,
курсовая, реферат, презентация, каталог товаров без юрлица
```

---

## 11. ФАЗА 3 — НОРМАЛИЗАЦИЯ И ПРИОРИТИЗАЦИЯ КОМПАНИЙ

### 11.1. Нормализация имени

```python
def normalize_company_name(name):
    name = name.lower()
    name = remove_legal_forms(name)       # ООО, АО, ПАО, НПП, НПО и т.д.
    name = normalize_quotes_spaces(name)
    name = remove_city_suffixes(name)
    name = remove_stopwords(name)
    return name.strip()
```

### 11.2. Company identity key

```python
company_keys = {
    'name_key': normalize_company_name(name),
    'inn_key': digits_only(inn),
    'domain_key': registered_domain(website),
}
```

Дубликат определяется по любому сильному ключу:

```text
INN match → duplicate
same official domain → duplicate
same normalized_name + same region → duplicate
same normalized_name + same director + similar address → duplicate
```

### 11.3. Priority score до дорогого поиска

```python
priority_score = (
    0.25 * discovery_source_score +
    0.25 * segment_match_score +
    0.20 * region_hint_score +
    0.15 * official_site_hint_score +
    0.10 * okved_hint_score +
    0.05 * freshness_score
)
```

Компании с `priority_score < 0.45` не идут в полный LPR-поиск, если уже есть достаточно кандидатов.

---

## 12. ФАЗА 4 — МНОГОПРОХОДНЫЙ БЕСПЛАТНЫЙ ПОИСК КОНТАКТОВ

```python
def enrich_company_free(candidate):
    evidence = []

    evidence += pass_0_egrul(candidate)
    evidence += pass_1_find_official_site(candidate)
    evidence += pass_2_crawl_official_site(candidate)
    evidence += pass_3_extract_requisites(candidate)
    evidence += pass_4_find_director(candidate)
    evidence += pass_5_extract_contacts(candidate)
    evidence += pass_6_external_phone_validation(candidate)
    evidence += pass_7_local_llm_structure(evidence)
    evidence += pass_8_final_cross_check(evidence)

    return build_contact_from_evidence(evidence)
```

### Pass 0 — ЕГРЮЛ `nalog.ru`

```yaml
purpose: официальный ИНН, ОГРН, директор, адрес
cost: free
rate_limit: strict
cache_ttl_days: 90
captcha_policy: do_not_bypass
```

Если `captchaRequired=true`, записать `source_blocked_captcha` и продолжить без обхода.

### Pass 1 — Поиск официального сайта

Источники:

1. Сайт из 2GIS, если найден.
2. Сайт из агрегаторов, если домен не агрегатор.
3. Search result, если домен похож на название компании.
4. Страница компании в технопарке/ассоциации, если содержит ссылку на сайт.

```python
website_confidence = max([
    domain_matches_company(name, url) * 0.35,
    site_contains_company_name(html) * 0.25,
    site_contains_inn(html, inn) * 0.30,
    site_has_contacts_or_requisites(html) * 0.10,
])
```

Сайт принимается только если `website_confidence >= 0.70`.

### Pass 2 — Crawl официального сайта

Обходить только безопасные публичные страницы:

```text
/
/contacts
/contact
/kontakty
/requisites
/rekvizity
/about
/company
/o-kompanii
/documents
/svedeniya
```

Ограничения:

```yaml
max_pages_per_domain: 5
max_html_size_mb: 2
max_pdf_size_mb: 8
timeout_sec: 10
respect_robots_txt: true
```

### Pass 3 — Реквизиты и документы

Извлекать:

```text
ИНН, ОГРН, КПП, юридический адрес, фактический адрес,
email, phone, director, генеральный директор, руководитель
```

Поддерживать HTML и PDF. PDF парсить через локальные библиотеки, без OCR по умолчанию. OCR включать только если пользователь явно разрешил и это локальный OCR.

### Pass 4 — Директор / ЛПР

Приоритет источников:

1. ЕГРЮЛ `nalog.ru`.
2. Официальный сайт, страница руководства/команды.
3. Реквизиты PDF с официального сайта.
4. Rusprofile/checko/list-org как подтверждение.
5. Search snippets только как слабое доказательство.

Директор принимается, если:

```text
ФИО ≥ 2 слов
кириллица или валидная латиница
нет цифр
роль содержит директор/руководитель/генеральный/исполнительный/коммерческий/технический
confidence >= 0.70
```

### Pass 5 — Email и телефоны

Email классифицировать:

```yaml
personal_email:
  examples: i.ivanov@company.ru, ivanov@company.ru, sergey.ivanov@company.ru
  required:
    - not generic
    - not freemail
    - belongs_to_company_domain
    - has_lpr_name_or_person_pattern

generic_email:
  examples: info@company.ru, sales@company.ru, office@company.ru
  required:
    - generic prefix
    - not freemail
    - belongs_to_company_domain

rejected_email:
  examples:
    - gmail/yandex/mail.ru as corporate
    - unrelated domain
    - bank/registrar/hosting/aggregator email
    - malformed
```

Телефоны классифицировать:

```yaml
mobile_phone:
  rule: Russian mobile, +7/8/7 + 9xx, total 10/11 digits
  personal_requirement: needs LPR context nearby or high-confidence source

generic_phone:
  rule: valid phone, not mobile, office/contact context
```

### Pass 6 — Внешняя телефонная проверка

2GIS/каталоги используются только для подтверждения телефонов и адреса.

```python
phone_confidence += 0.15 if same_phone_found_on_2gis
phone_confidence += 0.10 if same_address_found_on_2gis
phone_confidence -= 0.25 if phone_only_found_on_aggregator_without_company_match
```

### Pass 7 — Локальный LLM

LLM не ищет данные. Он только структурирует текст, уже собранный системой.

```yaml
llm_provider: ollama
model_priority:
  - qwen2.5:1.5b
  - qwen2.5:3b
  - llama3.2:3b
max_tokens: 700
temperature: 0.0
json_only: true
```

Prompt должен содержать:

```text
Ты извлекаешь только факты из предоставленного текста.
Нельзя придумывать.
Нельзя переносить контакты другой компании.
Каждое поле верни с confidence и цитатой/фрагментом evidence.
Если данных нет — null.
```

### Pass 8 — Финальная cross-check проверка

```python
def final_cross_check(contact, evidence):
    reject_if_email_domain_not_company(contact)
    reject_if_website_is_aggregator(contact)
    reject_if_inn_conflicts(contact)
    reject_if_director_conflicts_without_strong_source(contact)
    reject_if_region_conflicts(contact)
    reject_if_low_confidence(contact)
    return contact
```

---

## 13. CONFIDENCE SCORING

### 13.1. Source reliability

```python
SOURCE_RELIABILITY = {
    'egrul_nalog': 0.95,
    'official_site_html': 0.90,
    'official_site_pdf': 0.88,
    '2gis': 0.75,
    'rusprofile': 0.72,
    'checko': 0.72,
    'list_org': 0.65,
    'zachestnyibiznes': 0.65,
    'technopark': 0.70,
    'association': 0.65,
    'search_snippet': 0.45,
    'local_llm_extraction': 0.00, # LLM не источник, только метод обработки
}
```

### 13.2. Field confidence formula

```python
field_confidence = clamp(
    0.40 * source_reliability +
    0.25 * extraction_quality +
    0.15 * company_match +
    0.10 * cross_source_agreement +
    0.05 * freshness_score +
    0.05 * format_validity -
    penalties,
    0.0,
    1.0,
)
```

### 13.3. Lead score formula

```python
lead_score = clamp(
    0.18 * company_identity_score +
    0.14 * website_score +
    0.18 * email_score +
    0.12 * phone_score +
    0.12 * lpr_score +
    0.10 * inn_score +
    0.08 * region_score +
    0.05 * source_agreement_score +
    0.03 * freshness_score -
    penalties,
    0.0,
    1.0,
)
```

### 13.4. Quality gates

```yaml
save_thresholds:
  default_lead_score: 0.72
  strict_personal_email: 0.82
  generic_email_only: 0.70
  phone_only: 0.76
  inn_required: 0.80
  website_required: 0.75

field_thresholds:
  website: 0.70
  inn: 0.85
  director: 0.70
  personal_email: 0.82
  generic_email: 0.70
  mobile_phone: 0.78
  generic_phone: 0.68
```

### 13.5. Бесплатный auto-tuning весов scoring

Система может подстраивать веса без платных API только на основании локальных фактов:

```yaml
free_feedback_sources:
  - manual_validation_result
  - bounce_count_from_own_campaigns
  - positive_reply_detected_in_own_mailbox_if_user_enabled
  - repeated_cross_source_match
  - parser_health_status
  - source_error_rate

weight_update_rules:
  - if source precision on validation sample < 0.70: reduce source_reliability by 0.05
  - if source precision on validation sample > 0.90 and sample_size >= 30: increase source_reliability by 0.03
  - if email bounces twice: set email_confidence <= 0.20 and add to suppression list
  - if parser drift detected: freeze source score and route to fallback extractor
  - never increase confidence from LLM output alone
```

Важно: auto-tuning не должен делать платные запросы. Он учится только на локальных результатах, ручной проверке и фактах собственных кампаний.

---

## 14. VALIDATION RULES

### 14.1. Email validation

```python
def validate_email_field(email, company_name, website, lpr_name, requirement):
    if not valid_email_format(email): return reject('invalid_format')
    if domain(email) in FREEMAIL_DOMAINS: return reject('freemail_not_corporate')
    if domain(email) in BLOCKED_WEBSITE_DOMAINS: return reject('aggregator_email')
    if not email_belongs_to_company(email, company_name, website): return reject('email_domain_mismatch')

    if requirement == 'personal_email':
        if is_generic_email(email): return reject('generic_but_personal_required')
        if not lpr_name or len(lpr_name.split()) < 2: return reject('no_lpr_for_personal_email')
        if not email_matches_person_pattern(email, lpr_name): add_penalty('weak_personal_pattern')

    if requirement == 'generic_email':
        if not is_generic_email(email): add_note('non_generic_email_used_as_email')

    return accept()
```

### 14.2. Website validation

```python
def validate_official_website(url, company_name, inn, evidence_html):
    if domain(url) in BLOCKED_WEBSITE_DOMAINS: return False
    if is_social_or_marketplace(url): return False
    if domain_matches_company(company_name, url): return True
    if inn and inn in evidence_html: return True
    if company_name_appears_in_title_or_contacts(company_name, evidence_html): return True
    return False
```

### 14.3. Region validation

```python
region_confidence = max([
    egrul_address_region_match,
    official_site_address_region_match,
    phone_area_code_region_hint,
    2gis_region_match,
])
```

Если регион обязателен и `region_confidence < 0.60`, кандидат отклоняется или помечается как `region_uncertain`.

### 14.4. Deliverability без платных API

```python
def validate_email_deliverability_free(email, ctx):
    if not valid_email_format(email): return reject('email_invalid_format')
    if is_disposable_domain(email): return reject('email_disposable_domain')
    if is_role_account(email): add_note('role_account')
    mx = cached_mx_lookup(domain(email))
    if not mx.exists: return reject('email_no_mx')
    if domain(email) in ctx.suppression_domains: return reject('suppressed_domain')
    if email in ctx.suppression_emails: return reject('suppressed_email')
    # Не делать агрессивный SMTP-probing. Основной feedback — bounce/reply из собственных кампаний.
    return accept('mx_soft_valid')
```

### 14.5. Анти-перенос контактов другой компании

```python
def reject_cross_company_contact(field, candidate, evidence):
    if evidence.page_contains_multiple_companies and not evidence.local_context_matches(candidate):
        return reject('ambiguous_multi_company_page')
    if email_domain_belongs_to_other_known_company(field.email, candidate):
        return reject('contact_belongs_to_other_company')
    if phone_appears_under_other_company_block(field.phone, evidence.html_blocks):
        return reject('phone_context_mismatch')
    return accept()
```

---

## 15. RATE LIMIT, BACKOFF И УСТОЙЧИВОСТЬ

### 15.1. Per-domain limiter

```python
DOMAIN_LIMITS = {
    'egrul.nalog.ru': {'rpm': 6, 'burst': 1, 'cooldown_on_429_sec': 300},
    'rusprofile.ru': {'rpm': 4, 'burst': 1, 'cooldown_on_403_sec': 900},
    'checko.ru': {'rpm': 5, 'burst': 1, 'cooldown_on_403_sec': 900},
    'list-org.com': {'rpm': 4, 'burst': 1, 'cooldown_on_403_sec': 900},
    '2gis.ru': {'rpm': 6, 'burst': 1, 'cooldown_on_429_sec': 600},
    'default': {'rpm': 10, 'burst': 2, 'cooldown_on_429_sec': 300},
}
```

### 15.2. Retry policy

```yaml
retry_policy:
  network_timeout: retry 2 times with exponential backoff
  http_429: cooldown domain and skip temporarily
  http_403: mark source temporarily unavailable
  captcha: do not bypass; mark captcha_required
  invalid_html: save diagnostic and continue
```

### 15.3. Graceful degradation

Если источник недоступен:

```text
source unavailable → write metric → reduce source score → continue with other sources
```

### 15.4. Parser health и anti-drift

Каждый HTML/PDF extractor имеет версию, snapshot-тест и health score.

```yaml
parser_health:
  check_frequency: every_run_or_daily
  drift_signals:
    - required_selector_missing
    - extracted_fields_drop_more_than_35_percent
    - html_hash_changed_with_empty_output
    - captcha_or_js_gate_detected
    - repeated_invalid_html
  actions:
    - mark_source_degraded
    - route_to_fallback_extractor
    - reduce_source_reliability_temporarily
    - write_parser_health_event
    - do_not_save_low_confidence_fields
```

```python
def parser_health_guard(source, parser_version, html, extracted):
    drift_score = estimate_drift(source, html, extracted)
    if drift_score >= ctx.config.source_drift_threshold:
        record_parser_health(source, parser_version, 'degraded', drift_score)
        return fallback_extract_with_readability_or_regex(html)
    return extracted
```

---

## 16. КЭШИРОВАНИЕ

### 16.1. Таблица `http_cache`

```sql
CREATE TABLE IF NOT EXISTS http_cache (
  cache_key TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  domain TEXT,
  status_code INTEGER,
  response_text TEXT,
  response_hash TEXT,
  fetched_at TEXT,
  expires_at TEXT,
  source_type TEXT,
  error TEXT
);
```

### 16.2. TTL

```yaml
cache_ttl:
  search_results: 14 days
  egrul: 90 days
  official_site_html: 30 days
  official_site_pdf: 60 days
  aggregator_pages: 30 days
  dns_mx: 30 days
  robots_txt: 7 days
```

### 16.3. Кэш-правило

```python
if cached and not expired:
    use_cached_response()
else:
    fetch_with_rate_limit()
    save_cache()
```

---

## 17. БАЗА ДАННЫХ

### 17.1. `contacts`

```sql
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_name TEXT NOT NULL,
  normalized_company_name TEXT,
  website TEXT,
  website_confidence REAL,
  person_name TEXT,
  title TEXT,
  lpr_confidence REAL,
  email TEXT UNIQUE,
  personal_email TEXT,
  generic_email TEXT,
  email_confidence REAL,
  phone TEXT,
  mobile_phone TEXT,
  generic_phone TEXT,
  phone_confidence REAL,
  inn TEXT,
  ogrn TEXT,
  address TEXT,
  region TEXT,
  segment TEXT,
  lead_score REAL,
  source_url TEXT,
  source_summary TEXT,
  date_found TEXT,
  status TEXT DEFAULT 'new',
  notes TEXT,
  run_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  bounce_count INTEGER DEFAULT 0,
  last_verified_at TEXT,
  freshness_score REAL DEFAULT 1.0
);
```

### 17.2. `contact_evidence`

```sql
CREATE TABLE IF NOT EXISTS contact_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id INTEGER,
  run_id INTEGER,
  company_key TEXT,
  field_name TEXT,
  field_value TEXT,
  source_url TEXT,
  source_type TEXT,
  extraction_method TEXT,
  confidence REAL,
  reliability REAL,
  accepted INTEGER,
  reject_reason TEXT,
  evidence_snippet TEXT,
  evidence_hash TEXT,
  collected_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.3. `rejected_candidates`

```sql
CREATE TABLE IF NOT EXISTS rejected_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  company_name TEXT,
  normalized_company_name TEXT,
  inn TEXT,
  website TEXT,
  reason TEXT,
  lead_score REAL,
  best_email TEXT,
  best_phone TEXT,
  source_url TEXT,
  diagnostic_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.4. `research_metrics`

```sql
CREATE TABLE IF NOT EXISTS research_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  metric_name TEXT,
  metric_value REAL,
  metric_text TEXT,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.5. `parser_health`

```sql
CREATE TABLE IF NOT EXISTS parser_health (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  status TEXT NOT NULL,
  drift_score REAL,
  success_rate REAL,
  error_rate REAL,
  last_good_at TEXT,
  last_bad_at TEXT,
  diagnostic_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.6. `manual_validation_queue`

```sql
CREATE TABLE IF NOT EXISTS manual_validation_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER,
  contact_id INTEGER,
  company_name TEXT,
  field_name TEXT,
  field_value TEXT,
  evidence_url TEXT,
  model_confidence REAL,
  human_status TEXT DEFAULT 'pending',
  human_label TEXT,
  human_comment TEXT,
  reviewed_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.7. `gold_dataset_results`

```sql
CREATE TABLE IF NOT EXISTS gold_dataset_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  benchmark_run_id INTEGER,
  gold_company_key TEXT,
  expected_field TEXT,
  expected_value TEXT,
  predicted_value TEXT,
  match_type TEXT,
  precision_hit INTEGER,
  recall_hit INTEGER,
  source TEXT,
  confidence REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 17.8. `suppression_list`

```sql
CREATE TABLE IF NOT EXISTS suppression_list (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,
  domain TEXT,
  reason TEXT,
  bounce_count INTEGER DEFAULT 0,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 18. МЕТРИКИ ЭФФЕКТИВНОСТИ

В конце каждого запуска считать:

```yaml
run_metrics:
  queries_total
  search_results_total
  candidate_companies_total
  duplicate_companies_skipped
  companies_enriched
  contacts_saved
  rejected_total
  rejection_reasons_count
  avg_lead_score
  avg_email_confidence
  avg_phone_confidence
  avg_website_confidence
  source_success_rate
  source_error_rate
  cache_hit_rate
  egrul_success_rate
  official_site_found_rate
  contact_found_rate
  personal_email_found_rate
  generic_email_found_rate
  phone_found_rate
  inn_found_rate
  region_match_rate
  benchmark_precision_company
  benchmark_precision_email
  benchmark_precision_phone
  benchmark_recall_company
  benchmark_recall_email
  human_validation_precision
  parser_drift_events
  degraded_sources_count
  bounce_rate_by_source
```

### 18.1. Минимальные целевые метрики для статуса 10/10

```yaml
minimum_quality_bar_for_10_10:
  company_identity_precision: ">= 0.92 on validation sample"
  official_website_precision: ">= 0.90 on validation sample"
  generic_email_precision: ">= 0.85 on validation sample"
  phone_precision: ">= 0.82 on validation sample"
  inn_precision: ">= 0.95 on validation sample"
  rejected_reason_coverage: ">= 0.98"
  fields_with_evidence: "1.00"
  paid_api_calls: "0"
  captcha_bypass_attempts: "0"
```

### 18.2. Benchmark protocol

```yaml
benchmark_protocol:
  dataset: local gold dataset, CSV/JSONL, no paid sources
  minimum_size:
    companies: 100
    regions: [moscow, mo, russia]
    segments_per_run: at_least_3
  labels:
    - company_name
    - inn
    - official_website
    - generic_email
    - office_phone
    - director_name_if_public
  measurements:
    - precision_by_field
    - recall_by_field
    - source_precision
    - source_coverage
    - time_per_saved_contact
    - cache_hit_rate
    - parser_drift_rate
  rule: architecture is 10/10 only if quality is measured, not assumed
```

### 18.3. Human validation loop

```yaml
human_validation:
  sample_rate_default: 0.10
  oversample_low_confidence: true
  oversample_new_or_degraded_sources: true
  labels: [correct, incorrect, outdated, ambiguous, other_company, not_publicly_verifiable]
  feedback_effect:
    - recalibrate source reliability
    - update parser health
    - add suppression entries
    - update negative keywords
    - update official website detector rules
```

### 18.4. Пример отчёта

```text
Найдено кандидатов: 184
Обогащено компаний: 37
Сохранено контактов: 12
Отклонено: 25
Средний lead_score: 0.81
Cache hit rate: 42%
Лучший источник discovery: checko.ru + DDG
Главная причина отказа: email_domain_mismatch
```

---

## 19. REJECT REASONS

```python
REJECT_REASONS = {
    'duplicate_company',
    'duplicate_email',
    'duplicate_inn',
    'low_lead_score',
    'low_field_confidence',
    'no_required_email',
    'no_required_phone',
    'no_required_website',
    'no_required_inn',
    'website_is_aggregator',
    'website_confidence_low',
    'email_invalid_format',
    'email_freemail_not_corporate',
    'email_domain_mismatch',
    'email_generic_but_personal_required',
    'phone_invalid',
    'mobile_phone_without_lpr_context',
    'director_invalid',
    'director_conflict',
    'region_mismatch',
    'segment_mismatch',
    'source_unavailable',
    'captcha_required',
}
```

---

## 20. ПСЕВДОКОД ОСНОВНОГО WORKER

```python
def _research_worker(run_id, config):
    ctx = prepare_research_environment(config)
    target = config.get('count', 10)

    queries = build_free_query_pool(config)
    candidate_queue = PriorityQueue()

    for query in queries:
        if ctx.saved_count >= target:
            break

        results = free_search(query, ctx)
        ctx.metrics.add('search_results_total', len(results))

        companies = extract_companies_from_results(results)
        for candidate in companies:
            candidate = normalize_and_score_candidate(candidate, ctx)

            if is_duplicate_candidate(candidate, ctx):
                save_rejected(candidate, 'duplicate_company')
                continue

            if candidate.priority_score < 0.45 and candidate_queue.size() > target * 8:
                save_rejected(candidate, 'low_priority_before_enrichment')
                continue

            candidate_queue.put(candidate.priority_score, candidate)

    while not candidate_queue.empty() and ctx.saved_count < target:
        candidate = candidate_queue.pop_highest()
        candidate.status = 'processing'

        evidence = enrich_company_free(candidate, ctx)
        contact = build_contact_from_evidence(candidate, evidence, ctx)

        validation = validate_contact(contact, config, ctx)
        if not validation.accepted:
            save_rejected(candidate, validation.reason, contact, evidence)
            continue

        contact_id = save_contact(contact)
        save_evidence(contact_id, evidence)
        ctx.saved_count += 1

    if ctx.config.get('benchmark_mode'):
        run_gold_dataset_benchmark(ctx)

    enqueue_human_validation_sample(run_id, ctx)
    update_parser_health_report(run_id, ctx)
    apply_free_feedback_to_scoring_weights(ctx)

    finalize_run_metrics(run_id, ctx)
    set_run_status(run_id, 'done')
```

---

## 21. СТРУКТУРА ФАЙЛОВ ПРОЕКТА ПОСЛЕ УЛУЧШЕНИЯ

```text
webapp/
├── researcher.py                 — orchestration, worker, UI integration
├── research_sources.py           — бесплатные источники и fetchers
├── research_search.py            — FreeSearchProvider, DDG, HTML search fallback
├── research_egrul.py             — nalog.ru client + cache
├── research_crawler.py           — safe crawl official websites
├── research_extractors.py        — regex/html/pdf/local LLM extractors
├── research_scoring.py           — FieldConfidence, LeadScore, source reliability
├── research_validation.py        — validation gates, email/domain/phone checks
├── research_cache.py             — http/dns/egrul/cache helpers
├── research_rate_limit.py        — per-domain limiter, retry, backoff
├── research_metrics.py           — metrics collector and reports
├── research_parser_health.py     — parser health checks, drift detection, source versioning
├── research_benchmark.py         — local gold dataset benchmark and regression tests
├── research_feedback.py          — manual validation, bounce/reply feedback, suppression list
├── research_models.py            — dataclasses and typed dicts
├── app.py                        — Flask routes
├── database.py                   — SQLite schema and migrations
├── validator.py                  — MX validation, DNS cache
├── RESEARCH_RULES.md             — immutable rules
├── SEARCH_ARCHITECTURE.md        — this architecture map
└── data/contacts.db              — SQLite DB
```

---

## 22. ФУНКЦИИ, КОТОРЫЕ НУЖНО ДОБАВИТЬ

```python
# research_sources.py
free_search(query, ctx) -> list[SearchResult]
fetch_with_cache(url, ctx, source_type) -> FetchResult
safe_fetch_domain(url, ctx) -> FetchResult

# research_egrul.py
fetch_egrul_by_name(name, region=None) -> EgrulResult | None
fetch_egrul_by_inn(inn) -> EgrulResult | None

# research_crawler.py
find_official_website(candidate, evidence) -> WebsiteCandidate | None
crawl_official_site(website, ctx) -> list[PageContent]
extract_pdf_text_from_official_site(url, ctx) -> str | None

# research_extractors.py
extract_legal_entities(text) -> list[CandidateCompany]
extract_contacts_regex(text) -> ExtractedContactFields
extract_director_regex(text) -> Person | None
extract_requisites_regex(text) -> Requisites
structure_with_local_llm(text, known_fields) -> ExtractedContactFields

# research_scoring.py
score_candidate_company(candidate, evidence) -> float
score_field(field_name, value, evidence) -> FieldConfidence
score_lead(contact, evidence) -> LeadScore

# research_validation.py
validate_contact(contact, config, ctx) -> ValidationResult
email_belongs_to_company(email, company_name, website) -> bool
validate_official_website(url, company_name, inn, html) -> bool

# research_metrics.py
record_metric(run_id, name, value, source=None)
build_run_report(run_id) -> ResearchRunReport

# research_parser_health.py
record_parser_health(source, parser_version, status, drift_score, diagnostic)
run_parser_snapshot_tests() -> ParserHealthReport
fallback_extract_with_readability_or_regex(html) -> ExtractedContactFields

# research_benchmark.py
run_gold_dataset_benchmark(ctx) -> BenchmarkReport
compare_against_previous_benchmark(report) -> RegressionReport

# research_feedback.py
enqueue_human_validation_sample(run_id, ctx)
apply_manual_validation_feedback(ctx)
import_bounce_feedback_from_local_mailbox_or_csv(ctx)
update_suppression_list(email=None, domain=None, reason=None)
apply_free_feedback_to_scoring_weights(ctx)
```

---

## 23. ПРАВИЛА СОХРАНЕНИЯ

Контакт сохраняется, если:

```text
1. Выполнены требования пользователя.
2. lead_score >= quality_threshold.
3. Все обязательные поля имеют confidence >= min_field_confidence.
4. Нет конфликта ИНН/домена/региона.
5. Email, если есть, принадлежит компании.
6. Website, если есть, является официальным сайтом.
7. Источник каждого ключевого поля сохранён в contact_evidence.
```

### 23.1. Multi-email

```python
if personal_email and generic_email:
    create_two_rows = True
    # но обе строки связываются через same company_key/contact_group_id
elif email:
    create_one_row = True
else:
    create_phone_or_inn_only_row_if_requirements_allow = True
```

---

## 24. БЕЗОПАСНОСТЬ И COMPLIANCE

```yaml
security_rules:
  - never_log_passwords
  - never_log_smtp_pass
  - parameterized_sql_only
  - no_captcha_bypass
  - no_paid_api_usage
  - respect_robots_txt_by_default
  - no_aggressive_scraping
  - no_private_data_invention
  - no_contacts_without_source_attribution
  - no_aggressive_smtp_probe
  - honor_suppression_list
  - store_only_business_contact_evidence_needed_for_outreach
  - log_paid_api_calls_as_policy_violation
```

```yaml
free_only_enforcement:
  env_guard:
    - fail_if_TAVILY_API_KEY_required
    - fail_if_GROQ_API_KEY_required
    - warn_if_any_paid_provider_enabled
  runtime_guard:
    - every external call must have provider_type in [free_public, official_site, local_cache, local_llm]
    - paid_provider_call_count must equal 0
    - benchmark report must include paid_provider_call_count
```

---

## 25. ПЛАН ВНЕДРЕНИЯ

### Этап 1 — быстрый прирост качества

1. Убрать Tavily/Groq из обязательного пути.
2. Добавить `contact_evidence`.
3. Добавить `lead_score` и `field_confidence`.
4. Добавить reject reasons.
5. Добавить source attribution в UI.

### Этап 2 — устойчивость

1. Добавить `http_cache`.
2. Добавить `RateLimitManager`.
3. Добавить retry/backoff.
4. Добавить `rejected_candidates`.
5. Добавить resume после сбоя.

### Этап 3 — качество поиска

1. Добавить priority queue кандидатов.
2. Улучшить официальный сайт detection.
3. Добавить safe crawl страниц `/contacts`, `/rekvizity`, `/about`.
4. Добавить PDF extraction для официальных реквизитов.
5. Добавить cross-source agreement.

### Этап 4 — аналитика 10/10

1. Добавить `research_metrics`.
2. Добавить отчёт запуска.
3. Добавить dashboard качества источников.
4. Добавить рекомендации по следующим запросам.
5. Добавить автонастройку query pool по успешным источникам.

### Этап 5 — доказуемое качество 10/10

1. Создать локальный `gold_dataset` минимум на 100 компаний.
2. Добавить benchmark-run после каждого изменения extractor/scoring.
3. Добавить regression gate: не деплоить, если precision/recall упали ниже порога.
4. Добавить manual validation queue на 10% результатов.
5. Добавить source/parser health dashboard.
6. Добавить suppression list и bounce feedback import из собственных кампаний.
7. Добавить версионирование extractor-ов и snapshot-тесты HTML.

---

## 26. ЧЕКЛИСТ 10/10

```text
[ ] Система запускается без TAVILY_API_KEY
[ ] Система запускается без GROQ_API_KEY
[ ] Все remote LLM отключены
[ ] Ollama используется только локально и опционально
[ ] Каждое поле имеет source_url
[ ] Каждое поле имеет confidence
[ ] Каждый отказ имеет reject_reason
[ ] Есть http_cache
[ ] Есть egrul_cache
[ ] Есть RateLimitManager
[ ] Есть retry/backoff
[ ] Есть official website validation
[ ] Есть email domain ownership validation
[ ] Есть personal/generic email split
[ ] Есть mobile/generic phone split
[ ] Есть region confidence
[ ] Есть lead_score
[ ] Есть metrics report
[ ] Есть rejected_candidates table
[ ] Есть source success-rate analytics
[ ] Есть локальный gold dataset
[ ] Есть benchmark protocol
[ ] Есть human validation queue
[ ] Есть parser health checks
[ ] Есть source drift detection
[ ] Есть source/extractor versioning
[ ] Есть suppression list
[ ] Есть bounce feedback loop без платных API
[ ] paid_provider_call_count == 0
[ ] Нет f-string SQL
[ ] Нет обхода капчи
[ ] Нет сохранения контактов без evidence
```

---

## 27. ИТОГОВАЯ ОЦЕНКА ПОСЛЕ ВНЕДРЕНИЯ

| Компонент | Было | Стало |
|---|---:|---:|
| Бесплатность | 6/10 | 10/10 |
| Discovery компаний | 8/10 | 10/10 |
| Поиск ЛПР | 7/10 | 9/10 |
| Поиск общих контактов | 8/10 | 10/10 |
| Поиск персональных контактов | 6/10 | 10/10 методологически; 8–9/10 фактически из-за непубличности данных |
| Валидация | 8/10 | 10/10 |
| Надёжность | 6.5/10 | 10/10 |
| Масштабируемость | 6/10 | 10/10 |
| Измеримость | 4/10 | 10/10 |
| Production-readiness | 6/10 | 10/10 |

**Финальная архитектурная оценка: 10/10** для бесплатной системы поиска компаний и контактов, потому что эффективность достигается не платными API, а правильной структурой: evidence-first, scoring, кэш, rate limits, строгая валидация, локальный LLM, benchmark protocol, human validation loop, parser health, source drift detection, suppression list и измеримые метрики.

Важно: даже архитектура 10/10 не гарантирует 100% нахождение персональных email и мобильных телефонов ЛПР, потому что такие данные часто непубличны. Но система будет максимально эффективно использовать бесплатные публичные источники и честно показывать confidence каждого результата.


---

## 28. ЧТО ИМЕННО ИСПРАВЛЕНО В ЭТОЙ ВЕРСИИ

Эта версия закрывает слабые места предыдущей архитектуры и делает оценку 10/10 обоснованной:

1. Добавлен **benchmark protocol**: качество не предполагается, а измеряется на локальном gold dataset.
2. Добавлен **human validation loop**: 10% результатов проверяются вручную, а feedback меняет веса scoring.
3. Добавлен **parser health monitoring**: система видит, когда HTML-источник сломался или поменял структуру.
4. Добавлен **source drift detection**: деградировавшие источники не портят базу низкокачественными контактами.
5. Добавлен **fallback extraction** через regex/readability/local parser без платных API.
6. Добавлен **suppression list** и bounce feedback из собственных кампаний.
7. Добавлено **source/extractor versioning** и snapshot-тесты.
8. Добавлена защита от переноса контактов другой компании.
9. Добавлены минимальные метрики качества для статуса 10/10.
10. Добавлен runtime-контроль: `paid_provider_call_count` всегда должен быть равен 0.

Главное правило сохранено: **никаких платных подписок, платных enrichment API, платных LLM API и платного поиска**. Система остаётся free-first/offline-first и использует только публичные бесплатные источники, локальный кэш, локальный LLM и собственные данные качества.
