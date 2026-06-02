# ABCENTRUM Outreach Platform — CLAUDE.md

---

## ⚡ ECC — ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА (АКТИВНЫ В КАЖДОЙ СЕССИИ)

> Эти правила имеют НАИВЫСШИЙ приоритет. Они не опциональны. Каждое новое действие — проверяй таблицу ниже.

### ОБЯЗАТЕЛЬНЫЕ ТРИГГЕРЫ → АГЕНТ/СКИЛЛ

| Когда | ОБЯЗАТЕЛЬНО сделать | Команда |
|-------|---------------------|---------|
| **Любой новый Python-код или изменение `.py`** | Спавнить агент `python-reviewer` | `Agent(subagent_type="python-reviewer")` |
| **Изменение SQL-запросов, `database.py`** | Спавнить агент `database-reviewer` | `Agent(subagent_type="database-reviewer")` |
| **Изменение `auth.py`, паролей, сессий, SMTP** | Спавнить агент `security-reviewer` | `Agent(subagent_type="security-reviewer")` |
| **Изменение Flask-роутов, шаблонов Jinja2** | Спавнить агент `django-reviewer` | `Agent(subagent_type="django-reviewer")` |
| **Любое изменение кода** | Запустить `/code-review` или агент `code-reviewer` | `Skill("code-review")` |
| **Перед реализацией новой фичи** | Запустить `/plan` или `/feature-dev` | `Skill("plan")` |
| **После реализации фичи** | Проверить работу через `/run` и `/verify` | `Skill("run")`, `Skill("verify")` |
| **Build-ошибки / ошибки импорта** | Агент `build-error-resolver` | `Agent(subagent_type="build-error-resolver")` |
| **Безопасность: XSS, SQLi, secrets** | `/security-review` + `/security-scan` | `Skill("security-review")` |

### ЖЁСТКИЕ ПРАВИЛА ECC

1. **NEVER** изменять Python-файлы без последующего `python-reviewer` агента
2. **NEVER** коммитить без `/code-review` или `code-reviewer`
3. **ALWAYS** использовать `/plan` перед реализацией новой функциональности (3+ файлов)
4. **ALWAYS** использовать агент `security-reviewer` при изменении `auth.py`, `mailer.py`, `app.py` (роуты)
5. **ALWAYS** спавнить агенты параллельно когда задачи независимы
6. **NEVER** добавлять заглушки обработки ошибок без явного указания пользователя
7. ECC rules из `.claude/rules/ecc/` — **ЧИТАЮТСЯ АВТОМАТИЧЕСКИ** при каждой сессии

### ДОСТУПНЫЕ ECC СКИЛЛЫ ДЛЯ ЭТОГО ПРОЕКТА

```
/python-review      — ревью Python-кода
/code-review        — общий ревью (+ ultra для глубокого)
/security-review    — безопасность (OWASP, secrets, SQLi, XSS)
/security-scan      — автоматическое сканирование на уязвимости
/plan               — планирование реализации
/feature-dev        — разработка фичи по TDD-циклу
/run                — запуск приложения и проверка в браузере
/verify             — верификация что изменение работает
/fastapi-review     — ревью Flask/FastAPI паттернов
/simplify           — упрощение и очистка кода
/tdd-guide          — TDD-workflow
/update-docs        — обновление документации
```

---

## Проект

**ABCENTRUM Outreach Platform** — единый веб-интерфейс для поиска арендаторов промышленного парка «Промтехнопарк Митино» (Москва, Барышиха 37а, 11 776 м²) и email-рассылок ЛПР.

```
/Desktop/work/
├── webapp/              ← Flask-приложение (Python, SQLite, SMTP, Tavily+Ollama)
├── Research/            ← Скрипты и данные поиска ЛПР
├── mitino-email_html/   ← HTML-шаблон письма «Митино»
└── grekova_email_html/  ← HTML-шаблон письма «Грекова 5-7»
```

**Запуск:** `cd webapp && ./start.sh` → http://127.0.0.1:5050

---

## Технологический стек

- **Backend:** Python 3 + Flask (app.py)
- **БД:** SQLite (`webapp/data/contacts.db`)
- **AI Research:** Ollama qwen2.5:1.5b (локально) + Tavily (веб-поиск)
- **Email:** SMTP Mail.ru, BCC-батчи ≤ 30 адресов
- **Деплой:** Railway (Procfile + railway.toml) или локально

---

## Ключевые файлы

| Файл | Назначение |
|------|-----------|
| `webapp/app.py` | Flask-роуты: dashboard, contacts, research, campaigns, settings, tracking |
| `webapp/researcher.py` | Поиск ЛПР: Tavily + Ollama, многопроходный, правила Research |
| `webapp/mailer.py` | SMTP-отправка, BCC, батчи, трекинг открытий/кликов |
| `webapp/database.py` | Схема SQLite, хелперы get_db/init_db, mailing helpers |
| `webapp/auth.py` | Логин/пароль (bcrypt) |
| `webapp/validator.py` | MX-валидация email |
| `webapp/RESEARCH_RULES.md` | ⚠️ ПРАВИЛА ПОИСКА — читать ПЕРЕД правкой researcher.py |

---

## ⚠️ КРИТИЧЕСКИЕ ПРАВИЛА (НЕ МЕНЯТЬ без явного разрешения пользователя)

### Research Rules (webapp/RESEARCH_RULES.md)
1. **Контакт сохраняется только при наличии ВСЕХ выбранных полей** (ФИО + email + телефон по выбору пользователя в UI)
2. **Только новые компании** — дедупликация по имени и email перед каждым поиском
3. **Блокировка общих адресов** — BLOCKED_EMAIL_PREFIXES в researcher.py (info@, sales@, office@ и т.п.)
4. **Модель: qwen2.5:1.5b** — qwen3:4b ЗАПРЕЩЕНА (расходует все токены на "thinking")
5. **8-проходный поиск ЛПР** — rusprofile → email → сайт → телефон → ИНН → 2гис

### Email / SMTP Rules
- Все получатели — **только BCC**, To = s.zharov@abcentrum.ru
- **Макс 30 адресов** за один батч (лимит Mail.ru)
- **SMTP_PASS никогда не логируется** и не попадает в HTML/лог

### SQL Safety
- Всегда использовать параметризованные запросы: `conn.execute('... WHERE id=?', (cid,))`
- Никогда не использовать f-string или конкатенацию с user input в SQL

---

## ECC Skills — ОБЯЗАТЕЛЬНО использовать

> Эти скиллы доступны через `Skill("name")` или как slash-команды `/name`. Их использование НЕ ОПЦИОНАЛЬНО.

| Задача | ОБЯЗАТЕЛЬНЫЙ Skill |
|--------|-------------------|
| Python-код, паттерны | `/python-review`, `python-patterns`, `backend-patterns` |
| API endpoints, маршруты Flask | `/fastapi-review`, `api-design` |
| SQLite / миграции схемы | `database-migrations` + агент `database-reviewer` |
| Безопасность (OWASP, secrets) | `/security-review`, `/security-scan` |
| Email операции | `email-ops` |
| Веб-поиск / research агент | `deep-research`, `research-ops`, `market-research` |
| Тесты (pytest) | `/tdd-guide`, `python-testing` |
| Новая фича | `/plan` → `/feature-dev` → `/verify` |

---

## ECC Agents — ОБЯЗАТЕЛЬНО делегировать

> Агенты спавнятся через `Agent(subagent_type="...")`. Параллельный запуск нескольких — приоритет.

| Агент | ОБЯЗАТЕЛЬНО при |
|-------|----------------|
| `python-reviewer` | **ПОСЛЕ любого изменения `.py`-файла** |
| `database-reviewer` | **ПОСЛЕ изменения `database.py` или SQL** |
| `security-reviewer` | **ПОСЛЕ изменения `auth.py`, `mailer.py`, любых роутов** |
| `django-reviewer` | **ПОСЛЕ изменения Flask-роутов или Jinja2-шаблонов** |
| `code-reviewer` | **ПЕРЕД каждым коммитом** |
| `build-error-resolver` | **ПРИ ЛЮБЫХ ошибках запуска или импорта** |

---

## ECC Rules (загружаются АВТОМАТИЧЕСКИ в каждой сессии)

- `.claude/rules/ecc/python/` — PEP8, type annotations, security, testing
- `.claude/rules/ecc/common/` — git workflow, development workflow, code review
- `.claude/rules/ecc/web/` — HTML/CSS patterns
- Все правила из этих директорий **ОБЯЗАТЕЛЬНЫ** — не игнорировать

---

## ОБЯЗАТЕЛЬНЫЙ Workflow при изменении кода

1. **Перед правкой `researcher.py`** → ОБЯЗАТЕЛЬНО прочитать `webapp/RESEARCH_RULES.md`
2. **ПОСЛЕ изменения ЛЮБОГО Python-кода** → ОБЯЗАТЕЛЬНО спавнить агент `python-reviewer`
3. **При добавлении новых роутов** → ОБЯЗАТЕЛЬНО проверить декоратор `@login_required`
4. **При изменении SQL** → ТОЛЬКО параметризованные запросы (NEVER f-string в SQL)
5. **При изменении mailer.py** → ОБЯЗАТЕЛЬНО убедиться что SMTP_PASS не попадает в лог
6. **ПЕРЕД коммитом** → ОБЯЗАТЕЛЬНО запустить `/code-review` или агент `code-reviewer`

---

## Окружение разработки

```bash
cd /Users/sergeyzharov/Desktop/work/webapp
./start.sh                    # http://127.0.0.1:5050

# Проверить синтаксис
python3 -m py_compile researcher.py

# Зависимости
python3 -m pip install -r requirements.txt
```

### ENV переменные (webapp/.env)
```
SECRET_KEY=...
TAVILY_API_KEY=tvly-dev-...
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:1.5b
GROQ_API_KEY=...    # Альтернатива Ollama — llama-3.3-70b-versatile
```

---

## Skills в этом репозитории

| Файл | Skill |
|------|-------|
| `webapp/researcher.py`, `webapp/*.py` | `python-patterns`, `backend-patterns`, `security-review` |
| `webapp/database.py` | `database-migrations` |
| `webapp/mailer.py` | `email-ops` |
| `webapp/templates/*.html` | `django-patterns` (Jinja2) |
| `webapp/static/**` | web patterns |

---

## Правило иконок — HugeIcons ⚠️ ОБЯЗАТЕЛЬНО

**Все иконки в проекте берутся только из библиотеки HugeIcons.**

- Репозиторий: https://github.com/hugeicons/vue
- Пакет: `@hugeicons/core-free-icons` (5471 бесплатных иконок)
- Стиль: stroke, 24×24, 1.5px, `currentColor`
- SVG-файлы: `/webapp/static/icons/`
- Jinja2-макрос: `/webapp/templates/macros/icon.html`

### Использование в шаблонах:
```jinja
{% from "macros/icon.html" import icon %}
{{ icon("home") }}
{{ icon("bell", size=20, class="my-class") }}
```

### Добавление новой иконки:
1. Найти нужную иконку на https://hugeicons.com/icons
2. Запустить Node.js-скрипт для извлечения (см. выше в истории)
3. Добавить в `/webapp/static/icons/<name>.svg`
4. Добавить в макрос `icon.html`

### Доступные иконки:
`home`, `search`, `contact`, `mail`, `settings`, `bell`, `bell-dot`, `logout`,
`moon`, `sun`, `arrow-left`, `arrow-right`, `eye`, `eye-off`, `refresh`,
`plus`, `check`, `cancel`, `close`, `filter`, `download`, `upload`, `delete`,
`edit`, `pause`, `play`, `stop`, `chart`, `database`, `user`, `users`,
`building`, `send`, `star`, `phone`, `clock`, `check-mark`, `export`
