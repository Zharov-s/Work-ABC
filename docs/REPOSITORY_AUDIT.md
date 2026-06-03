# REPOSITORY AUDIT
Дата аудита: 2026-06-03  
Аудитор: Claude (Этап 0 — только чтение, без изменений кода)

---

## 1. Текущий стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.x |
| Веб-фреймворк | Flask 3.1.0 |
| WSGI-сервер | Gunicorn 23.0.0 |
| База данных | SQLite (файл `data/contacts.db`) |
| Шаблонизатор | Jinja2 (встроен в Flask) |
| Frontend | Vanilla JS + CSS Custom Properties |
| Email | SMTP via `smtplib` (Mail.ru, ssl 465) |
| AI / LLM | Groq (llama-3.3-70b) или Ollama (gemma3:4b) |
| Веб-поиск | Tavily API + DDG (`ddgs`) |
| Excel-экспорт | openpyxl |
| Email-валидация | dnspython (MX lookup) |
| Авторизация | bcrypt + Flask session |
| Переменные окружения | python-dotenv |
| Деплой | Railway (Nixpacks + Procfile) |
| Локальный запуск | `start.sh` → `python3 app.py` |

---

## 2. Текущая структура проекта

```
webapp/
├── app.py                   # Flask-приложение: все маршруты и логика
├── auth.py                  # bcrypt: проверка логина/пароля
├── database.py              # SQLite схема, миграции, get_db(), helper-функции
├── mailer.py                # SMTP-рассылка, трекинг, bounce, reply scanning
├── researcher.py            # ИИ-поиск новых компаний через Tavily/Ollama/Groq
├── research_cache.py        # HTTP-кэш для исследований
├── research_models.py       # Модели данных для researcher
├── research_scoring.py      # Скоринг лидов
├── validator.py             # MX-валидация email
├── requirements.txt
├── .env / .env.example
├── Procfile
├── railway.toml
├── start.sh
├── templates/
│   ├── base.html            # Общий layout с сайдбаром, уведомлениями, темами
│   ├── dashboard.html       # Главная страница
│   ├── contacts.html        # Таблица контактов с фильтрами
│   ├── research.html        # Поиск новых компаний через ИИ
│   ├── campaigns.html       # Рассылки
│   ├── campaign_detail.html # Детальная статистика кампании
│   ├── settings.html        # Настройки SMTP, учётные данные
│   ├── login.html
│   ├── unsubscribe.html
│   └── macros/icon.html     # SVG-иконки через Jinja macro
├── static/
│   ├── css/main.css         # Весь CSS одним файлом
│   ├── css/filter_tree.css  # CSS для дерева ОКВЭД-фильтров
│   ├── js/main.js           # Весь JS одним файлом
│   ├── js/filter_data.js    # Данные ОКВЭД дерева
│   ├── js/filter_tree.js    # Логика дерева фильтров
│   └── icons/               # SVG-иконки (38 файлов)
├── email_templates/
│   ├── mitino/              # HTML+plain шаблон: "Аренда Митино"
│   └── grekova/             # HTML+plain шаблон: "Грекова, продажа"
└── data/
    └── contacts.db          # SQLite база данных (gitignored)
```

---

## 3. Как запускается приложение

**Локально:**
```bash
bash start.sh
# → python3 app.py
# → http://127.0.0.1:5050
```

**Продакшн (Railway):**
```
gunicorn app:app --workers=1 --bind=0.0.0.0:$PORT --timeout=120
```

**Порт:** 5050 локально, `$PORT` на Railway.

**Инициализация при старте (app.py, строки 891-906):**
- `init_db()` — создаёт таблицы и запускает миграции
- Помечает незавершённые research runs как `interrupted`
- Удаляет старые спам-уведомления
- Запускает фоновый поток `bounce-checker` (каждые 30 мин)

---

## 4. База данных

**Файл:** `data/contacts.db` (SQLite, gitignored)  
**Инициализация:** `database.py → init_db()`

### Таблицы:

| Таблица | Назначение |
|---|---|
| `contacts` | Основная база контактов / компаний (смешанная модель) |
| `send_history` | История кампаний/отправок |
| `send_recipients` | Получатели каждой отправки + статус + tracking token |
| `mailing_recipients` | Денормализованная таблица для управления рассылками |
| `research_runs` | История ИИ-поисков |
| `settings` | Ключ-значение: SMTP, URL, авторизация |
| `email_opens` | Открытия писем (трекинг-пиксель) |
| `email_clicks` | Клики и отписки (трекинг ссылок) |
| `notifications` | Уведомления (bounce, reply, ooo) |
| `http_cache` | HTTP-кэш для researcher |
| `contact_evidence` | Доказательная база для найденных контактов |
| `rejected_candidates` | Отклонённые кандидаты research |
| `research_metrics` | Метрики качества research |
| `parser_health` | Здоровье парсеров |
| `manual_validation_queue` | Очередь ручной валидации |
| `gold_dataset_results` | Бенчмарк researcher |
| `suppression_list` | Список подавления email |

### Ключевые проблемы схемы:

1. **Таблица `contacts` = компания + контакт одновременно** — нет отдельных `companies`, `company_channels`, `company_okveds`
2. Поле `okved` — одна строка, не нормализованная; нет дерева ОКВЭД в БД
3. Нет `company_id` как стабильного строкового ключа — только `id INTEGER`
4. Нет `contact_change_log`
5. Нет `external_company_candidates`
6. Нет `email_campaigns` / `email_campaign_recipients`
7. UNIQUE constraint по `email` ограничивает хранение нескольких email одной компании

---

## 5. Маршруты страниц

| URL | Функция | Шаблон |
|---|---|---|
| `/` | `dashboard()` | `dashboard.html` |
| `/login` | `login()` | `login.html` |
| `/logout` | `logout()` | redirect |
| `/contacts` | `contacts()` | `contacts.html` |
| `/research` | `research()` | `research.html` |
| `/campaigns` | `campaigns()` | `campaigns.html` |
| `/campaigns/<id>` | `campaign_detail()` | `campaign_detail.html` |
| `/settings` | `settings()` | `settings.html` |
| `/unsubscribe/<token>` | `unsubscribe()` | `unsubscribe.html` |
| `/preview/<key>` | `preview_template()` | HTML-ответ |

**Отсутствуют страницы:**
- `/companies` — нет (есть `/contacts` со смешанной логикой)
- `/search` — нет отдельной страницы поиска новых компаний
- `/stats` — нет страницы статистики
- `/health` — нет эндпоинта

---

## 6. API-эндпоинты

| URL | Метод | Назначение |
|---|---|---|
| `/contacts/add` | POST | Добавить контакт |
| `/contacts/<id>/delete` | POST | Удалить (нет soft-delete!) |
| `/contacts/<id>/status` | POST | Обновить статус |
| `/contacts/export` | GET | Экспорт в XLSX |
| `/contacts/validate-emails` | POST | Batch MX-валидация |
| `/research/start` | POST | Запуск ИИ-поиска |
| `/research/run/<id>/pause` | POST | Пауза |
| `/research/run/<id>/resume` | POST | Возобновить |
| `/research/run/<id>/finish` | POST | Завершить |
| `/research/run/<id>/contacts` | GET | Контакты из рана |
| `/research/run/<id>/delete` | POST | Удалить ран |
| `/research/status/<id>` | GET | Статус рана |
| `/campaigns/send` | POST | Отправить вручную |
| `/campaigns/send-pending` | POST | Отправить pending |
| `/campaigns/<id>/retry` | POST | Повторить |
| `/campaigns/<id>/status` | GET | Статус кампании |
| `/campaigns/check-bounces` | POST | Проверить bounce |
| `/campaigns/scan-replies` | POST | Сканировать ответы |
| `/api/contacts/for-campaign` | GET | Контакты для пикера |
| `/api/notifications` | GET | Список уведомлений |
| `/api/notifications/count` | GET | Кол-во непрочитанных |
| `/api/notifications/<id>/read` | POST | Прочитать |
| `/api/notifications/read-all` | POST | Прочитать все |
| `/track/o/<token>` | GET | Трекинг-пиксель (открытие) |
| `/track/c/<token>` | GET | Трекинг клика |
| `/settings/save` | POST | Сохранить настройки |
| `/settings/test-smtp` | POST | Тест SMTP |

**Отсутствуют API:**
- `GET /health`
- `POST /api/companies/filter`
- `GET /api/filters/okved-tree`
- `GET /api/companies/:id/card`
- `POST /api/search/external`
- `POST /api/search/candidates/:id/import`

---

## 7. HTML-рассылки (mailer.py)

**Статус: РАБОТАЕТ, НЕ ЛОМАТЬ.**

**Логика:**
- `TEMPLATE_META` — словарь с 2 шаблонами: `mitino`, `grekova`
- Два режима отправки:
  - **Режим A (с трекингом):** `tracking_base_url` задан → каждый получатель получает уникальный токен, HTML инжектируется трекинг-пиксель и перезаписываются ссылки
  - **Режим B (BCC-батчи, без трекинга):** базовый режим, пачки по 29 адресов
- Retry: 3 попытки с паузой 20-30 сек
- Bounce-проверка: IMAP polling (Mail.ru) каждые 30 мин в фоновом потоке
- Reply-scanning: сканирование IMAP входящих на предмет ответов
- Bounce-правило двух сигналов: `bounce_count >= 2` → `status=unsubscribed`
- Tracking: `email_opens`, `email_clicks`, `send_recipients.tracking_token`

**Файлы шаблонов:**
- `email_templates/mitino/email-cdn-template.html` + `plain-text.txt`
- `email_templates/grekova/email-cdn-template.html` + `plain-text.txt`

---

## 8. Поиск новых компаний (researcher.py)

**Статус: РАБОТАЕТ, сложный, 2523 строки.**

**Логика:**
- Веб-поиск через Tavily API (основной) или DDG (fallback)
- LLM: Groq (llama-3.3-70b, если есть ключ) или Ollama (gemma3:4b)
- Сегменты: 7 типов (SEGMENT_LABELS)
- Регионы: Москва, МО, вся Россия
- Требования к контакту: настраиваемый комплект полей
- Сохраняет результаты в таблицу `contacts` напрямую (нет стадии кандидата)
- Запускается в отдельном потоке через `ThreadPoolExecutor`
- Поддерживает pause/resume/finish через threading.Event

**Проблемы:**
- Найденные внешние компании сразу попадают в `contacts` без стадии review/candidate
- Нет дедупликации по ИНН/домену перед сохранением
- Нет провайдер-архитектуры (нет интерфейса для Контур/DaData)

---

## 9. Импорт контактов

Скрипты `import_*.py` находятся в `/Desktop/work/` (не в webapp, gitignored).  
Не интегрированы в веб-интерфейс — только ручной запуск из терминала.

---

## 10. Что сейчас РАБОТАЕТ

- Логин/логаут (bcrypt)
- Dashboard с базовой статистикой
- Таблица контактов с фильтрами (сегмент, регион, статус, ОКВЭД)
- Экспорт в XLSX
- HTML-рассылки (SMTP, батчи, трекинг открытий/кликов)
- Bounce-checker (IMAP polling)
- Reply-scanner (IMAP)
- Уведомления (bounce, reply, ooo)
- ИИ-поиск новых компаний (Tavily + Groq/Ollama)
- Пауза/возобновление/завершение поиска
- MX-валидация email
- SMTP-тест
- Тёмная/светлая тема
- Трекинг-пиксель и клики

---

## 11. Что работает НЕКОРРЕКТНО или ОТСУТСТВУЕТ

### Критические отсутствия:

1. **Нет страницы "Компании"** — есть "Контакты", смешивающая компании и контакты
2. **Нет страницы "Поиск" с ОКВЭД-фильтрами** — поиск только через ИИ
3. **Нет страницы "Статистика"**
4. **Нет `/health` endpoint** — healthcheck идёт через `/login`
5. **Нет карточки компании** — нет drawer/modal с деталями по клику
6. **Нет дерева ОКВЭД в БД** — фильтр работает как LIKE-поиск по строке
7. **Нет новых таблиц** — `companies`, `company_channels`, `company_okveds`, `external_company_candidates`, `contact_change_log`
8. **Найденные внешние компании не изолированы** — сразу в `contacts`
9. **Нет `start.html`** — нет запуска с рабочего стола

### Технический долг:

10. `app.py` = монолит (934 строки, все маршруты, нет разделения)
11. `researcher.py` = 2523 строки, монолит, нет unit-тестов
12. Все стили в одном `main.css`, весь JS в одном `main.js`
13. В `database.py` есть хардкод SMTP-пароля в `DEFAULT_SETTINGS`
14. Нет тестов

---

## 12. Файлы которые НЕЛЬЗЯ ЛОМАТЬ

| Файл | Причина |
|---|---|
| `mailer.py` | HTML-рассылка работает; трекинг, bounce, reply активны |
| `email_templates/mitino/` | Рабочий HTML-шаблон рассылки |
| `email_templates/grekova/` | Рабочий HTML-шаблон рассылки |
| `data/contacts.db` | Реальные данные; деструктивные изменения схемы запрещены |
| `auth.py` | Рабочая авторизация |
| `.env` | Реальные ключи (не в git) |
| `researcher.py` | Работающий поиск; правки только по RESEARCH_RULES.md |

---

## 13. Файлы для рефакторинга

| Файл | Что нужно |
|---|---|
| `app.py` | Разбить на `routes/*.py`, вынести логику в `services/*.py` |
| `database.py` | Добавить новые таблицы через миграции (не DROP) |
| `researcher.py` | Обернуть в provider-архитектуру, добавить стадию кандидатов |
| `static/css/main.css` | Разбить по модулям |
| `static/js/main.js` | Разбить по модулям |

---

## 14. Пакеты данных (готовы к подключению)

В `/Desktop/hunter/companies_ai_dataset_package/data/`:

| Файл | Строк | Описание |
|---|---|---|
| `companies.csv` | 3059 | Компании с ИНН, адресом, сайтом, ОКВЭД, отраслью |
| `company_channels.csv` | ~23700 | Каналы связи (email + phone) с sendable_status |
| `company_emails.csv` | — | Только email-каналы |
| `company_phones.csv` | — | Только телефонные каналы |
| `raw_contacts_preserved.csv` | — | Исходные контакты (сохранить!) |

**Ключевые поля companies.csv:**
- `company_id` — стабильный ключ (`cmp_000001` и т.д.)
- `inn`, `registration_address`, `website`
- `okved_main_code`, `okved_status`, `okved_section`
- `industry_group_final`, `activity_type_final`
- `match_status`, `confidence_score`

**Важно:** У большинства компаний `okved_status = okved_not_found_needs_external_source` — ОКВЭД не найден в справочниках. Нужен добор через ФНС/Контур/DaData по ИНН.

---

## 15. Риски перед пересборкой

| Риск | Уровень | Митигация |
|---|---|---|
| Поломка рабочей рассылки | КРИТИЧЕСКИЙ | Копия в `_legacy_snapshot/`, не трогать `mailer.py` |
| Потеря данных contacts.db | КРИТИЧЕСКИЙ | Миграции backward-compatible, backup перед этапом |
| Поломка researcher.py | ВЫСОКИЙ | Обёртка, не переписывать |
| SMTP-пароль в коде (database.py DEFAULT_SETTINGS) | ВЫСОКИЙ | Вынести в .env до деплоя |
| Конфликт схемы при добавлении таблиц | СРЕДНИЙ | ALTER TABLE + миграции, не DROP |
| Дублирование данных при импорте CSV | СРЕДНИЙ | Проверка по email/company_id перед INSERT |

---

*Файл создан на Этапе 0. Обновлять при изменениях схемы и архитектуры.*
